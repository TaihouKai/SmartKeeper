"""Engine 门面：唯一的游戏逻辑入口。HTTP API 和 KP 只经由这里读写对局。"""

from __future__ import annotations

import copy
import hashlib
import secrets
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import sqlalchemy as sa
from pydantic import JsonValue

from smartkeeper.contracts import (
    ADMIN,
    ENGINE,
    KP,
    AdHocCheck,
    Adjudication,
    Audience,
    CheckResult,
    Dice,
    DiceResult,
    Event,
    EventLog,
    Forbidden,
    Game,
    GameConfig,
    GameSettings,
    IdentityRules,
    IllegalState,
    Intent,
    Location,
    NewEvent,
    NotFound,
    Opening,
    PatchOp,
    Player,
    Problem,
    Round,
    RoundMachine,
    RulePack,
    RulePackStore,
    Rules,
    SheetSubmission,
    SheetView,
    State,
    ValidationFailed,
    Visibility,
    World,
)
from smartkeeper.engine import adjudication as adjv
from smartkeeper.engine import scenario
from smartkeeper.engine.repo import Repo
from smartkeeper.engine.sheetview import build_sheet_views

MAX_TEXT = 4000


def _now() -> str:
    return datetime.now(UTC).isoformat()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _text(text: str, field: str = "text") -> str:
    if not text.strip():
        raise ValidationFailed("text.empty", field=field)
    if len(text) > MAX_TEXT:
        raise ValidationFailed("text.too_long", field=field, max=MAX_TEXT)
    return text


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


