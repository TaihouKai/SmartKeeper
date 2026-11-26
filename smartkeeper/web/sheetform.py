"""建卡表单用的接口内容：预览、公式检查、角色库的请求体。玩家接口（某一局里建卡）和规则书接口
（不进局、直接在规则书下编辑角色库）共用，只是规则包从哪来不同。"""

from __future__ import annotations

import logging

from fastapi import HTTPException, Response
from pydantic import BaseModel, JsonValue

from smartkeeper.contracts import (
    BudgetUse,
    CopilotAnswer,
    CopilotQuestion,
    DerivedValue,
    FormulaScope,
    LLMError,
    NotFound,
    PackParam,
    Problem,
    RulePack,
    Rules,
    ValidationFailed,
)
from smartkeeper.copilot import Copilot
from smartkeeper.web import sheetpdf

log = logging.getLogger("smartkeeper.web")


class PreviewIn(BaseModel):
    template: str
    sheet: dict[str, JsonValue]


class PreviewOut(BaseModel):
    derived: list[DerivedValue]
    problems: list[Problem]
    presets: dict[str, list[str]] = {}  # 分组名 -> 按当前填写会生效的固定条目名
    # 上下限是公式的字段（例如随出身变的范围）：按当前填写算出来的 [下限, 上限]，算不出的是 null
    ranges: dict[str, list[float | None]] = {}
    # 合计上限（例如属性点）：用了多少、最多多少
    budgets: list[BudgetUse] = []


class PdfSheet(BaseModel):
    template: str
    sheet: JsonValue


class PdfIn(BaseModel):
    """导出 PDF：整套卡（和建卡页上一样，没填完的也行）、界面语言。"""

    sheets: list[PdfSheet]
    lang: str = "zh"


def pdf_response(
    rules: Rules,
    pack: RulePack,
    body: PdfIn,
    clock: dict[str, JsonValue | None],
    messages: dict[str, dict[str, str]],
) -> Response:
    data = sheetpdf.export(
        rules,
        pack,
        [(x.template, x.sheet) for x in body.sheets],
        clock,
        messages,
        "en" if body.lang == "en" else "zh",
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=character.pdf"},
    )


class SheetFormulaIn(BaseModel):
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


class LibraryOpenIn(BaseModel):
    password: str | None = None


class LibrarySaveIn(BaseModel):
    sheets: JsonValue  # 和提交角色卡一样的格式
    name: str = ""  # 空着就用各张卡的角色名
    summary: str = ""
    password: str | None = None  # 新建：要设的密码；更新：原来的密码
    new_password: str | None = None  # 更新时改密码（空字符串是去掉密码）；None 是不改
    author: str = ""  # 不在局里建的：作者写的名字（在局里建的用玩家昵称）


class FormRules(BaseModel):
    """建卡表单要的规则：玩家看得到的模板、要建哪些卡、默认参数、检定名、规则书正文。"""

    world_name: str
    handbook: str
    params: list[PackParam]
    checks: list[str]
    templates: list[dict[str, JsonValue]]
    player_entities: list[dict[str, JsonValue]]


def ask_copilot(
    copilot: Copilot, pack: RulePack, body: CopilotQuestion, game_id: str | None
) -> CopilotAnswer:
    """问建卡助手；模型调用失败时给一个能翻译的错误。"""
    try:
        return copilot.ask(pack, body, game_id)
    except LLMError as err:
        log.warning("copilot failed: %s", err)
        raise HTTPException(
            status_code=502, detail={"code": "copilot.failed", "params": {"reason": err.code}}
        ) from err


def form_rules(pack: RulePack) -> FormRules:
    return FormRules(
        world_name=pack.world.name,
        handbook=pack.handbook,
        params=list(pack.params),
        checks=[c.name for c in pack.checks],
        templates=player_templates(pack),
        player_entities=[x.model_dump(mode="json") for x in pack.player_entities],
    )


def player_templates(pack: RulePack) -> list[dict[str, JsonValue]]:
    """玩家看得到的模板：隐藏的字段、分组、推导值去掉。"""
    out: list[dict[str, JsonValue]] = []
    for t in pack.templates:
        d = t.model_dump(mode="json")
        d["fields"] = [f for f in d["fields"] if not f["hidden"]]
        d["groups"] = [x for x in d["groups"] if not x["hidden"]]
        d["derived"] = [x for x in d["derived"] if not x["hidden"]]
        out.append(d)
    return out


def preview(
    rules: Rules, pack: RulePack, body: PreviewIn, clock: dict[str, JsonValue | None]
) -> PreviewOut:
    """按现在的填写算一遍：数值、问题、会自动获得的条目、随填写变的上下限。clock 是公式里的钟点。"""
    try:
        sheet = rules.init_sheet(pack, body.template, body.sheet, clock)
    except ValidationFailed as err:
        # 还没填完、算不出数值时，自动获得的条目照样按已经填了的算出来
        try:
            presets = _presets(rules, pack, body.template, body.sheet)
        except ValidationFailed:
            presets = {}
        return PreviewOut(
            derived=[],
            problems=[Problem(code=err.code, params=err.params)],
            presets=presets,
            ranges=_ranges(rules, pack, body.template, body.sheet),
            budgets=rules.budgets(pack, body.template, body.sheet),
        )
    problems = rules.validate_sheet(pack, body.template, sheet, creation=True)
    # 别处还没填完也照样算：算得出来的数值都给（例如第二个物品没填完，力量、生命值照样看得到）
    derived: list[DerivedValue] = []
    try:
        derived = rules.derive(pack, body.template, sheet, clock)
    except ValidationFailed:
        derived = []
    return PreviewOut(
        derived=derived,
        problems=problems,
        presets=_presets(rules, pack, body.template, sheet),
        ranges=_ranges(rules, pack, body.template, sheet),
        budgets=rules.budgets(pack, body.template, sheet),
    )


def check_formula(rules: Rules, pack: RulePack, body: SheetFormulaIn) -> FormulaOut:
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
        problems=rules.validate_formula(
            pack, body.template, body.formula, body.in_entry, scope, body.other, body.names
        ),
        names=rules.complete_names(pack, body.template, scope),
    )


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
