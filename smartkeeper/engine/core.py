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
    Handle,
    HandleStore,
    IdentityRules,
    IllegalState,
    Intent,
    Location,
    MapChange,
    MapData,
    MapStore,
    MemoryEntry,
    MemoryStore,
    NewEvent,
    NotFound,
    Opening,
    OwnEntity,
    PatchOp,
    Place,
    Player,
    Point,
    PresenceEntry,
    Problem,
    QueryResult,
    Round,
    RoundMachine,
    RulePack,
    RulePackStore,
    Rules,
    Scene,
    SeenEntry,
    SheetSubmission,
    SheetView,
    Spatial,
    SpatialQuery,
    SpatialQueryResult,
    State,
    SweepShape,
    TargetRef,
    ValidationFailed,
    Visibility,
    World,
)
from smartkeeper.engine import adjudication as adjv
from smartkeeper.engine import scenario
from smartkeeper.engine.mentions import find_mentions, replace_mentions
from smartkeeper.engine.repo import Repo
from smartkeeper.engine.sheetview import build_sheet_views, visible_sheet
from smartkeeper.engine.space import EMPTY_MAP, Space, point_of

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
        maps: MapStore,
        spatial: Spatial,
        handles: HandleStore,
        memory: MemoryStore,
    ) -> None:
        self._repo = Repo(db)
        self._maps = maps
        self._spatial = spatial
        self._handles = handles
        self._memory = memory
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
                face = self._dice.faces(1, len(free))
                roll = DiceResult(expr=f"1d{len(free)}", rolls=face, total=face[0])
                picked = free[face[0] - 1]
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
                loc = self.resolve_place(game_id, npc.location) if npc.location else None
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
            m = self._map(game_id)
            problems: list[Problem] = []
            npc_locs = {
                n.id: self.resolve_place(game_id, n.location)
                for n in meta.npcs
                if n.location is not None
            }
            for eid, loc in sorted({**npc_locs, **positions}.items()):
                problems += self._check_location(m, eid, loc, f"positions.{eid}")
            if problems:
                raise ValidationFailed("opening.invalid_positions", problems)
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
            self.refresh_handles(game_id)
            return self.round(game_id)

    def _initial_positions(
        self, game_id: str, state: State, meta: scenario.KpMeta, opening: Opening
    ) -> dict[str, Location]:
        """剧本指定的初始位置优先（按身份 id 或玩家显示名），其余用 KP 在开场时给出的。"""
        controls = _obj(state.get("controls"))
        out: dict[str, Location] = {}
        for p in self._active_players(game_id):
            keys = [k for k in (self._identity_of(p.id, game_id), p.display_name) if k]
            spec = next(
                (meta.initial_positions[k] for k in keys if k in meta.initial_positions), None
            )
            loc = self.resolve_place(game_id, spec) if spec is not None else None
            ents = controls.get(p.id)
            if loc is not None and isinstance(ents, list):
                for e in ents:
                    out[str(e)] = loc
        entities = set(_obj(state.get("entities"))) | {n.id for n in meta.npcs}
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
            # 玩家只能指代自己的实体和他有代号的实体（感知过的），不能凭实体 ID 猜
            entities = mine | {h.entity_id for h in self._handles.list(player_id)}
            m = self._map(g.id)
            problems: list[Problem] = []
            for i, item in enumerate(intent.items):
                for t in item.targets:
                    if t.kind == "feature" and (t.id is None or m.feature(t.id) is None):
                        problems.append(
                            Problem(
                                code="action.unknown_feature",
                                path=f"items[{i}]",
                                params={"id": t.id},
                            )
                        )
                if item.destination is not None:
                    problems += self._check_location(m, item.actor, item.destination, f"items[{i}]")
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
            res = self._rules.roll(self.rulepack(game_id), expr, self._dice.faces)
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
            faces = self._dice.faces
            roll = self._rules.roll(
                pack, self._rules.check_dice(pack, check), faces, str(ent["template"]), ent["sheet"]
            )
            opponent = None
            opp_roll = None
            if isinstance(against, str):
                opp = self._entity(state, against)
                cdef = pack.check(check)
                assert cdef is not None
                opp_expr = self._rules.check_dice(pack, cdef.opposed_by or check)
                opp_roll = self._rules.roll(
                    pack, opp_expr, faces, str(opp["template"]), opp["sheet"]
                )
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
            ent = self._entity(self._state(game_id), entity_id)
            roll = self._rules.roll(
                self.rulepack(game_id),
                spec.dice,
                self._dice.faces,
                str(ent["template"]),
                ent["sheet"],
            )
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
        r = self.round(game_id)
        pack = self.rulepack(game_id)
        m = self._map(game_id)
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
        for i, mem in enumerate(adj.memory_entries):
            for fid in mem.features:
                if m.feature(fid) is None:
                    problems.append(
                        Problem(
                            code="adj.memory_unknown_feature",
                            path=f"memory_entries[{i}]",
                            params={"id": fid},
                        )
                    )
        before = self._space_for(m, cur, pack)
        mv_ops: list[PatchOp] = []
        for i, mv in enumerate(adj.movements):
            path = f"movements[{i}]"
            if mv.entity not in after_entities:
                problems.append(
                    Problem(code="adj.unknown_entity", path=path, params={"id": mv.entity})
                )
                continue
            loc = Location(pos=mv.to, inside=mv.inside)
            problems += self._check_location(m, mv.entity, loc, path)
            problems += self._check_move_distance(
                before, mv.entity, mv.to, mv.ability, adj.time_advance_minutes, path
            )
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
        after = self._space_for(m, cur, pack)
        problems += self._check_encounters(adj, after)
        problems += self._check_area_effects(game_id, r.no, adj)
        if problems:
            raise ValidationFailed("adjudication.invalid", problems)
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
        problems = self._world.validate(cur, pack) + self._check_map_changes(m, cur)
        if problems:
            raise ValidationFailed("adjudication.invalid_state", problems)
        knowledge = self._map_knowledge_ops(self._space_for(m, cur, pack))
        if knowledge:
            cur = self._world.apply(cur, knowledge)
            groups.append(("map_knowledge", knowledge))
        return groups, cur

    # ---------------- 空间相关的校验 ----------------

    def _check_location(self, m: MapData, eid: str, loc: Location, path: str) -> list[Problem]:
        out: list[Problem] = []
        if not self._spatial.in_bounds(m, loc.pos):
            out.append(Problem(code="space.out_of_bounds", path=path, params={"entity": eid}))
        if loc.inside is not None:
            f = m.feature(loc.inside)
            if f is None or f.kind != "building":
                out.append(
                    Problem(code="space.unknown_building", path=path, params={"id": loc.inside})
                )
            elif not self._spatial.inside_feature(m, loc.inside, loc.pos):
                out.append(Problem(code="space.not_inside", path=path, params={"id": loc.inside}))
        return out

    def _check_move_distance(
        self, space: Space, eid: str, to: Point, ability: str | None, minutes: int, path: str
    ) -> list[Problem]:
        if ability is not None:
            # 依据能力的特殊移动：只校验这个能力确实在该实体的角色卡上
            sheet = space.full_sheet(eid)
            names: set[str] = set()
            for entries in _obj(sheet.get("groups")).values():
                if isinstance(entries, list):
                    names |= {str(_obj(e).get("name")) for e in entries}
            if ability not in names:
                return [
                    Problem(code="space.unknown_ability", path=path, params={"ability": ability})
                ]
            return []
        body = space.bodies.get(eid)
        if body is None:
            return []  # 还没有位置的实体（例如刚出现的）：第一次放置不算移动
        speed = space.derived(eid, "move_speed")
        dist = self._spatial.distance(body.pos, to)
        if dist > speed * minutes + 1e-6:
            return [
                Problem(
                    code="space.too_far",
                    path=path,
                    params={"distance": round(dist, 2), "max": round(speed * minutes, 2)},
                )
            ]
        return []

    def _check_encounters(self, adj: Adjudication, after: Space) -> list[Problem]:
        out: list[Problem] = []
        for i, enc in enumerate(adj.encounters):
            path = f"encounters[{i}]"
            for p in enc.observed_by:
                if p not in enc.players:
                    out.append(
                        Problem(code="adj.encounter_player", path=path, params={"player": p})
                    )
                    continue
                for q in enc.players:
                    if q != p and not after.player_sees_player(p, q):
                        out.append(
                            Problem(
                                code="adj.encounter_not_perceived",
                                path=path,
                                params={"observer": p, "target": q},
                            )
                        )
        return out

    def _check_area_effects(self, game_id: str, round_no: int, adj: Adjudication) -> list[Problem]:
        results = self._query_results(game_id, round_no)
        out: list[Problem] = []
        for i, ae in enumerate(adj.area_effects):
            path = f"area_effects[{i}]"
            res = results.get(ae.query_id)
            if res is None:
                out.append(
                    Problem(code="adj.unknown_query", path=path, params={"query": ae.query_id})
                )
                continue
            allowed = set(res.entities) | set(res.features)
            for a in ae.affected:
                if a not in allowed:
                    out.append(
                        Problem(
                            code="adj.not_in_query",
                            path=path,
                            params={"id": a, "query": ae.query_id},
                        )
                    )
        return out

    def _check_map_changes(self, m: MapData, state: State) -> list[Problem]:
        raw = state.get("map_changes")
        out: list[Problem] = []
        for i, c in enumerate(raw if isinstance(raw, list) else []):
            try:
                mc = MapChange.model_validate(c)
            except ValueError:
                out.append(Problem(code="state.bad_map_change", path=f"/map_changes/{i}"))
                continue
            if m.feature(mc.feature) is None:
                out.append(
                    Problem(
                        code="state.unknown_feature",
                        path=f"/map_changes/{i}",
                        params={"id": mc.feature},
                    )
                )
        return out

    def _map_knowledge_ops(self, space: Space) -> list[PatchOp]:
        """地图变化只在玩家的实体感知到它，或者它被公开之后，才对该玩家显示。知道了就一直知道。"""
        ops: list[PatchOp] = []
        for i, c in enumerate(space.changes):
            known = set(c.known_by)
            for pid in sorted(space.controls):
                if pid not in known and space.feature_known(pid, c.feature):
                    known.add(pid)
            if known != set(c.known_by):
                ops.append(
                    PatchOp(
                        op="add",
                        path=f"/map_changes/{i}/known_by",
                        value=list[JsonValue](sorted(known)),
                    )
                )
        return ops

    def _query_results(self, game_id: str, round_no: int) -> dict[str, QueryResult]:
        out: dict[str, QueryResult] = {}
        for e in self._events.view_for(game_id, KP, types=["spatial_query"], round_no=round_no):
            res = SpatialQueryResult.model_validate(e.payload["result"])
            out[res.query_id] = res.result or QueryResult(features=res.features)
        return out

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

    def set_feedback_leaks(self, game_id: str, player_id: str, leaks: Sequence[str]) -> None:
        """记下泄密检查命中的句子，供审核面板显示。"""
        with self._lock:
            r, d = self._draft(game_id)
            table = _obj(d.get("leaks"))
            if leaks:
                table[player_id] = list[JsonValue](leaks)
            else:
                table.pop(player_id, None)
            d["leaks"] = table
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
            adj_seq = written[0].seq
            self._memory.add(self._memory_entries(game_id, r.no, adj, adj_seq))
            self.refresh_handles(game_id)
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

    # ================= 位置、感知与代号 =================

    def map_data(self, game_id: str) -> MapData:
        return self._map(game_id)

    def _map(self, game_id: str) -> MapData:
        g = self.game(game_id)
        return self._maps.load(g.map_id) if g.map_id else EMPTY_MAP

    def _space_for(self, m: MapData, state: State, pack: RulePack) -> Space:
        return Space(spatial=self._spatial, m=m, state=state, pack=pack, rules=self._rules)

    def _space(self, game_id: str) -> Space:
        return self._space_for(self._map(game_id), self._state(game_id), self.rulepack(game_id))

    def _appearance(self, state: State, pack: RulePack, entity_id: str) -> str:
        ent = _obj(_obj(state.get("entities")).get(entity_id))
        tpl = pack.template(str(ent.get("template", "")))
        if tpl is None:
            return ""
        v = _obj(_obj(ent.get("sheet")).get("fields")).get(tpl.appearance_field)
        return v if isinstance(v, str) else ""

    def _entity_name(self, state: State, entity_id: str) -> str:
        sheet = _obj(_obj(_obj(state.get("entities")).get(entity_id)).get("sheet"))
        name = sheet.get("name")
        return name if isinstance(name, str) else entity_id

    def refresh_handles(self, game_id: str) -> list[tuple[str, str]]:
        """为每个玩家此刻感知到的实体确保有代号，自己的实体用角色名。返回还没命名的 (玩家, 实体)。"""
        with self._lock:
            space = self._space(game_id)
            state = space.state
            for pid, ents in space.controls.items():
                for e in ents:
                    h = self._handles.get(pid, e)
                    if h is None or h.auto:
                        self._handles.ensure(pid, e)
                        name = self._entity_name(state, e)
                        try:
                            self._handles.set_label(pid, e, name, by_player=True)
                        except ValidationFailed:
                            self._handles.set_label(pid, e, f"{name} ({e[-4:]})", by_player=True)
                for other in sorted(space.player_perceived(pid)):
                    self._handles.ensure(pid, other)
            return self.unnamed_handles(game_id)

    def unnamed_handles(self, game_id: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for p in self._active_players(game_id):
            mine = set(self.controlled(game_id, p.id))
            for h in self._handles.list(p.id):
                if h.auto and not h.named and h.entity_id not in mine:
                    out.append((p.id, h.entity_id))
        return out

    def handle_context(self, game_id: str, player_id: str, entity_id: str) -> tuple[str, list[str]]:
        """“外观代号”调用的上下文：对方的外观描述、该玩家已有的代号。"""
        state = self._state(game_id)
        appearance = self._appearance(state, self.rulepack(game_id), entity_id)
        labels = [h.label for h in self._handles.list(player_id) if h.entity_id != entity_id]
        return appearance, labels

    def set_handle_label(self, player_id: str, entity_id: str, label: str) -> Handle:
        """由“外观代号”调用命名。不覆盖玩家自己改过的名字。"""
        return self._handles.set_label(player_id, entity_id, label, by_player=False)

    def rename_handle(
        self, player_id: str, ref: str, label: str | None = None, note: str | None = None
    ) -> Handle:
        """玩家给代号改名或加私人备注，只影响自己的显示。"""
        h = self._handles.by_ref(player_id, ref)
        if h is None:
            raise NotFound("handle.not_found")
        if label is not None:
            h = self._handles.set_label(player_id, h.entity_id, label, by_player=True)
        if note is not None:
            h = self._handles.set_note(player_id, h.entity_id, note)
        return h

    def resolve_mentions(
        self, game_id: str, player_id: str, text: str
    ) -> tuple[str, list[TargetRef]]:
        """把行动文本里的 `@[文字](ref)` 换成该玩家的代号，并给出对应的实体 ID 或地物 id。

        ref 不属于这个玩家时拒绝：玩家只能 @ 引擎给出的代号。
        """
        m = self._map(game_id)
        labels: dict[str, str] = {}
        targets: list[TargetRef] = []
        for mt in find_mentions(text):
            if mt.is_point:
                pt = mt.point
                if pt is None or not self._spatial.in_bounds(m, pt):
                    raise ValidationFailed("mention.bad_point", ref=mt.ref)
                labels[mt.ref] = mt.text
                targets.append(TargetRef(kind="point", point=pt))
                continue
            if mt.is_feature:
                f = m.feature(mt.feature_id)
                if f is None:
                    raise ValidationFailed("mention.unknown", ref=mt.ref)
                labels[mt.ref] = f.name or f.id
                targets.append(TargetRef(kind="feature", id=f.id))
                continue
            h = self._handles.by_ref(player_id, mt.ref)
            if h is None:
                raise ValidationFailed("mention.unknown", ref=mt.ref)
            labels[mt.ref] = h.label
            targets.append(TargetRef(kind="entity", id=h.entity_id))
        return replace_mentions(text, labels), targets

    def entity_for_ref(self, player_id: str, ref: str) -> str:
        h = self._handles.by_ref(player_id, ref)
        if h is None:
            raise NotFound("handle.not_found")
        return h.entity_id

    def ref_for_entity(self, player_id: str, entity_id: str) -> str | None:
        h = self._handles.get(player_id, entity_id)
        return h.ref if h is not None else None

    def handles(self, player_id: str) -> list[Handle]:
        return self._handles.list(player_id)

    def scene(self, game_id: str, player_id: str) -> Scene:
        """我的各实体此刻的位置、各自的在场列表，以及我已知的地图变化。感知不到的实体不出现。"""
        space = self._space(game_id)
        state = space.state
        mine = space.controls.get(player_id, [])
        handles = {h.entity_id: h for h in self._handles.list(player_id)}
        own: list[OwnEntity] = []
        for e in mine:
            ent = _obj(space.entities.get(e))
            presence: list[PresenceEntry] = []
            for other in space.perceived_by(e):
                if other in mine:
                    continue
                h = handles.get(other) or self._handles.ensure(player_id, other)
                b = space.bodies[other]
                presence.append(
                    PresenceEntry(ref=h.ref, label=h.label, note=h.note, pos=b.pos, inside=b.inside)
                )
            presence.sort(key=lambda x: (x.label, x.ref))
            h_own = handles.get(e) or self._handles.ensure(player_id, e)
            inside = ent.get("inside")
            own.append(
                OwnEntity(
                    ref=h_own.ref,
                    name=self._entity_name(state, e),
                    pos=point_of(ent.get("pos")),
                    inside=inside if isinstance(inside, str) else None,
                    presence=tuple(presence),
                )
            )
        changes = tuple(
            c.model_copy(update={"known_by": ()})
            for c in space.changes
            if c.public or player_id in c.known_by
        )
        seen = tuple(
            SeenEntry(ref=h.ref, label=h.label, note=h.note)
            for h in sorted(self._handles.list(player_id), key=lambda x: (x.label, x.ref))
            if h.entity_id not in mine
        )
        return Scene(entities=tuple(own), map_changes=changes, seen=seen)

    def state_slice(self, game_id: str, player_id: str) -> dict[str, JsonValue]:
        """该玩家各实体感知范围内的状态，给澄清对话用。只含角色此刻能感知或已知的事。"""
        space = self._space(game_id)
        state = space.state
        pack = space.pack
        mine = space.controls.get(player_id, [])
        own: list[JsonValue] = []
        for e in mine:
            ent = _obj(space.entities.get(e))
            tpl = pack.template(str(ent.get("template", "")))
            sheet = visible_sheet(tpl, space.full_sheet(e)) if tpl else {}
            perceived: list[JsonValue] = []
            for other in space.perceived_by(e):
                if other in mine:
                    continue
                h = self._handles.ensure(player_id, other)
                b = space.bodies[other]
                perceived.append(
                    {
                        "handle": h.label,
                        "appearance": self._appearance(state, pack, other),
                        "distance_m": round(self._spatial.distance(space.bodies[e].pos, b.pos), 1),
                        "inside": b.inside,
                    }
                )
            inside = ent.get("inside")
            own.append(
                {
                    "name": self._entity_name(state, e),
                    "template": str(ent.get("template", "")),
                    "pos": ent.get("pos"),
                    "inside": inside if isinstance(inside, str) else None,
                    "sheet": sheet,
                    "perceived": perceived,
                }
            )
        changes: list[JsonValue] = [
            {"feature": c.feature, "status": c.status, "above_z": c.above_z}
            for c in space.changes
            if c.public or player_id in c.known_by
        ]
        return {
            "game_minutes": state.get("game_minutes"),
            "entities": own,
            "known_map_changes": changes,
        }

    def _resolve_point(self, space: Space, ref: TargetRef | None, what: str) -> Point:
        if ref is None:
            raise ValidationFailed("query.missing", param=what)
        if ref.kind == "point" and ref.point is not None:
            return ref.point
        if ref.kind == "entity" and ref.id in space.bodies:
            return space.bodies[ref.id].pos
        if ref.kind == "feature" and ref.id is not None:
            f = space.map.feature(ref.id)
            if f is not None:
                if f.point is not None:
                    return Point(x=f.point[0], y=f.point[1], z=0)
                ring = f.polygon[0] if f.polygon else f.line
                if ring:
                    xs = [p[0] for p in ring]
                    ys = [p[1] for p in ring]
                    return Point(x=sum(xs) / len(xs), y=sum(ys) / len(ys), z=0)
        raise ValidationFailed("query.bad_target", param=what)

    def _ability_shape(self, space: Space, q: SpatialQuery) -> SweepShape:
        """范围效果的形状取自实体角色卡上那个能力的结构化参数，KP 只给起点（实体位置）和朝向。"""
        if q.entity is None or q.entity not in space.bodies:
            raise ValidationFailed("query.bad_entity")
        origin = space.bodies[q.entity].pos
        toward = self._resolve_point(space, q.toward, "toward")
        shape_raw: JsonValue = None
        if q.ability is not None:
            sheet = space.full_sheet(q.entity)
            for entries in _obj(sheet.get("groups")).values():
                for e in entries if isinstance(entries, list) else []:
                    if _obj(e).get("name") == q.ability:
                        shape_raw = _obj(e).get("shape")
            if shape_raw is None and q.shape is None:
                raise ValidationFailed("query.ability_without_shape", ability=q.ability)
        if shape_raw is not None:
            sp = _obj(shape_raw)
            kind = str(sp.get("kind"))

            def num(k: str) -> float | None:
                v = sp.get(k)
                return float(v) if isinstance(v, int | float) else None

            length, width, height = num("length"), num("width"), num("height")
            radius, angle = num("radius"), num("angle")
        elif q.shape is not None:
            # 能力只有文字描述：KP 依据描述给出尺寸，同样记入日志
            kind = q.shape.kind
            length, width, height = q.shape.length, q.shape.width, q.shape.height
            radius, angle = q.shape.radius, q.shape.angle
        else:
            raise ValidationFailed("query.missing", param="shape")
        if kind == "capsule":
            dx, dy, dz = toward.x - origin.x, toward.y - origin.y, toward.z - origin.z
            n = (dx * dx + dy * dy + dz * dz) ** 0.5
            if n == 0 or length is None:
                raise ValidationFailed("query.bad_shape")
            b = Point(
                x=origin.x + dx / n * length,
                y=origin.y + dy / n * length,
                z=origin.z + dz / n * length,
            )
            return SweepShape(
                kind="capsule",
                a=origin,
                b=b,
                radius=radius if radius is not None else (width or 1) / 2,
            )
        if kind == "sphere":
            return SweepShape(kind="sphere", center=toward, radius=radius)
        if kind == "box":
            return SweepShape(
                kind="box", origin=origin, toward=toward, length=length, width=width, height=height
            )
        return SweepShape(kind="cone", origin=origin, toward=toward, length=length, angle=angle)

    def spatial_query(self, game_id: str, query: SpatialQuery) -> SpatialQueryResult:
        """执行 KP 声明的空间查询，写一条 spatial_query 事件（kp_only）。"""
        with self._lock:
            r = self._require(game_id, "roll")
            if query.query_id in self._query_results(game_id, r.no):
                raise ValidationFailed("query.duplicate_id", query=query.query_id)
            space = self._space(game_id)
            bodies = list(space.bodies.values())
            m, ch = space.map, space.changes
            res: SpatialQueryResult
            if query.kind == "within":
                center = self._resolve_point(space, query.center, "center")
                if query.radius is None or query.radius <= 0:
                    raise ValidationFailed("query.missing", param="radius")
                res = SpatialQueryResult(
                    query_id=query.query_id,
                    kind=query.kind,
                    result=self._spatial.within(m, ch, bodies, center, query.radius),
                )
            elif query.kind == "sweep":
                shape = self._ability_shape(space, query)
                hit = self._spatial.sweep(m, ch, bodies, shape)
                # 发动者自己不算命中
                hit = hit.model_copy(
                    update={"entities": tuple(e for e in hit.entities if e != query.entity)}
                )
                res = SpatialQueryResult(
                    query_id=query.query_id, kind=query.kind, shape=shape, result=hit
                )
            elif query.kind == "line_of_sight":
                a = self._resolve_point(space, query.a, "a")
                b = self._resolve_point(space, query.b, "b")
                res = SpatialQueryResult(
                    query_id=query.query_id,
                    kind=query.kind,
                    los=self._spatial.line_of_sight(m, ch, a, b),
                )
            elif query.kind == "distance":
                a = self._resolve_point(space, query.a, "a")
                b = self._resolve_point(space, query.b, "b")
                res = SpatialQueryResult(
                    query_id=query.query_id, kind=query.kind, distance=self._spatial.distance(a, b)
                )
            else:
                res = SpatialQueryResult(
                    query_id=query.query_id,
                    kind=query.kind,
                    features=tuple(self._spatial.locate(m, query.name, query.point)),
                )
            self._events.append(
                game_id,
                r.no,
                [
                    NewEvent(
                        type="spatial_query",
                        actor=ENGINE,
                        visibility=Visibility.kp_only(),
                        payload={
                            "query": query.model_dump(mode="json"),
                            "result": res.model_dump(mode="json"),
                        },
                    )
                ],
            )
            return res

    # ================= 长对局记忆与 KP 辅助读取 =================

    @staticmethod
    def _memory_entries(
        game_id: str, round_no: int, adj: Adjudication, seq: int
    ) -> list[MemoryEntry]:
        return [
            MemoryEntry(
                game_id=game_id,
                round_no=round_no,
                entities=m.entities,
                features=m.features,
                text=m.text,
                source_seq=seq,
            )
            for m in adj.memory_entries
        ]

    def rebuild_memory(self, game_id: str) -> int:
        """记事条目只是索引：随时可以从事件日志里的裁定事件重建。"""
        self._memory.clear(game_id)
        n = 0
        for e in self._events.view_for(game_id, KP, types=["adjudication"]):
            adj = Adjudication.model_validate(e.payload["adjudication"])
            entries = self._memory_entries(game_id, e.round_no, adj, e.seq)
            self._memory.add(entries)
            n += len(entries)
        return n

    def recall(
        self,
        game_id: str,
        entity_ids: Sequence[str],
        feature_ids: Sequence[str] = (),
        actor_ids: Sequence[str] = (),
    ) -> list[MemoryEntry]:
        """按实体检索记事条目（kp_only）。"""
        return self._memory.recall(game_id, list(entity_ids), list(actor_ids), list(feature_ids))

    def record_claim_check(
        self,
        game_id: str,
        player_id: str,
        claim: str,
        verdict: str,
        evidence: Sequence[int],
        note: str = "",
    ) -> Event:
        """一条声明核对的结果（kp_only）。依据事件必须在该玩家的视图内。"""
        with self._lock:
            r = self._require(game_id, "roll")
            if verdict not in ("holds", "fails", "partial"):
                raise ValidationFailed("claim.bad_verdict", verdict=verdict)
            visible = {e.seq for e in self._events.view_for(game_id, player_id)}
            bad = [s for s in evidence if s not in visible]
            if bad:
                raise ValidationFailed("claim.evidence_not_visible", seqs=list(bad))
            ev = NewEvent(
                type="claim_check",
                actor=KP,
                visibility=Visibility.kp_only(),
                payload={
                    "player": player_id,
                    "claim": claim,
                    "verdict": verdict,
                    "evidence": list(evidence),
                    "note": note,
                },
            )
            return self._events.append(game_id, r.no, [ev])[0]

    def nearby_features(
        self, game_id: str, player_id: str, radius: float = 200.0, limit: int = 60
    ) -> list[dict[str, JsonValue]]:
        """玩家各实体附近有名字的地物，供意图解析把地点名对应到地物 id。

        同名同类的地物（一条路的很多段）只留最近的一个；按距离取最近的 limit 个，控制 prompt 长度。
        """
        space = self._space(game_id)
        m = space.map
        best: dict[tuple[str, str], tuple[float, str]] = {}
        for e in space.controls.get(player_id, []):
            b = space.bodies.get(e)
            if b is None:
                continue
            hit = self._spatial.within(m, space.changes, [], b.pos, radius)
            for fid in hit.features:
                f = m.feature(fid)
                if f is None or not f.name:
                    continue
                loc = self.feature_location(game_id, fid) if f.kind != "road" else None
                d = self._spatial.distance(b.pos, loc.pos) if loc else radius
                key = (f.name, f.kind)
                if key not in best or d < best[key][0]:
                    best[key] = (d, fid)
        ranked = sorted(best.items(), key=lambda kv: kv[1][0])[:limit]
        return [{"id": fid, "name": name, "kind": kind} for (name, kind), (_d, fid) in ranked]

    def record_summary(self, game_id: str, round_no: int, text: str) -> Event:
        """滚动摘要（kp_only）。只是索引和氛围，不能作为事实依据。"""
        ev = NewEvent(
            type="summary",
            actor=KP,
            visibility=Visibility.kp_only(),
            payload={"text": _text(text), "round": round_no},
        )
        return self._events.append(game_id, round_no, [ev])[0]

    def latest_summary(self, game_id: str) -> str:
        evs = self._events.view_for(game_id, KP, types=["summary"])
        return str(evs[-1].payload.get("text", "")) if evs else ""

    def derived_all(self, game_id: str) -> dict[str, dict[str, float]]:
        """全部实体的推导值（仅供 KP 与控制台）。"""
        pack = self.rulepack(game_id)
        out: dict[str, dict[str, float]] = {}
        for eid, raw in _obj(self._state(game_id).get("entities")).items():
            ent = _obj(raw)
            try:
                vals = self._rules.derive(pack, str(ent.get("template", "")), ent.get("sheet"))
            except (ValidationFailed, NotFound):
                continue
            out[eid] = {d.name: round(d.value, 4) for d in vals}
        return out

    def resolve_place(self, game_id: str, place: Place) -> Location:
        """把地名或坐标解析成位置。地名先找完全同名的地物，再找包含这个名字的；建筑优先。"""
        if place.pos is not None:
            return Location(pos=place.pos, inside=place.inside)
        if not place.place:
            raise ValidationFailed("place.empty")
        m = self._map(game_id)
        ids = [place.place] if m.feature(place.place) else self._spatial.locate(m, name=place.place)
        if not ids:
            raise ValidationFailed("place.not_found", place=place.place)
        ids.sort(key=lambda i: (0 if (f := m.feature(i)) and f.kind == "building" else 1, i))
        fid = ids[0]
        f = m.feature(fid)
        assert f is not None
        z: float | None = None
        if place.roof and f.kind == "building":
            z = f.height
        elif place.floor is not None:
            z = (place.floor - 1) * 3.0 if place.floor >= 1 else place.floor * 3.0
        return self.feature_location(game_id, fid, z)

    def feature_location(self, game_id: str, feature_id: str, z: float | None = None) -> Location:
        """地物里的一个代表点：建筑取轮廓内的一点，z 默认地面（楼顶写建筑高度）。"""
        m = self._map(game_id)
        f = m.feature(feature_id)
        if f is None:
            raise NotFound("map.unknown_feature", id=feature_id)
        if f.point is not None:
            return Location(pos=Point(x=f.point[0], y=f.point[1], z=z or 0.0))
        ring = f.polygon[0] if f.polygon else f.line
        assert ring
        cands = [
            ((ring[0][0] + ring[i][0]) / 2, (ring[0][1] + ring[i][1]) / 2)
            for i in range(1, len(ring))
        ]
        cands.insert(0, (sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)))
        for x, y in cands:
            pt = Point(x=x, y=y, z=z or 0.0)
            if f.kind != "building" or self._spatial.inside_feature(m, feature_id, pt):
                inside = feature_id if f.kind == "building" else None
                if inside and z is not None and not (f.min_height - 1e-6 <= z <= f.height + 1e-6):
                    raise ValidationFailed("space.height_outside_building", id=feature_id)
                return Location(pos=pt, inside=inside)
        raise ValidationFailed("space.no_point_inside", id=feature_id)

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
