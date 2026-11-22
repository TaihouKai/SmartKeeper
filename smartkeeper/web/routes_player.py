"""玩家接口。只认玩家 token；请求里同时带着管理员会话也不改变返回内容。路径和请求体里不接受玩家 id。

注意：这个文件不用 from __future__ import annotations，因为依赖项 require_player 是局部变量，FastAPI 要在运行时解析注解。
"""

import logging
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, JsonValue

from smartkeeper.contracts import (
    DerivedValue,
    IdentityRules,
    Player,
    Problem,
    SheetSubmission,
    SheetView,
    ValidationFailed,
)
from smartkeeper.engine import split_front_matter
from smartkeeper.mapdata import display_geojson, to_meters
from smartkeeper.rules import render as render_rules
from smartkeeper.web.auth import RateLimiter
from smartkeeper.web.services import Services
from smartkeeper.web.views import (
    ActionEcho,
    EventOut,
    RefIntent,
    SceneOut,
    echo,
    event_for_player,
    scene,
)

log = logging.getLogger("smartkeeper.web")


class MeOut(BaseModel):
    player_id: str
    display_name: str
    ui_language: str
    game_id: str
    game_name: str
    game_status: str
    character_status: str
    has_identity: bool


class StatusOut(BaseModel):
    round: int
    phase: str | None
    game_status: str
    game_minutes: int
    start_time: str | None
    submitted: int
    total: int
    me_submitted: bool


class RulesOut(BaseModel):
    rulebook: str
    world_name: str
    templates: list[dict[str, JsonValue]]
    player_entities: list[dict[str, JsonValue]]
    identities: IdentityRules
    scenario: str


class TextIn(BaseModel):
    text: str


class BroadcastIn(BaseModel):
    text: str
    anonymous: bool = False


class IdentityIn(BaseModel):
    choice: str | None = None


class CharacterIn(BaseModel):
    sheets: list[SheetSubmission]


class PreviewIn(BaseModel):
    template: str
    sheet: dict[str, JsonValue]


class PreviewOut(BaseModel):
    derived: list[DerivedValue]
    problems: list[Problem]


class FormulaIn(BaseModel):
    formula: str
    template: str | None = None
    in_entry: str | None = None


class FormulaOut(BaseModel):
    problems: list[Problem]
    names: list[str]


class HandleIn(BaseModel):
    label: str | None = None
    note: str | None = None


class ActionIn(BaseModel):
    text: str
    intent: RefIntent


class ChatIn(BaseModel):
    to: str
    text: str


class ChatMessageOut(BaseModel):
    id: int
    sender: str
    recipient: str
    mine: bool
    text: str
    created_at: str


class PeerOut(BaseModel):
    player_id: str
    display_name: str


class LangIn(BaseModel):
    lang: str


class ProjectOut(BaseModel):
    x: float
    y: float


class OkOut(BaseModel):
    ok: bool = True


