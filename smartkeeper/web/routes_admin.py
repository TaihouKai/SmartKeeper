"""管理控制台接口。只接受管理控制台的会话，玩家 token 一律 403。"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, JsonValue

from smartkeeper.contracts import (
    KP,
    Adjudication,
    DerivedValue,
    Event,
    Game,
    GameConfig,
    GameSettings,
    IllegalState,
    LLMCallRecord,
    NotFound,
    PatchOp,
    Problem,
    Round,
    RulePack,
    RulePackInfo,
    RulePackVersion,
    ValidationFailed,
)
from smartkeeper.engine import kp_meta, public_meta
from smartkeeper.mapdata import display_geojson
from smartkeeper.rules import export_pack, parse_import
from smartkeeper.web.auth import ADMIN_COOKIE, ADMIN_COOKIE_PATH, ADMIN_SESSION_SECONDS, Auth
from smartkeeper.web.services import Services

log = logging.getLogger("smartkeeper.web")
_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class LoginIn(BaseModel):
    password: str


class OkOut(BaseModel):
    ok: bool = True


class AdminMe(BaseModel):
    enabled: bool


class MaterialsOut(BaseModel):
    maps: list[str]
    scenarios: list[str]


class TextBody(BaseModel):
    text: str


class ScenarioOut(BaseModel):
    name: str
    public: str
    kp: str


class NewPackIn(BaseModel):
    name: str


class PackIn(BaseModel):
    pack: RulePack


class ValidateOut(BaseModel):
    problems: list[Problem]


class TryIn(BaseModel):
    pack: RulePack
    template: str
    sheet: dict[str, JsonValue]


class TryOut(BaseModel):
    derived: list[DerivedValue]
    problems: list[Problem]
    sheet: JsonValue = None


class FormulaIn(BaseModel):
    pack: RulePack
    formula: str
    template: str | None = None
    in_entry: str | None = None


class FormulaOut(BaseModel):
    problems: list[Problem]
    names: list[str]


class NewGameIn(BaseModel):
    name: str
    rulepack_id: str
    rulepack_version: int
    map_id: str | None = None
    scenario: str
    settings: GameSettings = GameSettings()


class PlayerRow(BaseModel):
    id: str
    display_name: str
    active: bool
    character_status: str
    submitted: bool


class GameDetail(BaseModel):
    game: Game
    players: list[PlayerRow]
    round: Round | None
    searchable: bool


class PatchGameIn(BaseModel):
    settings: GameSettings | None = None
    action: Literal["start", "end"] | None = None


class InviteIn(BaseModel):
    display_name: str


class InviteOut(BaseModel):
    player_id: str
    url: str


class ReviewOut(BaseModel):
    round: Round
    dice: list[dict[str, JsonValue]]
    queries: list[dict[str, JsonValue]]
    claims: list[dict[str, JsonValue]]
    declarations: dict[str, JsonValue]


class ReviewIn(BaseModel):
    adjudication: Adjudication | None = None
    feedback: dict[str, str] = {}
    broadcast: str | None = None


class RewriteIn(BaseModel):
    player_id: str


class AdminEvent(BaseModel):
    seq: int
    round_no: int
    type: str
    actor: str | None
    visibility: dict[str, JsonValue]
    payload: dict[str, JsonValue]
    created_at: str


class StatePatchIn(BaseModel):
    ops: list[PatchOp]
    note: str = ""


def _admin_event(e: Event) -> AdminEvent:
    return AdminEvent(
        seq=e.seq,
        round_no=e.round_no,
        type=e.type,
        actor=e.actor,
        visibility=e.visibility.model_dump(mode="json"),
        payload=e.payload,
        created_at=e.created_at.isoformat(),
    )


def build_admin_router(s: Services, auth: Auth) -> APIRouter:
    r = APIRouter(prefix="/api/admin", tags=["admin"])
    guarded = APIRouter(dependencies=[Depends(auth.require_admin)])
    e, kp = s.engine, s.kp
    scen_dir = Path(s.scenarios_dir)

    def background(fn: Callable[..., Any], *args: Any) -> Callable[[], None]:
        def run() -> None:
            try:
                fn(*args)
            except Exception:
                log.exception("background task %s failed", getattr(fn, "__name__", fn))

        return run

    # ---------------- 登录 ----------------

    @r.post("/login")
    def login(body: LoginIn, request: Request, response: Response) -> OkOut:
        ip = request.client.host if request.client else "?"
        if not auth.login_limiter.hit(ip):
            raise HTTPException(status_code=429, detail={"code": "rate.login"})
        if not auth.check_password(body.password):
            raise HTTPException(status_code=403, detail={"code": "auth.bad_password"})
        response.set_cookie(
            ADMIN_COOKIE,
            auth.new_session(),
            max_age=ADMIN_SESSION_SECONDS,
            path=ADMIN_COOKIE_PATH,
            httponly=True,
            samesite="strict",
        )
        return OkOut()

    @r.post("/logout")
    def logout(response: Response) -> OkOut:
        response.delete_cookie(ADMIN_COOKIE, path=ADMIN_COOKIE_PATH)
        return OkOut()

    @r.get("/enabled")
    def enabled() -> AdminMe:
        return AdminMe(enabled=auth.admin_enabled)

    @guarded.get("/session")
    def session() -> OkOut:
        return OkOut()

    # ---------------- 资料 ----------------

    @guarded.get("/materials")
    def materials() -> MaterialsOut:
        scen = (
            sorted(p.name for p in scen_dir.iterdir() if (p / "scenario_public.md").is_file())
            if scen_dir.is_dir()
            else []
        )
        return MaterialsOut(maps=s.maps.list_ids(), scenarios=scen)

    @guarded.get("/materials/scenarios/{name}")
    def get_scenario(name: str) -> ScenarioOut:
        d = _scenario_dir(name)
        if not (d / "scenario_public.md").is_file():
            raise NotFound("scenario.not_found", name=name)
        kp_file = d / "scenario_kp.md"
        return ScenarioOut(
            name=name,
            public=(d / "scenario_public.md").read_text(encoding="utf-8"),
            kp=kp_file.read_text(encoding="utf-8") if kp_file.is_file() else "",
        )

    def _scenario_dir(name: str) -> Path:
        if not _NAME.match(name):
            raise ValidationFailed("scenario.bad_name", name=name)
        return scen_dir / name

    @guarded.put("/materials/scenarios/{name}/{part}")
    def put_scenario(name: str, part: Literal["public", "kp"], body: TextBody) -> OkOut:
        (public_meta if part == "public" else kp_meta)(body.text)  # 先校验 front matter
        d = _scenario_dir(name)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"scenario_{part}.md").write_text(body.text, encoding="utf-8")
        return OkOut()

    @guarded.get("/materials/maps/{map_id}")
    def get_map(map_id: str) -> dict[str, Any]:
        return display_geojson(s.maps.load(map_id))

    @guarded.put("/materials/maps/{map_id}")
    def put_map(map_id: str, body: TextBody) -> OkOut:
        s.maps.save(map_id, body.text)
        return OkOut()

    # ---------------- 规则包 ----------------

    @guarded.get("/rulepacks")
    def packs() -> list[RulePackInfo]:
        return s.packs.list_packs()

    @guarded.post("/rulepacks")
    def new_pack(body: NewPackIn) -> RulePackInfo:
        pid = s.packs.create_pack(body.name)
        return RulePackInfo(pack_id=pid, name=body.name, versions=())

    @guarded.get("/rulepacks/{pack_id}/versions/{version}")
    def get_version(pack_id: str, version: int) -> RulePackVersion:
        return s.packs.get_version(pack_id, version)

    @guarded.post("/rulepacks/{pack_id}/versions")
    def save_version(pack_id: str, body: PackIn) -> RulePackVersion:
        return s.packs.save_version(pack_id, body.pack)

    @guarded.delete("/rulepacks/{pack_id}/versions/{version}")
    def delete_version(pack_id: str, version: int) -> OkOut:
        e.delete_rulepack_version(pack_id, version)
        return OkOut()

    @guarded.post("/rulepacks/validate")
    def validate_pack(body: PackIn) -> ValidateOut:
        return ValidateOut(problems=s.rules.validate_pack(body.pack))

    @guarded.post("/rulepacks/try")
    def try_pack(body: TryIn) -> TryOut:
        try:
            sheet = s.rules.init_sheet(body.pack, body.template, body.sheet)
        except ValidationFailed as err:
            return TryOut(derived=[], problems=[Problem(code=err.code, params=err.params)])
        problems = s.rules.validate_sheet(body.pack, body.template, sheet)
        derived = [] if problems else s.rules.derive(body.pack, body.template, sheet)
        return TryOut(derived=derived, problems=problems, sheet=sheet)

    @guarded.post("/rulepacks/formula")
    def formula(body: FormulaIn) -> FormulaOut:
        return FormulaOut(
            problems=s.rules.validate_formula(
                body.pack, body.template, body.formula, body.in_entry
            ),
            names=s.rules.complete_names(body.pack, body.template),
        )

    @guarded.post("/rulepacks/import")
    def import_pack(body: TextBody) -> RulePackVersion:
        pack = parse_import(body.text)
        problems = s.rules.validate_pack(pack)
        if problems:
            raise ValidationFailed("rulepack.invalid", problems)
        pid = s.packs.create_pack(pack.world.name)
        return s.packs.save_version(pid, pack)

    @guarded.get("/rulepacks/{pack_id}/versions/{version}/export")
    def export(pack_id: str, version: int) -> Response:
        text = export_pack(s.packs.get_version(pack_id, version).pack)
        return Response(
            content=text,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{pack_id}-v{version}.json"'},
        )

    # ---------------- 局 ----------------

    @guarded.get("/games")
    def games() -> list[Game]:
        return e.list_games()

    @guarded.post("/games")
    def new_game(body: NewGameIn) -> Game:
        sc = get_scenario(body.scenario)
        return e.create_game(
            GameConfig(
                name=body.name,
                rulepack_id=body.rulepack_id,
                rulepack_version=body.rulepack_version,
                map_id=body.map_id,
                scenario_public=sc.public,
                scenario_kp=sc.kp,
                settings=body.settings,
            )
        )

    @guarded.get("/games/{game_id}")
    def game(game_id: str) -> GameDetail:
        g = e.game(game_id)
        decl = e.declarations(game_id) if g.current_round else {}
        rows = [
            PlayerRow(
                id=p.id,
                display_name=p.display_name,
                active=p.active,
                character_status=e.character_status(p.id),
                submitted=p.id in decl,
            )
            for p in e.players(game_id)
        ]
        rnd = e.round(game_id) if g.current_round else None
        return GameDetail(game=g, players=rows, round=rnd, searchable=s.judge.supports_search)

    @guarded.patch("/games/{game_id}")
    def patch_game(game_id: str, body: PatchGameIn, bg: BackgroundTasks) -> Game:
        if body.settings is not None:
            e.update_settings(game_id, body.settings)
        if body.action == "start":
            g = e.game(game_id)
            if g.status != "characters":
                raise IllegalState("game.not_in_character_phase")
            pending = [
                p.id
                for p in e.players(game_id)
                if p.active and e.character_status(p.id) != "approved"
            ]
            if pending or not any(p.active for p in e.players(game_id)):
                raise IllegalState("game.characters_pending", players=list[JsonValue](pending))
            bg.add_task(background(kp.open_game, game_id))
        elif body.action == "end":
            e.end_game(game_id)
        return e.game(game_id)

    @guarded.post("/games/{game_id}/invites")
    def invite(game_id: str, body: InviteIn, request: Request) -> InviteOut:
        p, token = e.add_player(game_id, body.display_name)
        base = s.base_url or str(request.base_url)
        return InviteOut(player_id=p.id, url=f"{base.rstrip('/')}/join/{token}")

    @guarded.delete("/games/{game_id}/invites/{player_id}")
    def revoke(game_id: str, player_id: str) -> OkOut:
        if e.player(player_id).game_id != game_id:
            raise NotFound("player.not_found")
        e.revoke_player(player_id)
        return OkOut()

    @guarded.post("/games/{game_id}/characters/{player_id}/review")
    def rereview(game_id: str, player_id: str, bg: BackgroundTasks) -> OkOut:
        bg.add_task(background(kp.review_character, player_id))
        return OkOut()

    # ---------------- 回合与审核 ----------------

    @guarded.post("/games/{game_id}/round/close")
    def force_close(game_id: str, bg: BackgroundTasks) -> OkOut:
        if e.round(game_id).status != "collecting":
            raise IllegalState("round.not_collecting")
        bg.add_task(background(kp.force_close, game_id))
        return OkOut()

    @guarded.post("/games/{game_id}/round/rerun")
    def rerun(game_id: str, bg: BackgroundTasks) -> OkOut:
        if e.round(game_id).status != "review":
            raise IllegalState("round.not_in_review")
        bg.add_task(background(kp.rerun, game_id))
        return OkOut()

    @guarded.get("/games/{game_id}/round/review")
    def review(game_id: str) -> ReviewOut:
        rnd = e.round(game_id)
        this = [x for x in e.view_for(game_id, KP) if x.round_no == rnd.no]
        return ReviewOut(
            round=rnd,
            dice=[x.payload for x in this if x.type == "dice_roll"],
            queries=[x.payload for x in this if x.type == "spatial_query"],
            claims=[x.payload for x in this if x.type == "claim_check"],
            declarations={pid: ev.payload for pid, ev in e.declarations(game_id, rnd.no).items()},
        )

    @guarded.put("/games/{game_id}/round/review")
    def save_review(game_id: str, body: ReviewIn) -> OkOut:
        if body.adjudication is not None:
            e.edit_adjudication(game_id, body.adjudication)
        for pid, text in body.feedback.items():
            e.set_feedback_draft(game_id, pid, text)
        if body.broadcast is not None:
            e.set_broadcast_draft(game_id, body.broadcast or None)
        return OkOut()

    @guarded.post("/games/{game_id}/round/rewrite")
    def rewrite(game_id: str, body: RewriteIn) -> OkOut:
        kp.rewrite_feedback(game_id, body.player_id)
        return OkOut()

    @guarded.post("/games/{game_id}/round/publish")
    def publish(game_id: str, bg: BackgroundTasks) -> Round:
        draft = e.draft(game_id) or {}
        raw = draft.get("adjudication")
        adj = Adjudication.model_validate(raw) if raw is not None else None
        rnd = e.publish_round(game_id)
        bg.add_task(background(kp.after_publish, game_id, rnd.no, adj))
        bg.add_task(background(kp.name_pending_handles, game_id))
        return rnd

    # ---------------- 日志、状态、LLM 调用 ----------------

    @guarded.get("/games/{game_id}/events")
    def events(
        game_id: str, as_: Annotated[str | None, Query(alias="as")] = None, since: int = 0
    ) -> list[AdminEvent]:
        audience = as_ or KP
        return [_admin_event(x) for x in e.view_for(game_id, audience, since)]

    @guarded.get("/games/{game_id}/state")
    def state(game_id: str, round: int | None = None) -> dict[str, JsonValue]:
        return e.world_state(game_id, round)

    @guarded.patch("/games/{game_id}/state")
    def patch_state(game_id: str, body: StatePatchIn) -> dict[str, JsonValue]:
        return e.admin_patch(game_id, body.ops, body.note)

    @guarded.get("/games/{game_id}/llm-calls")
    def llm_calls(game_id: str, limit: int = 200) -> list[LLMCallRecord]:
        return s.llm_log.list(game_id, limit)

    r.include_router(guarded)
    return r
