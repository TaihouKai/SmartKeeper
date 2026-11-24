"""检定结算：引擎掷骰，这里按规则包里的成功条件算出结果等级。"""

from __future__ import annotations

from typing import cast

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import (
    CheckLevel,
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
) -> CheckResult:
    cdef = spec(pack, check)
    try:
        target = context(pack, template, sheet, peers).eval_num(cdef.target)
        variables: dict[str, f.Value] = {
            "roll": float(roll.total),
            # 骰子本身掷出的点数（不含加值），大成功、大失败常用：natural == 20
            "natural": float(sum(roll.rolls)),
            "target": target,
            "difficulty": float(difficulty) if difficulty is not None else 0.0,
            "opp_roll": 0.0,
            "opp_target": 0.0,
        }
        opp_target: float | None = None
        if opponent is not None:
            opp_id, opp_tpl, opp_sheet, opp_roll = opponent
            del opp_id
            odef = spec(pack, opp_check or cdef.opposed_by or check)
            opp_target = context(pack, opp_tpl, opp_sheet).eval_num(odef.target)
            variables["opp_roll"] = float(opp_roll.total)
            variables["opp_target"] = opp_target
            if difficulty is None:
                # 对抗：难度就是对方的点数，同一条 roll > difficulty 两种情况都能用
                variables["difficulty"] = float(opp_roll.total)
        level: CheckLevel = "failure"
        for name, cond in (
            ("critical_success", cdef.critical_success),
            ("critical_failure", cdef.critical_failure),
            ("success", cdef.success),
        ):
            if cond.strip() and f.truthy(f.evaluate(f.parse(cond), _vars(variables), _no_tables)):
                level = cast(CheckLevel, name)
                break
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
    )


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
            resolve = ctx.resolver(entry)
            collect: f.Collect | None = ctx.collect
        else:
            node = f.parse(expr)
            resolve = _vars({})
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
