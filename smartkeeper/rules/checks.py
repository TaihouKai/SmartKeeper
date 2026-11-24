"""检定结算：引擎掷骰，这里按规则包里的成功条件算出结果等级。"""

from __future__ import annotations

import math
from collections.abc import Mapping

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import (
    CheckResult,
    CheckSpec,
    DiceResult,
    NotFound,
    Peers,
    RulePack,
    Sheet,
    ValidationFailed,
)
from smartkeeper.rules import checkconfig
from smartkeeper.rules.evaluator import EntityContext, table_lookup


def context(
    pack: RulePack, template: str, sheet: JsonValue, peers: Peers | None = None
) -> EntityContext:
    tpl = pack.template(template)
    if tpl is None:
        raise NotFound("rules.unknown_template", name=template)
    return EntityContext(pack, tpl, Sheet.model_validate(sheet), peers=peers or {})


def resolve_check(
    pack: RulePack,
    *,
    entity: str,
    template: str,
    sheet: JsonValue,
    check: str,
    roll: DiceResult,
    difficulty: float | None,
    opponent: tuple[str, str, JsonValue, DiceResult] | None,
    peers: Peers | None = None,
    opp_check: str | None = None,
    distance: float = 0.0,
    vs_template: str = "",
) -> CheckResult:
    """算这次检定的等级。对抗时（opponent）对方按自己的检定（opp_check，默认 opposed_by，再默认同一个）
    另算一个等级 opp_level，难度只算在发起的一方。vs_template 是没有对抗时对象的模板（opponent.template）。"""
    cdef = spec(pack, check)
    try:
        target = context(pack, template, sheet, peers).eval_num(cdef.target)
        variables: dict[str, f.Value] = {
            "roll": float(roll.total),
            # 骰子本身掷出的点数（不含加值）：natural == 20
            "natural": float(sum(roll.rolls)),
            "target": target,
            "difficulty": float(difficulty) if difficulty is not None else 0.0,
            "distance": float(distance),
            "opp_roll": 0.0,
            "opp_target": 0.0,
            "self.template": template,
            "opponent.template": vs_template,
        }
        opp_target: float | None = None
        opp_level: int | None = None
        if opponent is not None:
            _opp_id, opp_tpl, opp_sheet, opp_roll = opponent
            odef = spec(pack, opp_check or cdef.opposed_by or check)
            opp_target = context(pack, opp_tpl, opp_sheet).eval_num(odef.target)
            variables["opp_roll"] = float(opp_roll.total)
            variables["opp_target"] = opp_target
            variables["opponent.template"] = opp_tpl
            theirs: dict[str, f.Value] = {
                **variables,
                "roll": float(opp_roll.total),
                "natural": float(sum(opp_roll.rolls)),
                "target": opp_target,
                "difficulty": 0.0,
                "opp_roll": float(roll.total),
                "opp_target": target,
                "self.template": opp_tpl,
                "opponent.template": template,
            }
            opp_level = _level(odef, theirs)
        level = _level(cdef, variables)
    except f.FormulaError as e:
        raise ValidationFailed(e.code, **e.params) from e
    return CheckResult(
        entity=entity,
        check=check,
        roll=roll,
        target=target,
        difficulty=difficulty,
        opponent=opponent[0] if opponent else None,
        opp_roll=opponent[3] if opponent else None,
        opp_target=opp_target,
        level=level,
        level_name=level_name(cdef, level),
        opp_level=opp_level,
    )


def _level(cdef: CheckSpec, variables: dict[str, f.Value]) -> int:
    """检定代码的等级：写了 level 用它（取整），否则 success 成立是 1、不成立是 0。"""
    if cdef.level.strip():
        v = f.evaluate(f.parse(cdef.level), _vars(variables), _no_tables)
        if isinstance(v, str):
            raise f.FormulaError("formula.text_result", value=v)
        return math.floor(v)
    return 1 if f.truthy(f.evaluate(f.parse(cdef.success), _vars(variables), _no_tables)) else 0


def level_name(cdef: CheckSpec, level: int) -> str:
    if not cdef.levels:
        return ""
    return cdef.levels[max(0, min(level, len(cdef.levels) - 1))]


def _vars(variables: dict[str, f.Value]) -> f.Resolver:
    def resolve(name: str) -> f.Value:
        if name not in variables:
            raise f.FormulaError("formula.unknown_name", name=name)
        return variables[name]

    return resolve


def _no_tables(name: str, key: f.Value) -> float:
    raise f.FormulaError("formula.unknown_table", name=name)


def roll(
    pack: RulePack,
    expr: str,
    faces: f.Faces,
    template: str | None = None,
    sheet: JsonValue = None,
    entry: dict[str, JsonValue] | None = None,
    peers: Peers | None = None,
    target: tuple[str, JsonValue, Peers | None] | None = None,
    extra: Mapping[str, float] | None = None,
) -> DiceResult:
    rolls: list[int] = []

    def record(count: int, sides: int) -> tuple[int, ...]:
        got = faces(count, sides)
        rolls.extend(got)
        return got

    try:
        if template is not None:
            ctx = context(pack, template, sheet, peers)
            if target is not None:
                ctx.target = context(pack, target[0], target[1], target[2])
            node = ctx.prepare(expr, entry)
            resolve = ctx.resolver(entry, extra)
            collect: f.Collect | None = ctx.collect
        else:
            node = f.parse(expr)
            resolve = _vars(dict(extra or {}))
            collect = None
        v = f.evaluate(node, resolve, table_lookup(pack), record, collect)
        if isinstance(v, str):
            raise f.FormulaError("formula.text_result", value=v)
    except f.FormulaError as e:
        raise ValidationFailed(e.code, formula=expr, **e.params) from e
    return DiceResult(expr=expr.strip(), rolls=tuple(rolls), total=v)


def spec(pack: RulePack, check: str) -> CheckSpec:
    """规则包里一个检定的内容。没有这个检定抛 NotFound；代码写错抛 ValidationFailed。"""
    cdef = pack.check(check)
    if cdef is None:
        raise NotFound("rules.unknown_check", name=check)
    try:
        return checkconfig.read_check(cdef.config)
    except f.FormulaError as e:
        raise ValidationFailed(e.code, **e.params) from e


def check_dice(pack: RulePack, check: str) -> str:
    return spec(pack, check).dice
