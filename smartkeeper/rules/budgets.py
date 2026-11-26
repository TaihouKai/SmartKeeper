"""合计上限（例如属性点）：算一张卡在每一项上用了多少、超没超，以及规则包里的定义写得对不对。

只看建角时填的值（字段原值、条目的列），不看游戏中的临时修正，所以游戏里属性被技能临时拉高也不会“超支”。
"""

from __future__ import annotations

from pydantic import JsonValue

from smartkeeper import lang as f
from smartkeeper.contracts import BudgetDef, BudgetUse, EntityTemplate, Problem
from smartkeeper.rules.evaluator import EntityContext

_EPS = 1e-9


def _num(v: JsonValue) -> float | None:
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    return float(v) if isinstance(v, int | float) else None


def _literal(text: str | None) -> float:
    try:
        return float(text) if text else 0.0
    except ValueError:
        return 0.0


def used(ctx: EntityContext, b: BudgetDef) -> float:
    """这一项现在用了多少：字段的值加上各条目那一列的值（没填的按初值，算不出按 0）。"""
    tpl = ctx.template
    total = 0.0
    for name in b.fields:
        v = _num(ctx.sheet.fields.get(name, None))
        if v is None:
            fd = next((x for x in tpl.fields if x.name == name), None)
            try:
                v = ctx.eval_num(fd.initial) if fd and fd.initial else 0.0
            except f.FormulaError:
                v = 0.0
        total += v
    presets = ctx.active_presets()
    for ref in b.columns:
        gname, _, col = ref.partition(".")
        g = next((x for x in tpl.groups if x.name == gname), None)
        fd = next((x for x in g.fields if x.name == col), None) if g else None
        default = _literal(fd.initial if fd else None)
        for e in (*presets.get(gname, ()), *ctx.sheet.groups.get(gname, ())):
            v = _num(e.fields.get(col))
            total += default if v is None else v
    return total


def active(ctx: EntityContext, b: BudgetDef) -> bool:
    """条件成立（没写条件是成立；算不出来当作不成立）。"""
    if not b.when.strip():
        return True
    try:
        return f.truthy(ctx.eval(b.when))
    except f.FormulaError:
        return False


def limit(ctx: EntityContext, b: BudgetDef) -> float | None:
    """合计最多多少；不限、条件不成立或算不出来时是 None。"""
    if not b.total.strip() or not active(ctx, b):
        return None
    try:
        return ctx.eval_num(b.total)
    except f.FormulaError:
        return None


def uses(ctx: EntityContext) -> list[BudgetUse]:
    return [
        BudgetUse(
            name=b.name,
            label=b.label,
            description=b.description,
            used=round(used(ctx, b), 4),
            total=limit(ctx, b),
            active=active(ctx, b),
        )
        for b in ctx.template.budgets
    ]


def check_sheet(ctx: EntityContext) -> list[Problem]:
    """超过上限的每一项报一个问题（用不完不算问题，界面上会显示剩多少）。"""
    problems: list[Problem] = []
    for u in uses(ctx):
        if u.total is not None and u.used > u.total + _EPS:
            problems.append(
                Problem(
                    code="sheet.budget_over",
                    path=f"budgets.{u.name}",
                    params={"label": u.label or u.name, "used": u.used, "total": u.total},
                )
            )
    return problems


def check_pack(tpl: EntityTemplate, base: str) -> list[Problem]:
    """定义本身：名字不重复，字段是数值字段，“分组.列”存在且是数值列。公式另由规则包校验检查。"""
    problems: list[Problem] = []
    seen: set[str] = set()
    fields = {x.name: x for x in tpl.fields}
    for i, b in enumerate(tpl.budgets):
        path = f"{base}.budgets[{i}]"
        if b.name in seen:
            problems.append(
                Problem(code="pack.duplicate_name", path=f"{path}.name", params={"name": b.name})
            )
        seen.add(b.name)
        for j, name in enumerate(b.fields):
            fd = fields.get(name)
            if fd is None or fd.kind not in ("number", "boolean"):
                problems.append(
                    Problem(
                        code="pack.budget_field", path=f"{path}.fields[{j}]", params={"name": name}
                    )
                )
        for j, ref in enumerate(b.columns):
            gname, _, col = ref.partition(".")
            g = next((x for x in tpl.groups if x.name == gname), None)
            fd = next((x for x in g.fields if x.name == col), None) if g else None
            if fd is None or fd.kind not in ("number", "boolean"):
                problems.append(
                    Problem(
                        code="pack.budget_column", path=f"{path}.columns[{j}]", params={"name": ref}
                    )
                )
        if not b.fields and not b.columns:
            problems.append(Problem(code="pack.budget_empty", path=path))
    return problems
