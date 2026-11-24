"""检定结算：引擎掷骰，这里按规则包里的成功条件算出结果等级。"""

from __future__ import annotations

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import (
    CheckResult,
    DiceResult,
    NotFound,
    Peers,
    RulePack,
    Sheet,
    ValidationFailed,
)
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
) -> CheckResult:
    cdef = pack.check(check)
    if cdef is None:
        raise NotFound("rules.unknown_check", name=check)
    try:
        target = context(pack, template, sheet, peers).eval_num(cdef.target)
        variables: dict[str, f.Value] = {
            "roll": float(roll.total),
            "target": target,
            "difficulty": float(difficulty) if difficulty is not None else 0.0,
            "opp_roll": 0.0,
            "opp_target": 0.0,
        }
        opp_target: float | None = None
        if opponent is not None:
            opp_id, opp_tpl, opp_sheet, opp_roll = opponent
            del opp_id
            opp_check = pack.check(cdef.opposed_by or cdef.name)
            assert opp_check is not None
            opp_target = context(pack, opp_tpl, opp_sheet).eval_num(opp_check.target)
            variables["opp_roll"] = float(opp_roll.total)
            variables["opp_target"] = opp_target
        level = None
        for lv in cdef.levels:
            v = f.evaluate(f.parse(lv.condition), _vars(variables), _no_tables)
            if v != 0 and v != 0.0 and v != "":
                level = lv.name
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
        level=level or cdef.levels[-1].name,
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


def check_dice(pack: RulePack, check: str) -> str:
    cdef = pack.check(check)
    if cdef is None:
        raise NotFound("rules.unknown_check", name=check)
    return cdef.dice