class Engine:
    def __init__(
        self,
        *,
        db: sa.Engine,
        events: EventLog,
        packs: RulePackStore,
        rules: Rules,
        world: World,
        rounds: RoundMachine,
        dice: Dice,
    ) -> None:
        self._repo = Repo(db)
        self._events = events
        self._packs = packs
        self._rules = rules
        self._world = world
        self._rounds = rounds
        self._dice = dice
        self._lock = threading.RLock()
        self._state_cache: dict[str, tuple[int, State]] = {}

    # ================= 读取：局、玩家、规则包 =================

    def game(self, game_id: str) -> Game:
        return self._repo.get_game(game_id)

    def list_games(self) -> list[Game]:
        return self._repo.list_games()

    def player(self, player_id: str) -> Player:
        return self._repo.get_player(player_id)

    def players(self, game_id: str) -> list[Player]:
        return self._repo.players(game_id)

    def player_by_token(self, token: str) -> Player | None:
        p = self._repo.player_by_token_hash(hash_token(token))
        return p if p is not None and p.active else None

    def rulepack(self, game_id: str) -> RulePack:
        g = self.game(game_id)
        return self._packs.get_version(g.rulepack_id, g.rulepack_version).pack

    def rulebook(self, game_id: str) -> str:
        return self._rules.render(self.rulepack(game_id))

    def round(self, game_id: str, no: int | None = None) -> Round:
        g = self.game(game_id)
        n = g.current_round if no is None else no
        if n == 0:
            raise NotFound("round.not_started", game_id=game_id)
        return self._repo.get_round(game_id, n)

    def rounds(self, game_id: str) -> list[Round]:
        return self._repo.rounds(game_id)

    def identity_rules(self, game_id: str) -> IdentityRules:
        return scenario.public_meta(self.game(game_id).scenario_public).identities

    def delete_rulepack_version(self, pack_id: str, version: int) -> None:
        used = self._repo.games_using(pack_id, version)
        if used:
            raise IllegalState("rulepack.version_in_use", games=list(used))
        self._packs.delete_version(pack_id, version)

    # ================= 开局与建角 =================

    def create_game(self, config: GameConfig) -> Game:
        self._packs.get_version(config.rulepack_id, config.rulepack_version)  # 必须存在
        scenario.public_meta(config.scenario_public)
        scenario.kp_meta(config.scenario_kp)
        g = Game(
            id="g_" + secrets.token_hex(4),
            name=config.name,
            status="characters",
            rulepack_id=config.rulepack_id,
            rulepack_version=config.rulepack_version,
            map_id=config.map_id,
            scenario_public=config.scenario_public,
            scenario_kp=config.scenario_kp,
            settings=config.settings,
            current_round=0,
        )
        self._repo.insert_game(g, _now())
        return g

    def update_settings(self, game_id: str, settings: GameSettings) -> Game:
        self._repo.update_game(game_id, settings=settings)
        return self.game(game_id)

    def update_materials(
        self,
        game_id: str,
        *,
        scenario_public: str | None = None,
        scenario_kp: str | None = None,
        map_id: str | None = None,
    ) -> Game:
        """开场前可以替换剧本和地图；开场后它们是这一局的固定资料。"""
        g = self.game(game_id)
        if g.current_round != 0:
            raise IllegalState("game.already_started")
        values: dict[str, Any] = {}
        if scenario_public is not None:
            scenario.public_meta(scenario_public)
            values["scenario_public"] = scenario_public
        if scenario_kp is not None:
            scenario.kp_meta(scenario_kp)
            values["scenario_kp"] = scenario_kp
        if map_id is not None:
            values["map_id"] = map_id
        if values:
            self._repo.update_game(game_id, **values)
        return self.game(game_id)

    def add_player(self, game_id: str, display_name: str) -> tuple[Player, str]:
        """返回明文 token，仅此一次。库里只存哈希。"""
        g = self.game(game_id)
        if g.status == "ended":
            raise IllegalState("game.ended")
        name = display_name.strip()
        if not name or len(name) > 64:
            raise ValidationFailed("player.bad_name")
        token = secrets.token_urlsafe(32)
        p = Player(id="p" + secrets.token_hex(4), game_id=game_id, display_name=name)
        self._repo.insert_player(p, hash_token(token), _now())
        return p, token

    def revoke_player(self, player_id: str) -> None:
        self._repo.update_player(player_id, active=False)

    def set_ui_language(self, player_id: str, lang: str) -> None:
        if lang not in ("zh", "en"):
            raise ValidationFailed("player.bad_language")
        self._repo.update_player(player_id, ui_language=lang)

    def _active_players(self, game_id: str) -> list[Player]:
        return [p for p in self._repo.players(game_id) if p.active]

    def _identity_of(self, player_id: str, game_id: str) -> str | None:
        evs = self._events.view_for(game_id, KP, types=["identity_assigned"])
        mine = [e for e in evs if e.payload.get("player") == player_id]
        return str(mine[-1].payload["identity"]) if mine else None

    def assign_identity(self, player_id: str, choice: str | None = None) -> Event:
        """按剧本抽取或选择身份。抽取由引擎掷骰，记入日志；已被占用的身份不再出现。"""
        with self._lock:
            p = self.player(player_id)
            g = self.game(p.game_id)
            if g.status != "characters":
                raise IllegalState("game.not_in_character_phase")
            if self._identity_of(player_id, g.id) is not None:
                raise IllegalState("identity.already_assigned")
            rules = self.identity_rules(g.id)
            if not rules.options:
                raise IllegalState("identity.none_defined")
            taken = {
                str(e.payload["identity"])
                for e in self._events.view_for(g.id, KP, types=["identity_assigned"])
            }
            free = [o for o in rules.options if o.id not in taken]
            if not free:
                raise IllegalState("identity.exhausted")
            new: list[NewEvent] = []
            if rules.mode == "choose":
                if choice is None:
                    raise ValidationFailed("identity.choice_required")
                picked = next((o for o in free if o.id == choice), None)
                if picked is None:
                    raise ValidationFailed("identity.unavailable", choice=choice)
            else:
                if choice is not None:
                    raise ValidationFailed("identity.draw_only")
                roll = self._dice.roll(f"1d{len(free)}")
                picked = free[roll.total - 1]
                new.append(
                    self._dice_event(roll, reason="identity_draw", extra={"player": player_id})
                )
            new.append(
                NewEvent(
                    type="identity_assigned",
                    actor=ENGINE,
                    visibility=Visibility.to(player_id),
                    payload={
                        "player": player_id,
                        "identity": picked.id,
                        "name": picked.name,
                        "description": picked.description,
                    },
                )
            )
            return self._events.append(g.id, 0, new)[-1]

    def character_status(self, player_id: str) -> str:
        """none / submitted / approved / rejected"""
        p = self.player(player_id)
        evs = self._events.view_for(
            p.game_id,
            player_id,
            types=["character_submitted", "character_approved", "character_rejected"],
        )
        if not evs:
            return "none"
        return {
            "character_submitted": "submitted",
            "character_approved": "approved",
            "character_rejected": "rejected",
        }[evs[-1].type]

    def submitted_character(self, player_id: str) -> list[SheetSubmission]:
        p = self.player(player_id)
        evs = self._events.view_for(p.game_id, player_id, types=["character_submitted"])
        if not evs:
            raise NotFound("character.not_submitted")
        raw = evs[-1].payload.get("sheets")
        assert isinstance(raw, list)
        return [SheetSubmission.model_validate(x) for x in raw]

    def submit_character(self, player_id: str, sheets: Sequence[SheetSubmission]) -> Event:
        with self._lock:
            p = self.player(player_id)
            g = self.game(p.game_id)
            if g.status != "characters":
                raise IllegalState("game.not_in_character_phase")
            if self.character_status(player_id) == "approved":
                raise IllegalState("character.already_approved")
            if self.identity_rules(g.id).options and self._identity_of(player_id, g.id) is None:
                raise IllegalState("identity.required_first")
            pack = self.rulepack(g.id)
            problems: list[Problem] = []
            counts: dict[str, int] = {}
            for s in sheets:
                counts[s.template] = counts.get(s.template, 0) + 1
            allowed = {pe.template for pe in pack.player_entities}
            for t in counts:
                if t not in allowed:
                    problems.append(
                        Problem(code="character.template_not_allowed", params={"template": t})
                    )
            for pe in pack.player_entities:
                n = counts.get(pe.template, 0)
                if not pe.min <= n <= pe.max:
                    problems.append(
                        Problem(
                            code="character.count",
                            params={
                                "template": pe.template,
                                "count": n,
                                "min": pe.min,
                                "max": pe.max,
                            },
                        )
                    )
            filled: list[JsonValue] = []
            for i, s in enumerate(sheets):
                raw = s.sheet.model_dump(mode="json")
                try:
                    init = self._rules.init_sheet(pack, s.template, raw)
                except ValidationFailed as e:
                    problems.append(Problem(code=e.code, path=f"sheets[{i}]", params=e.params))
                    continue
                for prob in self._rules.validate_sheet(pack, s.template, init):
                    problems.append(prob.model_copy(update={"path": f"sheets[{i}].{prob.path}"}))
                filled.append({"template": s.template, "sheet": init})
            if problems:
                raise ValidationFailed("character.invalid", problems)
            ev = NewEvent(
                type="character_submitted",
                actor=player_id,
                visibility=Visibility.to(player_id),
                payload={"sheets": filled},
            )
            return self._events.append(g.id, 0, [ev])[0]

    def reject_character(self, player_id: str, comments: str) -> Event:
        with self._lock:
            p = self.player(player_id)
            if self.character_status(player_id) != "submitted":
                raise IllegalState("character.not_pending")
            ev = NewEvent(
                type="character_rejected",
                actor=KP,
                visibility=Visibility.to(player_id),
                payload={"comments": _text(comments, "comments")},
            )
            return self._events.append(p.game_id, 0, [ev])[0]

    def approve_character(self, player_id: str, comments: str = "") -> Event:
        """审核通过后实体进入世界状态（还没有位置，开场时确定）。"""
        with self._lock:
            p = self.player(player_id)
            g = self.game(p.game_id)
            if self.character_status(player_id) != "submitted":
                raise IllegalState("character.not_pending")
            subs = self.submitted_character(player_id)
            state = self._state(g.id)
            ids = self._new_entity_ids(state, len(subs))
            ops: list[PatchOp] = []
            for eid, s in zip(ids, subs, strict=True):
                ops.append(
                    PatchOp(
                        op="add",
                        path=f"/entities/{eid}",
                        value={
                            "template": s.template,
                            "pos": None,
                            "inside": None,
                            "sheet": s.sheet.model_dump(mode="json"),
                        },
                    )
                )
            ops.append(PatchOp(op="add", path=f"/controls/{player_id}", value=list(ids)))
            self._validated(g.id, state, ops)
            evs = [
                self._patch_event(ops, cause="character_approved", actor=ENGINE),
                NewEvent(
                    type="character_approved",
                    actor=KP,
                    visibility=Visibility.to(player_id),
                    payload={"entities": list(ids), "comments": comments},
                ),
            ]
            return self._events.append(g.id, 0, evs)[-1]

    def _new_entity_ids(self, state: State, n: int, prefix: str = "ent") -> list[str]:
        used = set(_obj(state.get("entities")))
        out: list[str] = []
        i = 1
        while len(out) < n:
            cand = f"{prefix}_{i}"
            if cand not in used:
                out.append(cand)
                used.add(cand)
            i += 1
        return out

    def start_game(self, game_id: str, opening: Opening) -> Round:
        """开场：KP 广播起始剧情，私发开场信息，确定初始位置；开启第 1 轮。"""
        with self._lock:
            g = self.game(game_id)
            if g.status != "characters":
                raise IllegalState("game.not_in_character_phase")
            players = self._active_players(game_id)
            if not players:
                raise IllegalState("game.no_players")
            pending = [p.id for p in players if self.character_status(p.id) != "approved"]
            if pending:
                raise IllegalState("game.characters_pending", players=list(pending))
            missing = [p.id for p in players if p.id not in opening.messages]
            if missing:
                raise ValidationFailed("opening.missing_message", players=list(missing))
            meta = scenario.kp_meta(g.scenario_kp)
            pack = self.rulepack(game_id)
            state = self._state(game_id)
            ops: list[PatchOp] = []
            for npc in meta.npcs:
                if npc.id in _obj(state.get("entities")):
                    raise ValidationFailed("opening.npc_id_taken", id=npc.id)
                sheet = self._rules.init_sheet(pack, npc.template, npc.sheet)
                loc = npc.location
                ops.append(
                    PatchOp(
                        op="add",
                        path=f"/entities/{npc.id}",
                        value={
                            "template": npc.template,
                            "pos": loc.pos.model_dump() if loc else None,
                            "inside": loc.inside if loc else None,
                            "sheet": sheet,
                        },
                    )
                )
            positions = self._initial_positions(game_id, state, meta, opening)
            for eid, loc in sorted(positions.items()):
                ops.append(
                    PatchOp(op="replace", path=f"/entities/{eid}/pos", value=loc.pos.model_dump())
                )
                ops.append(PatchOp(op="replace", path=f"/entities/{eid}/inside", value=loc.inside))
            self._validated(game_id, state, ops)
            evs: list[NewEvent] = (
                [self._patch_event(ops, cause="opening", actor=ENGINE)] if ops else []
            )
            evs.append(
                NewEvent(
                    type="broadcast",
                    actor=KP,
                    visibility=Visibility.public(),
                    payload={"text": _text(opening.broadcast), "anonymous": False},
                )
            )
            for p in players:
                evs.append(
                    NewEvent(
                        type="pm_kp",
                        actor=KP,
                        visibility=Visibility.to(p.id),
                        payload={
                            "text": _text(opening.messages[p.id]),
                            "from": "kp",
                            "kind": "opening",
                        },
                    )
                )
            evs.append(
                NewEvent(
                    type="round_opened",
                    actor=ENGINE,
                    visibility=Visibility.public(),
                    payload={"round": 1, "game_minutes": 0},
                )
            )
            self._events.append(game_id, 0, evs)
            self._repo.insert_round(
                Round(game_id=game_id, no=1, status="collecting", started_minute=0)
            )
            self._repo.update_game(game_id, status="running", current_round=1)
            return self.round(game_id)

    def _initial_positions(
        self, game_id: str, state: State, meta: scenario.KpMeta, opening: Opening
    ) -> dict[str, Location]:
        """剧本指定的初始位置优先（按身份 id 或玩家显示名），其余用 KP 在开场时给出的。"""
        controls = _obj(state.get("controls"))
        out: dict[str, Location] = {}
        for p in self._active_players(game_id):
            keys = [k for k in (self._identity_of(p.id, game_id), p.display_name) if k]
            loc = next(
                (meta.initial_positions[k] for k in keys if k in meta.initial_positions), None
            )
            ents = controls.get(p.id)
            if loc is not None and isinstance(ents, list):
                for e in ents:
                    out[str(e)] = loc
        entities = _obj(state.get("entities"))
        for eid, loc in opening.positions.items():
            if eid not in entities:
                raise ValidationFailed("opening.unknown_entity", id=eid)
            out.setdefault(eid, loc)
        return out

    # ================= 行动期 =================

    def post_broadcast(self, game_id: str, actor: str, text: str, anonymous: bool = False) -> Event:
        g = self.game(game_id)
        if actor != KP:
            p = self.player(actor)
            if p.game_id != game_id or not p.active:
                raise Forbidden("player.not_in_game")
        if g.status == "ended" and actor != KP:
            raise IllegalState("game.ended")
        ev = NewEvent(
            type="broadcast",
            actor=actor,
            visibility=Visibility.public(),
            payload={"text": _text(text), "anonymous": bool(anonymous and actor != KP)},
        )
        return self._events.append(game_id, g.current_round, [ev])[0]

    def post_kp_chat(self, player_id: str, text: str, from_kp: bool = False) -> Event:
        """聊天框：写 pm_kp。它不是行动，不影响回合结算。"""
        p = self.player(player_id)
        g = self.game(p.game_id)
        ev = NewEvent(
            type="pm_kp",
            actor=KP if from_kp else player_id,
            visibility=Visibility.to(player_id),
            payload={"text": _text(text), "from": "kp" if from_kp else "player", "kind": "chat"},
        )
        return self._events.append(g.id, g.current_round, [ev])[0]

    def controlled(self, game_id: str, player_id: str) -> list[str]:
        ents = _obj(self._state(game_id).get("controls")).get(player_id)
        return [str(e) for e in ents] if isinstance(ents, list) else []

    def declare_action(self, player_id: str, text: str, intent: Intent) -> Event:
        """行动框：玩家已确认的行动声明。结算开始前可以重新提交来覆盖。"""
        with self._lock:
            p = self.player(player_id)
            g = self.game(p.game_id)
            if g.status != "running":
                raise IllegalState("game.not_running")
            r = self.round(g.id)
            self._rounds.transition(r.status, "declare")
            if intent.unresolved:
                raise ValidationFailed("action.unresolved_reference", refs=list(intent.unresolved))
            if not intent.items:
                raise ValidationFailed("action.empty")
            mine = set(self.controlled(g.id, player_id))
            entities = set(_obj(self._state(g.id).get("entities")))
            problems: list[Problem] = []
            for i, item in enumerate(intent.items):
                if item.actor not in mine:
                    problems.append(
                        Problem(
                            code="action.actor_not_controlled",
                            path=f"items[{i}]",
                            params={"actor": item.actor},
                        )
                    )
                for t in item.targets:
                    if t.kind == "entity" and t.id not in entities:
                        problems.append(
                            Problem(
                                code="action.unknown_target",
                                path=f"items[{i}]",
                                params={"id": t.id},
                            )
                        )
            visible = {e.seq for e in self._events.view_for(g.id, player_id)}
            for q in intent.quotes:
                if q not in visible:
                    problems.append(Problem(code="action.quote_not_visible", params={"seq": q}))
            if problems:
                raise ValidationFailed("action.invalid", problems)
            items = [
                it.model_copy(update={"id": f"act_{r.no}_{player_id}_{i + 1}"})
                for i, it in enumerate(intent.items)
            ]
            stored = intent.model_copy(update={"items": tuple(items)})
            ev = NewEvent(
                type="action_declared",
                actor=player_id,
                visibility=Visibility.to(player_id),
                payload={
                    "text": _text(text),
                    "intent": stored.model_dump(mode="json", by_alias=True),
                },
            )
            return self._events.append(g.id, r.no, [ev])[0]

    def declarations(self, game_id: str, round_no: int | None = None) -> dict[str, Event]:
        """本轮每个玩家最新的一份已确认行动声明。"""
        n = round_no if round_no is not None else self.game(game_id).current_round
        out: dict[str, Event] = {}
        for e in self._events.view_for(game_id, KP, types=["action_declared"], round_no=n):
            if e.actor is not None:
                out[e.actor] = e
        return out

    def required_players(self, game_id: str) -> list[str]:
        """需要提交行动的玩家：有效且控制着至少一个实体。"""
        return [p.id for p in self._active_players(game_id) if self.controlled(game_id, p.id)]

    def submitted_count(self, game_id: str) -> tuple[int, int]:
        req = self.required_players(game_id)
        decl = self.declarations(game_id)
        return sum(1 for p in req if p in decl), len(req)

    def ready_to_close(self, game_id: str) -> bool:
        g = self.game(game_id)
        if g.status != "running" or self.round(game_id).status != "collecting":
            return False
        done, total = self.submitted_count(game_id)
        return total > 0 and done == total

    def rename_handle(
        self, player_id: str, entity_id: str, label: str | None = None, note: str | None = None
    ) -> None:
        raise NotImplementedError("handles arrive in M2")

    # ================= 结算 =================

    def close_round(self, game_id: str, forced: bool = False) -> Round:
        with self._lock:
            r = self.round(game_id)
            nxt = self._rounds.transition(r.status, "close")
            if not forced and not self.ready_to_close(game_id):
                raise IllegalState("round.not_ready")
            submitted = sorted(self.declarations(game_id))
            self._repo.update_round(game_id, r.no, status=nxt, forced=forced, submitted=submitted)
            return self.round(game_id)

    def _require(self, game_id: str, action: str) -> Round:
        r = self.round(game_id)
        self._rounds.transition(r.status, action)
        return r

    def _dice_event(
        self, roll: DiceResult, reason: str, extra: dict[str, JsonValue] | None = None
    ) -> NewEvent:
        return NewEvent(
            type="dice_roll",
            actor=ENGINE,
            visibility=Visibility.kp_only(),
            payload={
                "expr": roll.expr,
                "rolls": list(roll.rolls),
                "total": roll.total,
                "reason": reason,
                **(extra or {}),
            },
        )

    def roll(self, game_id: str, expr: str, reason: str) -> DiceResult:
        with self._lock:
            r = self._require(game_id, "roll")
            probs = self._dice.validate(expr)
            if probs:
                raise ValidationFailed("dice.invalid", probs)
            res = self._dice.roll(expr)
            ev = self._events.append(game_id, r.no, [self._dice_event(res, reason)])[0]
            return res.model_copy(update={"seq": ev.seq})

    def _entity(self, state: State, entity_id: str) -> dict[str, JsonValue]:
        ent = _obj(state.get("entities")).get(entity_id)
        if not isinstance(ent, dict):
            raise NotFound("entity.not_found", id=entity_id)
        return cast(dict[str, JsonValue], ent)

    def run_check(
        self,
        game_id: str,
        entity_id: str,
        check: str,
        against: float | str | None = None,
        reason: str = "",
    ) -> CheckResult:
        """命名检定。against 为难度（数）或对抗对象（实体 id）。引擎掷骰并按成功条件算结果等级。"""
        with self._lock:
            r = self._require(game_id, "roll")
            pack = self.rulepack(game_id)
            state = self._state(game_id)
            ent = self._entity(state, entity_id)
            roll = self._dice.roll(self._rules.check_dice(pack, check))
            opponent = None
            opp_roll = None
            if isinstance(against, str):
                opp = self._entity(state, against)
                cdef = pack.check(check)
                assert cdef is not None
                opp_roll = self._dice.roll(self._rules.check_dice(pack, cdef.opposed_by or check))
                opponent = (against, str(opp["template"]), opp["sheet"], opp_roll)
            res = self._rules.resolve_check(
                pack,
                entity=entity_id,
                template=str(ent["template"]),
                sheet=ent["sheet"],
                check=check,
                roll=roll,
                difficulty=float(against) if isinstance(against, int | float) else None,
                opponent=opponent,
            )
            payload: dict[str, JsonValue] = {
                "expr": roll.expr,
                "rolls": list(roll.rolls),
                "total": roll.total,
                "reason": reason or "check",
                "check": check,
                "entity": entity_id,
                "level": res.level,
                "target": res.target,
                "difficulty": res.difficulty,
                "opponent": res.opponent,
                "opp_total": opp_roll.total if opp_roll else None,
                "opp_rolls": list(opp_roll.rolls) if opp_roll else None,
            }
            ev = self._events.append(
                game_id,
                r.no,
                [
                    NewEvent(
                        type="dice_roll",
                        actor=ENGINE,
                        visibility=Visibility.kp_only(),
                        payload=payload,
                    )
                ],
            )[0]
            return res.model_copy(update={"roll": roll.model_copy(update={"seq": ev.seq})})

    def run_adhoc_check(
        self, game_id: str, entity_id: str, spec: AdHocCheck, reason: str = ""
    ) -> CheckResult:
        with self._lock:
            r = self._require(game_id, "roll")
            self._entity(self._state(game_id), entity_id)
            probs = self._dice.validate(spec.dice)
            if probs:
                raise ValidationFailed("dice.invalid", probs)
            roll = self._dice.roll(spec.dice)
            res = self._rules.resolve_adhoc(entity_id, spec, roll)
            payload: dict[str, JsonValue] = {
                "expr": roll.expr,
                "rolls": list(roll.rolls),
                "total": roll.total,
                "reason": reason or "adhoc",
                "check": "adhoc",
                "entity": entity_id,
                "level": res.level,
                "target": spec.target,
                "success_when": spec.success_when,
            }
            ev = self._events.append(
                game_id,
                r.no,
                [
                    NewEvent(
                        type="dice_roll",
                        actor=ENGINE,
                        visibility=Visibility.kp_only(),
                        payload=payload,
                    )
                ],
            )[0]
            return res.model_copy(update={"roll": roll.model_copy(update={"seq": ev.seq})})

    def _items(self, game_id: str, round_no: int) -> dict[str, adjv.ItemInfo]:
        out: dict[str, adjv.ItemInfo] = {}
        for pid, ev in self.declarations(game_id, round_no).items():
            intent = Intent.model_validate(ev.payload["intent"])
            for it in intent.items:
                assert it.id is not None
                targets = frozenset(t.id for t in it.targets if t.kind == "entity" and t.id)
                out[it.id] = adjv.ItemInfo(player=pid, actor=it.actor, targets=targets)
        return out

    def plan_adjudication(
        self, game_id: str, adj: Adjudication
    ) -> tuple[list[tuple[str, list[PatchOp]]], State]:
        """校验裁定并算出发布时要写入的各组 patch 和结果状态。不写入任何东西。"""
        g = self.game(game_id)
        r = self.round(game_id)
        pack = self.rulepack(game_id)
        state = self._state(game_id)
        entities = set(_obj(state.get("entities")))
        controls = {
            pid: set(map(str, v))
            for pid, v in _obj(state.get("controls")).items()
            if isinstance(v, list)
        }
        required = self.required_players(game_id)
        items = self._items(game_id, r.no)
        if r.forced:
            # 强制结算：没提交的玩家本轮视为没有行动
            items = {k: v for k, v in items.items() if v.player in r.submitted}
        problems = adjv.check_sources(
            adj, required=required, items=items, controls=controls, entities=entities
        )
        problems += adjv.check_patch_paths(adj.state_patch, entities)
        groups: list[tuple[str, list[PatchOp]]] = []
        cur = state
        if not problems and adj.state_patch:
            try:
                cur = self._world.apply(cur, adj.state_patch)
                groups.append(("adjudication", list(adj.state_patch)))
            except ValidationFailed as e:
                problems += e.problems
        after_entities = set(_obj(cur.get("entities")))
        problems += adjv.check_memory_entities(adj, after_entities | entities)
        mv_ops: list[PatchOp] = []
        for i, mv in enumerate(adj.movements):
            if mv.entity not in after_entities:
                problems.append(
                    Problem(
                        code="adj.unknown_entity", path=f"movements[{i}]", params={"id": mv.entity}
                    )
                )
                continue
            mv_ops.append(
                PatchOp(op="replace", path=f"/entities/{mv.entity}/pos", value=mv.to.model_dump())
            )
            mv_ops.append(
                PatchOp(op="replace", path=f"/entities/{mv.entity}/inside", value=mv.inside)
            )
        if problems:
            raise ValidationFailed("adjudication.invalid", problems)
        if mv_ops:
            cur = self._world.apply(cur, mv_ops)
            groups.append(("movement", mv_ops))
        if adj.kp_notes is not None:
            ops = [PatchOp(op="replace", path="/kp_notes", value=adj.kp_notes)]
            cur = self._world.apply(cur, ops)
            groups.append(("kp_notes", ops))
        minutes = int(cast(int, cur["game_minutes"])) + adj.time_advance_minutes
        ops = [PatchOp(op="replace", path="/game_minutes", value=minutes)]
        cur = self._world.apply(cur, ops)
        groups.append(("time", ops))
        expire = self._world.expire(cur, minutes)
        if expire:
            cur = self._world.apply(cur, expire)
            groups.append(("expiry", expire))
        problems = self._world.validate(cur, pack)
        if problems:
            raise ValidationFailed("adjudication.invalid_state", problems)
        del g
        return groups, cur

    def apply_adjudication(self, game_id: str, adj: Adjudication) -> Round:
        """校验裁定，通过后存为本轮草稿，回合进入待审核。校验失败时什么都不写。

        事件在 publish_round 时才写入，所以重跑和人工修改只需替换草稿。
        """
        with self._lock:
            r = self.round(game_id)
            nxt = self._rounds.transition(r.status, "to_review")
            self.plan_adjudication(game_id, adj)
            draft: dict[str, JsonValue] = {
                "adjudication": adj.model_dump(mode="json", by_alias=True),
                "feedback": {},
                "broadcast": None,
                "error": None,
            }
            self._repo.update_round(game_id, r.no, status=nxt, draft=draft)
            return self.round(game_id)

    def fail_round(self, game_id: str, error: JsonValue) -> Round:
        """裁定重试用尽：回合停在待审核，没有草稿，等管理员处理。"""
        with self._lock:
            r = self.round(game_id)
            nxt = self._rounds.transition(r.status, "to_review")
            self._repo.update_round(
                game_id,
                r.no,
                status=nxt,
                draft={"adjudication": None, "feedback": {}, "broadcast": None, "error": error},
            )
            return self.round(game_id)

    def _draft(self, game_id: str) -> tuple[Round, dict[str, JsonValue]]:
        r = self.round(game_id)
        if r.status != "review" or r.draft is None:
            raise IllegalState("round.no_draft")
        return r, copy.deepcopy(r.draft)

    def set_feedback_draft(self, game_id: str, player_id: str, text: str) -> None:
        with self._lock:
            r, d = self._draft(game_id)
            self._rounds.transition(r.status, "edit")
            fb = _obj(d.get("feedback"))
            fb[player_id] = _text(text)
            d["feedback"] = fb
            self._repo.update_round(game_id, r.no, draft=d)

    def set_broadcast_draft(self, game_id: str, text: str | None) -> None:
        with self._lock:
            r, d = self._draft(game_id)
            d["broadcast"] = _text(text) if text is not None else None
            self._repo.update_round(game_id, r.no, draft=d)

    def edit_adjudication(self, game_id: str, adj: Adjudication) -> None:
        """管理员在审核面板修改裁定；同样要通过全部校验。"""
        with self._lock:
            r, d = self._draft(game_id)
            self._rounds.transition(r.status, "edit")
            self.plan_adjudication(game_id, adj)
            d["adjudication"] = adj.model_dump(mode="json", by_alias=True)
            d["error"] = None
            self._repo.update_round(game_id, r.no, draft=d)

    def rerun_round(self, game_id: str) -> Round:
        with self._lock:
            r = self.round(game_id)
            nxt = self._rounds.transition(r.status, "rerun")
            if r.draft is not None:
                self._repo.discard_draft(game_id, r.no, r.draft)
            self._repo.update_round(game_id, r.no, status=nxt)
            return self.round(game_id)

    def recover(self) -> list[str]:
        """进程启动时调用：停在“裁定中”的回合需要重跑，返回这些局的 id。"""
        out: list[str] = []
        for r in self._repo.rounds_in("adjudicating"):
            self._rounds.transition(r.status, "restart")
            out.append(r.game_id)
        return sorted(set(out))

    def draft(self, game_id: str) -> dict[str, JsonValue] | None:
        return self.round(game_id).draft

    def publish_round(self, game_id: str) -> Round:
        """发布：写入裁定、状态变更、反馈与广播，开启下一轮（或结束这一局）。"""
        with self._lock:
            r, d = self._draft(game_id)
            self._rounds.transition(r.status, "publish")
            raw = d.get("adjudication")
            if raw is None:
                raise IllegalState("round.no_adjudication")
            adj = Adjudication.model_validate(raw)
            groups, final = self.plan_adjudication(game_id, adj)
            feedback = _obj(d.get("feedback"))
            missing = [
                o.player_id for o in adj.outcomes if not isinstance(feedback.get(o.player_id), str)
            ]
            if missing:
                raise IllegalState("round.feedback_missing", players=list(missing))
            bc = d.get("broadcast")
            if adj.public_events and not isinstance(bc, str):
                raise IllegalState("round.broadcast_missing")
            evs: list[NewEvent] = [
                NewEvent(
                    type="adjudication",
                    actor=KP,
                    visibility=Visibility.kp_only(),
                    payload={"adjudication": raw},
                )
            ]
            evs += [
                self._patch_event(
                    ops, cause=cause, actor=KP if cause != "expiry" and cause != "time" else ENGINE
                )
                for cause, ops in groups
            ]
            for o in adj.outcomes:
                evs.append(
                    NewEvent(
                        type="feedback",
                        actor=KP,
                        visibility=Visibility.to(o.player_id),
                        payload={"text": feedback[o.player_id], "round": r.no},
                    )
                )
            if isinstance(bc, str):
                evs.append(
                    NewEvent(
                        type="broadcast",
                        actor=KP,
                        visibility=Visibility.public(),
                        payload={"text": bc, "anonymous": False, "round": r.no},
                    )
                )
            minutes = int(cast(int, final["game_minutes"]))
            evs.append(
                NewEvent(
                    type="round_closed",
                    actor=ENGINE,
                    visibility=Visibility.public(),
                    payload={"round": r.no, "game_minutes": minutes, "game_over": adj.game_over},
                )
            )
            if not adj.game_over:
                evs.append(
                    NewEvent(
                        type="round_opened",
                        actor=ENGINE,
                        visibility=Visibility.public(),
                        payload={"round": r.no + 1, "game_minutes": minutes},
                    )
                )
            written = self._events.append(game_id, r.no, evs)
            self._repo.update_round(
                game_id, r.no, status="published", ended_minute=minutes, snapshot=final
            )
            if adj.game_over:
                self._repo.update_game(game_id, status="ended")
            else:
                self._repo.insert_round(
                    Round(game_id=game_id, no=r.no + 1, status="collecting", started_minute=minutes)
                )
                self._repo.update_game(game_id, current_round=r.no + 1)
            del written
            return self._repo.get_round(game_id, r.no)

    def end_game(self, game_id: str) -> Game:
        self._repo.update_game(game_id, status="ended")
        return self.game(game_id)

    def admin_patch(self, game_id: str, ops: Sequence[PatchOp], note: str = "") -> State:
        """管理员在控制台手动修改世界状态。"""
        with self._lock:
            g = self.game(game_id)
            state = self._state(game_id)
            new = self._validated(game_id, state, ops)
            self._events.append(
                game_id,
                g.current_round,
                [
                    NewEvent(
                        type="admin_override",
                        actor=ADMIN,
                        visibility=Visibility.kp_only(),
                        payload={
                            "ops": [o.model_dump(mode="json", by_alias=True) for o in ops],
                            "note": note,
                        },
                    ),
                    self._patch_event(list(ops), cause="admin", actor=ADMIN),
                ],
            )
            return new

    # ================= 读取 =================

    def view_for(self, game_id: str, audience: Audience, since_seq: int = 0) -> list[Event]:
        return self._events.view_for(game_id, audience, since_seq)

    def world_state(self, game_id: str, at_round: int | None = None) -> State:
        """仅供 KP 与控制台。"""
        if at_round is None:
            return copy.deepcopy(self._state(game_id))
        snap = self._repo.get_round(game_id, at_round).snapshot
        if snap is None:
            raise NotFound("round.no_snapshot", no=at_round)
        return snap

    def rebuild_state(self, game_id: str, upto_seq: int | None = None) -> State:
        """从空状态按顺序折叠全部 state_patch 事件。用于重放校验。"""
        g = self.game(game_id)
        state = self._world.initial_state(g.map_id)
        for e in self._events.view_for(game_id, KP, types=["state_patch"]):
            if upto_seq is not None and e.seq > upto_seq:
                break
            state = self._world.apply(state, self._ops(e))
        return state

    def canonical(self, state: State) -> str:
        return self._world.canonical(state)

    def sheets(self, game_id: str, player_id: str) -> list[SheetView]:
        pack = self.rulepack(game_id)
        g = self.game(game_id)
        patches = self._events.view_for(game_id, KP, types=["state_patch"])
        feedback = {
            e.round_no: e.seq for e in self._events.view_for(game_id, player_id, types=["feedback"])
        }
        return build_sheet_views(
            world=self._world,
            rules=self._rules,
            pack=pack,
            initial=self._world.initial_state(g.map_id),
            patches=[(e.round_no, str(e.payload.get("cause", "")), self._ops(e)) for e in patches],
            feedback_seq=feedback,
            player_id=player_id,
        )

    # ================= 内部 =================

    @staticmethod
    def _ops(e: Event) -> list[PatchOp]:
        raw = e.payload.get("ops")
        assert isinstance(raw, list)
        return [PatchOp.model_validate(x) for x in raw]

    def _patch_event(self, ops: Sequence[PatchOp], *, cause: str, actor: str) -> NewEvent:
        return NewEvent(
            type="state_patch",
            actor=actor,
            visibility=Visibility.kp_only(),
            payload={
                "cause": cause,
                "ops": [o.model_dump(mode="json", by_alias=True, exclude_none=False) for o in ops],
            },
        )

    def _validated(self, game_id: str, state: State, ops: Sequence[PatchOp]) -> State:
        new = self._world.apply(state, ops)
        problems = self._world.validate(new, self.rulepack(game_id))
        if problems:
            raise ValidationFailed("state.invalid", problems)
        return new

    def _state(self, game_id: str) -> State:
        """当前世界状态：缓存加上缓存之后的 state_patch 事件。"""
        with self._lock:
            cached = self._state_cache.get(game_id)
            if cached is None:
                g = self.game(game_id)
                seq, state = 0, self._world.initial_state(g.map_id)
            else:
                seq, state = cached
            new = self._events.view_for(game_id, KP, since_seq=seq, types=["state_patch"])
            for e in new:
                state = self._world.apply(state, self._ops(e))
                seq = e.seq
            self._state_cache[game_id] = (seq, state)
            return state
