"""玩家接口。只认玩家 token；请求里同时带着管理员会话也不改变返回内容。路径和请求体里不接受玩家 id。

注意：这个文件不用 from __future__ import annotations，因为依赖项 require_player 是局部变量，FastAPI 要在运行时解析注解。
"""

import logging
import secrets
import time
from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field, JsonValue

from smartkeeper.contracts import (
    AllianceView,
    DerivedValue,
    FormulaScope,
    IdentityRules,
    Intent,
    LibraryCharacter,
    LibraryCharacterFull,
    NotFound,
    PackParam,
    Player,
    Point,
    Problem,
    ReactionChoice,
    ReactionSkill,
    RulePack,
    Rules,
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
    SceneOut,
    TalkOut,
    echo,
    event_for_player,
    scene,
    talk_for_player,
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
    """玩家只看到自己的状态和自己的时间，没有回合数、没有全局进度：不能从这些推断别人在做什么。"""

    game_status: str
    game_seconds: int  # 自己的时间：上一次收到消息时的游戏内时刻
    start_time: str | None
    # act：轮到我行动；submitted：已提交，等结算；busy：我的行动还在进行
    me: Literal["act", "submitted", "busy", "idle"]


class RulesOut(BaseModel):
    rulebook: str
    handbook: str  # 规则书（Markdown）
    params: list[PackParam]  # 默认参数（各自适用于哪些分组）
    checks: list[str]  # 检定名（自己加参数时可以要求过一个检定）
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
    presets: dict[str, list[str]] = {}  # 分组名 -> 按当前填写会生效的固定条目名
    # 上下限是公式的字段（例如随出身变的范围）：按当前填写算出来的 [下限, 上限]，算不出的是 null
    ranges: dict[str, list[float | None]] = {}


class FormulaIn(BaseModel):
    formula: str
    template: str | None = None
    in_entry: str | None = None
    dice: bool = False  # 掷骰公式字段：允许掷骰
    script: bool = False  # 技能脚本
    config: bool = False  # 技能设置
    bonus: bool = False  # 常驻加成
    other: str = ""  # 条目的另一半（技能设置 / 技能脚本），两边可以互相引用名字
    names: list[str] = []  # 条目、用途自己加的参数名（公式里 this.<名字>）


class FormulaOut(BaseModel):
    problems: list[Problem]
    names: list[str]


class HandleIn(BaseModel):
    label: str | None = None
    note: str | None = None


class LibraryOpenIn(BaseModel):
    password: str | None = None


class LibrarySaveIn(BaseModel):
    sheets: JsonValue  # 和提交角色卡一样的格式
    name: str = ""  # 空着就用各张卡的角色名
    summary: str = ""
    password: str | None = None  # 新建：要设的密码；更新：原来的密码
    new_password: str | None = None  # 更新时改密码（空字符串是去掉密码）；None 是不改


class AllianceIn(BaseModel):
    ref: str  # 向这个角色的玩家提出


class AnswerIn(BaseModel):
    accept: bool


class ActionIn(BaseModel):
    parse_id: str
    quotes: list[int] = []


class TravelOut(BaseModel):
    ref: str
    name: str
    seconds: int | None  # None：没有位置或走不了
    fly: bool


class TalkStartIn(BaseModel):
    to: str  # 对方的 ref
    from_: str | None = Field(default=None, alias="from")  # 我的哪个实体；只有一个时可省略


class TalkAnswerIn(BaseModel):
    accept: bool


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


class NameIn(BaseModel):
    name: str


class DraftIn(BaseModel):
    sheets: JsonValue  # 建角表单的原样内容，不校验


class DraftOut(BaseModel):
    sheets: JsonValue = None
    updated_at: str | None = None


class ProjectOut(BaseModel):
    x: float
    y: float


class ReactionOut(BaseModel):
    """一次等我应对的攻击：哪个技能、打的是我的哪个角色、谁打的（看不见是空）、能选的应对。"""

    seq: int
    entry: str
    defender: str
    who: str | None = None
    checks: list[str]
    labels: dict[str, str] = {}
    skills: list[ReactionSkill]


class ReactIn(BaseModel):
    choices: list[ReactionChoice]


class OkOut(BaseModel):
    ok: bool = True


def _no_dice(count: int, sides: int) -> tuple[int, ...]:
    """上下限不掷骰；万一写了骰子就按最小值。"""
    return tuple(1 for _ in range(count))


def _ranges(
    rules: Rules, pack: RulePack, template: str, sheet: JsonValue
) -> dict[str, list[float | None]]:
    """上下限写成公式的数值字段，按这张卡现在的填写算出来（例如随出身变的范围）。"""
    tpl = pack.template(template)
    out: dict[str, list[float | None]] = {}
    for fd in tpl.fields if tpl else ():
        if fd.cls != "player" or fd.kind not in ("number", "resource"):
            continue
        texts = (fd.min, fd.max)
        if all(x is None or _literal(x) for x in texts):
            continue
        vals: list[float | None] = []
        for text in texts:
            try:
                vals.append(
                    rules.roll(pack, text, _no_dice, template, sheet).total if text else None
                )
            except (ValidationFailed, NotFound):
                vals.append(None)
        out[fd.name] = vals
    return out


def _literal(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _presets(rules: Rules, pack: RulePack, template: str, sheet: JsonValue) -> dict[str, list[str]]:
    """按这张卡现在的填写会生效的固定条目名（固定条目排在玩家条目前面）。"""
    full = rules.full_sheet(pack, template, sheet)
    if not isinstance(full, dict) or not isinstance(sheet, dict):
        return {}
    own = sheet.get("groups")
    own = own if isinstance(own, dict) else {}
    out: dict[str, list[str]] = {}
    groups = full.get("groups")
    for g, entries in (groups if isinstance(groups, dict) else {}).items():
        mine = own.get(g)
        if not isinstance(entries, list):
            continue
        n = len(entries) - (len(mine) if isinstance(mine, list) else 0)
        names = [str(e.get("name", "")) for e in entries[:n] if isinstance(e, dict)]
        if names:
            out[g] = names
    return out


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

    @r.post("/me/name")
    def rename(p: Annotated[Player, Depends(require_player)], body: NameIn) -> OkOut:
        """改自己的玩家昵称（不是角色名）。"""
        e.rename_player(p.id, body.name)
        return OkOut()

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
        me: Literal["act", "submitted", "busy", "idle"] = "idle"
        if g.status == "running":
            if not e.idle_entities(g.id, p.id):
                me = "busy"
            elif p.id in e.declarations(g.id) or e.round(g.id).status != "collecting":
                me = "submitted"
            else:
                me = "act"
        return StatusOut(
            game_status=g.status,
            game_seconds=e.player_seconds(g.id, p.id) if g.status != "setup" else 0,
            start_time=str(start) if start else None,
            me=me,
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
            handbook=pack.handbook,
            params=list(pack.params),
            checks=[c.name for c in pack.checks],
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

    @r.get("/character/draft")
    def draft(p: Annotated[Player, Depends(require_player)]) -> DraftOut:
        got = e.character_draft(p.id)
        return DraftOut(sheets=got[0], updated_at=got[1]) if got else DraftOut()

    @r.put("/character/draft")
    def save_draft(p: Annotated[Player, Depends(require_player)], body: DraftIn) -> DraftOut:
        """建角表单自动保存：存到服务器，换浏览器、换设备也接得上。"""
        at = e.save_character_draft(p.id, body.sheets)
        return DraftOut(sheets=body.sheets, updated_at=at)

    @r.get("/character")
    def submitted(p: Annotated[Player, Depends(require_player)]) -> list[SheetSubmission]:
        try:
            return e.submitted_character(p.id)
        except Exception:
            return []

    @r.post("/character/preview")
    def preview(p: Annotated[Player, Depends(require_player)], body: PreviewIn) -> PreviewOut:
        pack = e.rulepack(p.game_id)
        clock = e.sheet_clock(p.game_id)  # 按开局时刻算（例如只在某个时段生效的加成）
        try:
            sheet = s.rules.init_sheet(pack, body.template, body.sheet, clock)
        except ValidationFailed as err:
            # 还没填完、算不出数值时，自动获得的条目照样按已经填了的算出来
            try:
                presets = _presets(s.rules, pack, body.template, body.sheet)
            except ValidationFailed:
                presets = {}
            return PreviewOut(
                derived=[],
                problems=[Problem(code=err.code, params=err.params)],
                presets=presets,
                ranges=_ranges(s.rules, pack, body.template, body.sheet),
            )
        problems = s.rules.validate_sheet(pack, body.template, sheet)
        # 别处还没填完也照样算：算得出来的数值都给（例如第二个物品没填完，力量、生命值照样看得到）
        derived: list[DerivedValue] = []
        try:
            derived = s.rules.derive(pack, body.template, sheet, clock)
        except ValidationFailed:
            derived = []
        return PreviewOut(
            derived=derived,
            problems=problems,
            presets=_presets(s.rules, pack, body.template, sheet),
            ranges=_ranges(s.rules, pack, body.template, sheet),
        )

    @r.post("/formula/validate")
    def formula(p: Annotated[Player, Depends(require_player)], body: FormulaIn) -> FormulaOut:
        pack = e.rulepack(p.game_id)
        scope: FormulaScope | None = (
            "config"
            if body.config
            else "script"
            if body.script
            else "bonus"
            if body.bonus
            else "dice"
            if body.dice
            else None
        )
        return FormulaOut(
            problems=s.rules.validate_formula(
                pack, body.template, body.formula, body.in_entry, scope, body.other, body.names
            ),
            names=s.rules.complete_names(pack, body.template, scope),
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
        # 实体 id 换成该玩家的 ref；变更历史不带回合数（玩家看不到回合）
        return [
            v.model_copy(
                update={
                    "entity_id": e.ref_for_entity(p.id, v.entity_id) or "?",
                    "history": tuple(h.model_copy(update={"round_no": 0}) for h in v.history),
                }
            )
            for v in views
        ]

    @r.patch("/handles/{ref}")
    def handle(p: Annotated[Player, Depends(require_player)], ref: str, body: HandleIn) -> OkOut:
        e.rename_handle(p.id, ref, body.label, body.note)
        return OkOut()

    # 角色库：这一局规则书下的角色。打开、更新要密码（设了的话）；猜密码有限速
    library_limit = RateLimiter(limit=10, window=60)

    @r.get("/library")
    def library(p: Annotated[Player, Depends(require_player)]) -> list[LibraryCharacter]:
        return e.library(p.game_id)

    @r.post("/library/{char_id}/open")
    def library_open(
        p: Annotated[Player, Depends(require_player)], char_id: str, body: LibraryOpenIn
    ) -> LibraryCharacterFull:
        if not library_limit.hit(p.id):
            raise HTTPException(status_code=429, detail={"code": "rate.library"})
        return e.library_character(p.game_id, char_id, body.password)

    @r.post("/library")
    def library_new(
        p: Annotated[Player, Depends(require_player)], body: LibrarySaveIn
    ) -> LibraryCharacter:
        return e.save_library_character(
            p.id, body.sheets, name=body.name, summary=body.summary, password=body.password
        )

    @r.put("/library/{char_id}")
    def library_update(
        p: Annotated[Player, Depends(require_player)], char_id: str, body: LibrarySaveIn
    ) -> LibraryCharacter:
        if not library_limit.hit(p.id):
            raise HTTPException(status_code=429, detail={"code": "rate.library"})
        return e.save_library_character(
            p.id,
            body.sheets,
            name=body.name,
            summary=body.summary,
            char_id=char_id,
            password=body.password,
            new_password=body.new_password,
        )

    # 结盟：向某个角色（ref）的玩家提出；对方同意、拒绝；自己撤回或解除
    @r.get("/alliances")
    def alliances(p: Annotated[Player, Depends(require_player)]) -> AllianceView:
        return e.alliance_view(p.game_id, p.id)

    @r.post("/alliances")
    def propose(p: Annotated[Player, Depends(require_player)], body: AllianceIn) -> AllianceView:
        return e.propose_alliance(p.game_id, p.id, body.ref)

    @r.post("/alliances/{item}/answer")
    def answer(
        p: Annotated[Player, Depends(require_player)], item: int, body: AnswerIn
    ) -> AllianceView:
        return e.answer_alliance(p.game_id, p.id, item, body.accept)

    @r.delete("/alliances/{item}")
    def withdraw(p: Annotated[Player, Depends(require_player)], item: int) -> AllianceView:
        return e.withdraw_alliance(p.game_id, p.id, item)

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

    # 每个玩家最近一次的解析结果：确认时按编号取回，玩家改不了 KP 估的耗时
    parsed: dict[str, tuple[str, str, Intent]] = {}
    talk_limit = RateLimiter(limit=30, window=60)

    @r.post("/action/parse")
    def action_parse(p: Annotated[Player, Depends(require_player)], body: TextIn) -> ActionEcho:
        if not chat_limit.hit(p.id):
            raise HTTPException(status_code=429, detail={"code": "rate.kp_chat"})
        intent = e.plan_intent(p.game_id, s.kp.parse_intent(p.id, body.text))
        parse_id = secrets.token_hex(8)
        parsed[p.id] = (parse_id, body.text, intent)
        return echo(e, p.game_id, p.id, body.text, intent, parse_id)

    @r.post("/action")
    def action(
        p: Annotated[Player, Depends(require_player)], body: ActionIn, bg: BackgroundTasks
    ) -> EventOut:
        hit = parsed.get(p.id)
        if hit is None or hit[0] != body.parse_id:
            raise HTTPException(status_code=409, detail={"code": "action.parse_expired"})
        _, text, intent = hit
        intent = intent.model_copy(update={"quotes": tuple(sorted(set(body.quotes)))})
        ev = e.declare_action(p.id, text, intent)
        parsed.pop(p.id, None)
        bg.add_task(background(s.kp.on_action, p.game_id))
        return event_for_player(e, p.id, ev, names(p.game_id))

    def my_reactions(p: Player) -> list[ReactionOut]:
        return [
            ReactionOut(
                seq=x.seq,
                entry=x.entry,
                defender=e.entity_name(p.game_id, x.defender),
                who=x.who,
                checks=list(x.checks),
                labels=x.labels,
                skills=list(x.skills),
            )
            for x in e.reaction_prompts(p.game_id, p.id)
        ]

    @r.get("/reactions")
    def reactions(p: Annotated[Player, Depends(require_player)]) -> list[ReactionOut]:
        """本轮有人攻击我、等我选怎么应对的（没有时限）。"""
        return my_reactions(p)

    @r.post("/reactions")
    def react(
        p: Annotated[Player, Depends(require_player)], body: ReactIn, bg: BackgroundTasks
    ) -> list[ReactionOut]:
        """一次交齐对每次攻击的应对。全都交齐了，本轮接着裁定。"""
        e.react(p.game_id, p.id, body.choices)
        bg.add_task(background(s.kp.on_reaction, p.game_id))
        return my_reactions(p)

    @r.get("/travel")
    def travel(
        p: Annotated[Player, Depends(require_player)], lon: float, lat: float
    ) -> list[TravelOut]:
        """我的每个实体走（或飞）到地图上这一点要多久。"""
        m = e.map_data(p.game_id)
        x, y = to_meters(m.origin.lon, m.origin.lat, lon, lat)
        out: list[TravelOut] = []
        for eid, (secs, fly) in e.travel_times(p.game_id, p.id, Point(x=x, y=y, z=0)).items():
            out.append(
                TravelOut(
                    ref=e.ref_for_entity(p.id, eid) or "?",
                    name=e.entity_name(p.game_id, eid),
                    seconds=secs,
                    fly=fly,
                )
            )
        return out

    # ---------------- 对话模式 ----------------

    def npc_turn(game_id: str, talk_id: str) -> None:
        """KP 替 NPC 回话，按长度延迟出现，模拟打字，玩家分不出对方是不是真人。"""
        started = time.monotonic()

        def typing(text: str) -> None:
            delay = min(25.0, 2.0 + 0.25 * len(text))
            time.sleep(max(0.0, delay - (time.monotonic() - started)))

        s.kp.npc_reply(game_id, talk_id, wait=typing)

    @r.get("/talks")
    def talks(p: Annotated[Player, Depends(require_player)]) -> list[TalkOut]:
        return [
            talk_for_player(e, p.game_id, p.id, t)
            for t in e.talks(p.game_id)
            if p.id in (t.a_player, t.b_player)
        ]

    @r.post("/talks")
    def talk_start(p: Annotated[Player, Depends(require_player)], body: TalkStartIn) -> TalkOut:
        to = e.entity_for_ref(p.id, body.to)
        if body.from_ is not None:
            mine = e.entity_for_ref(p.id, body.from_)
        else:
            idle = e.idle_entities(p.game_id, p.id)
            if not idle:
                raise HTTPException(status_code=409, detail={"code": "talk.busy"})
            mine = idle[0]
        t = e.start_talk(p.id, mine, to)
        return talk_for_player(e, p.game_id, p.id, t)

    @r.post("/talks/{talk_id}/answer")
    def talk_answer(
        p: Annotated[Player, Depends(require_player)],
        talk_id: str,
        body: TalkAnswerIn,
        bg: BackgroundTasks,
    ) -> TalkOut:
        t = e.answer_talk(p.id, talk_id, body.accept)
        if not body.accept:
            bg.add_task(background(s.kp.on_action, p.game_id))
        return talk_for_player(e, p.game_id, p.id, t)

    @r.post("/talks/{talk_id}/say")
    def talk_say(
        p: Annotated[Player, Depends(require_player)],
        talk_id: str,
        body: TextIn,
        bg: BackgroundTasks,
    ) -> TalkOut:
        if not talk_limit.hit(p.id):
            raise HTTPException(status_code=429, detail={"code": "rate.kp_chat"})
        e.say(p.game_id, talk_id, p.id, body.text)
        t = e.talk(p.game_id, talk_id)
        if t.b_player is None:
            bg.add_task(background(npc_turn, p.game_id, talk_id))
        return talk_for_player(e, p.game_id, p.id, t)

    @r.post("/talks/{talk_id}/end")
    def talk_end(
        p: Annotated[Player, Depends(require_player)], talk_id: str, bg: BackgroundTasks
    ) -> TalkOut:
        t = e.end_talk(p.game_id, talk_id, p.id)
        bg.add_task(background(s.kp.on_action, p.game_id))
        return talk_for_player(e, p.game_id, p.id, t)

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