def build_player_router(s: Services, require_player: Callable[..., Player]) -> APIRouter:
    r = APIRouter(prefix="/api", tags=["player"])
    e = s.engine
    chat_limit = RateLimiter(limit=6, window=60)

    def names(game_id: str) -> dict[str, str]:
        return {p.id: p.display_name for p in e.players(game_id)}

    def background(fn: Callable[..., Any], *args: Any) -> Callable[[], None]:
        def run() -> None:
            try:
                fn(*args)
            except Exception:
                log.exception("background task %s failed", getattr(fn, "__name__", fn))

        return run

    @r.get("/me")
    def me(p: Annotated[Player, Depends(require_player)]) -> MeOut:
        g = e.game(p.game_id)
        has_identity = any(x.type == "identity_assigned" for x in e.view_for(g.id, p.id))
        return MeOut(
            player_id=p.id,
            display_name=p.display_name,
            ui_language=p.ui_language,
            game_id=g.id,
            game_name=g.name,
            game_status=g.status,
            character_status=e.character_status(p.id),
            has_identity=has_identity,
        )

    @r.post("/lang")
    def lang(p: Annotated[Player, Depends(require_player)], body: LangIn) -> OkOut:
        e.set_ui_language(p.id, body.lang)
        return OkOut()

    @r.get("/events")
    def events(p: Annotated[Player, Depends(require_player)], since: int = 0) -> list[EventOut]:
        nm = names(p.game_id)
        return [event_for_player(e, p.id, x, nm) for x in e.view_for(p.game_id, p.id, since)]

    @r.get("/status")
    def status(p: Annotated[Player, Depends(require_player)]) -> StatusOut:
        g = e.game(p.game_id)
        meta = split_front_matter(g.scenario_public)[0]
        start = meta.get("start_time")
        done, total = e.submitted_count(g.id) if g.status == "running" else (0, 0)
        phase = e.round(g.id).status if g.current_round else None
        minutes = e.world_state(g.id).get("game_minutes")
        return StatusOut(
            round=g.current_round,
            phase=phase,
            game_status=g.status,
            game_minutes=int(minutes) if isinstance(minutes, int) else 0,
            start_time=str(start) if start else None,
            submitted=done,
            total=total,
            me_submitted=g.status == "running" and p.id in e.declarations(g.id),
        )

    @r.get("/rules")
    def rules(p: Annotated[Player, Depends(require_player)]) -> RulesOut:
        pack = e.rulepack(p.game_id)
        g = e.game(p.game_id)
        templates: list[dict[str, JsonValue]] = []
        for t in pack.templates:
            d = t.model_dump(mode="json")
            d["fields"] = [f for f in d["fields"] if not f["hidden"]]
            d["groups"] = [x for x in d["groups"] if not x["hidden"]]
            d["derived"] = [x for x in d["derived"] if not x["hidden"]]
            templates.append(d)
        return RulesOut(
            rulebook=render_rules(pack, include_hidden=False),
            world_name=pack.world.name,
            templates=templates,
            player_entities=[x.model_dump(mode="json") for x in pack.player_entities],
            identities=e.identity_rules(g.id),
            scenario=split_front_matter(g.scenario_public)[1],
        )

    @r.post("/identity")
    def identity(p: Annotated[Player, Depends(require_player)], body: IdentityIn) -> EventOut:
        ev = e.assign_identity(p.id, body.choice)
        return event_for_player(e, p.id, ev, names(p.game_id))

    @r.post("/character")
    def character(
        p: Annotated[Player, Depends(require_player)], body: CharacterIn, bg: BackgroundTasks
    ) -> OkOut:
        e.submit_character(p.id, body.sheets)
        bg.add_task(background(s.kp.review_character, p.id))
        return OkOut()

    @r.get("/character")
    def submitted(p: Annotated[Player, Depends(require_player)]) -> list[SheetSubmission]:
        try:
            return e.submitted_character(p.id)
        except Exception:
            return []

    @r.post("/character/preview")
    def preview(p: Annotated[Player, Depends(require_player)], body: PreviewIn) -> PreviewOut:
        pack = e.rulepack(p.game_id)
        try:
            sheet = s.rules.init_sheet(pack, body.template, body.sheet)
        except ValidationFailed as err:
            return PreviewOut(derived=[], problems=[Problem(code=err.code, params=err.params)])
        problems = s.rules.validate_sheet(pack, body.template, sheet)
        derived: list[DerivedValue] = []
        if not problems:
            derived = s.rules.derive(pack, body.template, sheet)
        return PreviewOut(derived=derived, problems=problems)

    @r.post("/formula/validate")
    def formula(p: Annotated[Player, Depends(require_player)], body: FormulaIn) -> FormulaOut:
        pack = e.rulepack(p.game_id)
        return FormulaOut(
            problems=s.rules.validate_formula(pack, body.template, body.formula, body.in_entry),
            names=s.rules.complete_names(pack, body.template),
        )

    @r.get("/map")
    def map_(p: Annotated[Player, Depends(require_player)]) -> dict[str, Any]:
        return display_geojson(e.map_data(p.game_id))

    @r.get("/map/project")
    def project(
        p: Annotated[Player, Depends(require_player)], lon: float, lat: float
    ) -> ProjectOut:
        m = e.map_data(p.game_id)
        x, y = to_meters(m.origin.lon, m.origin.lat, lon, lat)
        return ProjectOut(x=round(x, 2), y=round(y, 2))

    @r.get("/scene")
    def scene_(p: Annotated[Player, Depends(require_player)]) -> SceneOut:
        return scene(e, p.game_id, p.id)

    @r.get("/sheets")
    def sheets(p: Annotated[Player, Depends(require_player)]) -> list[SheetView]:
        views = e.sheets(p.game_id, p.id)
        # 实体 id 换成该玩家的 ref
        return [
            v.model_copy(update={"entity_id": e.ref_for_entity(p.id, v.entity_id) or "?"})
            for v in views
        ]

    @r.patch("/handles/{ref}")
    def handle(p: Annotated[Player, Depends(require_player)], ref: str, body: HandleIn) -> OkOut:
        e.rename_handle(p.id, ref, body.label, body.note)
        return OkOut()

    @r.post("/broadcast")
    def broadcast(p: Annotated[Player, Depends(require_player)], body: BroadcastIn) -> EventOut:
        ev = e.post_broadcast(p.game_id, p.id, body.text, body.anonymous)
        return event_for_player(e, p.id, ev, names(p.game_id))

    @r.post("/kp/chat")
    def kp_chat(
        p: Annotated[Player, Depends(require_player)], body: TextIn, bg: BackgroundTasks
    ) -> EventOut:
        if not chat_limit.hit(p.id):
            raise HTTPException(status_code=429, detail={"code": "rate.kp_chat"})
        ev = e.post_kp_chat(p.id, body.text)
        bg.add_task(background(s.kp.answer_chat, p.id))
        return event_for_player(e, p.id, ev, names(p.game_id))

    @r.post("/action/parse")
    def action_parse(p: Annotated[Player, Depends(require_player)], body: TextIn) -> ActionEcho:
        if not chat_limit.hit(p.id):
            raise HTTPException(status_code=429, detail={"code": "rate.kp_chat"})
        intent = s.kp.parse_intent(p.id, body.text)
        return echo(e, p.game_id, p.id, body.text, intent)

    @r.post("/action")
    def action(
        p: Annotated[Player, Depends(require_player)], body: ActionIn, bg: BackgroundTasks
    ) -> EventOut:
        intent = body.intent.to_intent(e, p.id)
        ev = e.declare_action(p.id, body.text, intent)
        bg.add_task(background(s.kp.on_action, p.game_id))
        return event_for_player(e, p.id, ev, names(p.game_id))

    @r.get("/chat/peers")
    def peers(p: Annotated[Player, Depends(require_player)]) -> list[PeerOut]:
        return [
            PeerOut(player_id=x.id, display_name=x.display_name)
            for x in e.players(p.game_id)
            if x.active and x.id != p.id
        ]

    @r.get("/chat")
    def chat(p: Annotated[Player, Depends(require_player)], since: int = 0) -> list[ChatMessageOut]:
        return [
            ChatMessageOut(
                id=m.id,
                sender=m.sender,
                recipient=m.recipient,
                mine=m.sender == p.id,
                text=m.text,
                created_at=m.created_at,
            )
            for m in s.chat.for_player(p.game_id, p.id, since)
        ]

    @r.post("/chat")
    def chat_post(p: Annotated[Player, Depends(require_player)], body: ChatIn) -> ChatMessageOut:
        peer = e.player(body.to)
        if peer.game_id != p.game_id or not peer.active:
            raise HTTPException(status_code=404, detail={"code": "chat.unknown_peer"})
        m = s.chat.post(p.game_id, p.id, peer.id, body.text)
        return ChatMessageOut(
            id=m.id,
            sender=m.sender,
            recipient=m.recipient,
            mine=True,
            text=m.text,
            created_at=m.created_at,
        )

    return r
