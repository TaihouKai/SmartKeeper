"""规则包与角色卡的校验。全部返回 Problem 列表，不抛异常。"""

from __future__ import annotations

from collections.abc import Iterable

from pydantic import JsonValue
from pydantic import ValidationError as PydanticError

from smartkeeper.contracts import (
    FLY_FIELD,
    REQUIRED_DERIVED,
    Effect,
    EntityTemplate,
    FieldDef,
    GroupDef,
    GroupEntry,
    Problem,
    RulePack,
    Sheet,
)
from smartkeeper.rules import formula as f
from smartkeeper.rules.evaluator import EntityContext
from smartkeeper.rules.sheets import init_sheet

CHECK_VARS = ("roll", "target", "difficulty", "opp_roll", "opp_target")


def known_names(pack: RulePack, template: EntityTemplate | None) -> set[str]:
    out = {x.name for x in pack.formulas}
    if template is not None:
        out |= {x.name for x in template.fields}
        out |= {x.name for x in template.derived}
    return out


def check_formula(
    pack: RulePack,
    template: EntityTemplate | None,
    text: str,
    path: str,
    *,
    entry_fields: Iterable[str] | None = None,
    extra: Iterable[str] = (),
    dice: bool = False,
) -> list[Problem]:
    try:
        node = f.parse(text)
    except f.FormulaError as e:
        return [Problem(code=e.code, path=path, params={"formula": text, **e.params})]
    problems: list[Problem] = []
    if not dice and f.has_dice(node):
        problems.append(Problem(code="formula.dice_not_allowed", path=path))
    allowed = known_names(pack, template) | set(extra)
    entry = set(entry_fields) if entry_fields is not None else None
    for name in sorted(f.names(node)):
        if name.startswith("self."):
            if entry is None or name[5:] not in entry:
                problems.append(
                    Problem(code="formula.unknown_name", path=path, params={"name": name})
                )
        elif name not in allowed:
            problems.append(_unknown_name(name, allowed, path))
    table_names = {t.name for t in pack.tables}
    for t in sorted(f.tables(node)):
        if t not in table_names:
            problems.append(Problem(code="formula.unknown_table", path=path, params={"name": t}))
    return problems


def _unknown_name(name: str, allowed: set[str], path: str) -> Problem:
    """未知名字；如果它其实是“名字d名字”连写的掷骰，提示在 d 两边加空格。"""
    for i, ch in enumerate(name):
        if ch in "dD" and 0 < i < len(name) - 1:
            a, b = name[:i], name[i + 1 :]
            if (a in allowed or a.isdigit()) and (b in allowed or b.isdigit()):
                return Problem(
                    code="formula.dice_needs_space",
                    path=path,
                    params={"name": name, "fixed": f"{a} d {b}"},
                )
    return Problem(code="formula.unknown_name", path=path, params={"name": name})


def _dupes(names: Iterable[str]) -> set[str]:
    seen: set[str] = set()
    out: set[str] = set()
    for n in names:
        (out if n in seen else seen).add(n)
    return out


def _check_field_def(
    pack: RulePack,
    tpl: EntityTemplate | None,
    fd: FieldDef,
    path: str,
    entry_fields: list[str] | None = None,
) -> list[Problem]:
    problems: list[Problem] = []
    if fd.kind == "param" and entry_fields is None:
        problems.append(Problem(code="pack.param_only_in_group", path=path))
    if fd.choices and fd.kind != "text":
        problems.append(Problem(code="pack.choices_need_text", path=path))
    if (
        fd.cls == "runtime"
        and fd.kind not in ("text", "boolean", "formula", "param")
        and fd.initial is None
    ):
        problems.append(Problem(code="pack.runtime_needs_initial", path=path))
    if fd.kind == "resource" and fd.max is None:
        problems.append(Problem(code="pack.resource_needs_max", path=path))
    for attr in ("min", "max", "initial"):
        text = getattr(fd, attr)
        if text is not None:
            problems += check_formula(pack, tpl, text, f"{path}.{attr}", entry_fields=entry_fields)
    if fd.spends is not None and fd.kind != "param":
        problems.append(Problem(code="pack.spends_needs_param", path=path))
    if fd.spends is not None and tpl is not None:
        target = next((x for x in tpl.fields if x.name == fd.spends), None)
        if target is None or target.kind not in ("number", "resource"):
            problems.append(
                Problem(code="pack.unknown_spend_target", path=path, params={"name": fd.spends})
            )
    return problems


def _check_group(pack: RulePack, tpl: EntityTemplate, g: GroupDef, path: str) -> list[Problem]:
    problems: list[Problem] = []
    for name in _dupes(x.name for x in g.fields):
        problems.append(Problem(code="pack.duplicate_name", path=path, params={"name": name}))
    for i, fd in enumerate(g.fields):
        if fd.cls != "player":
            problems.append(
                Problem(code="pack.group_field_must_be_player", path=f"{path}.fields[{i}]")
            )
        problems += _check_field_def(
            pack, tpl, fd, f"{path}.fields[{i}]", entry_fields=[x.name for x in g.fields]
        )
    if g.max_count is not None and g.max_count < g.min_count:
        problems.append(Problem(code="pack.bad_count", path=path))
    derived = {d.name for d in tpl.derived}
    field_names = [x.name for x in tpl.fields]
    for name in sorted(_dupes(p.name for p in g.presets)):
        problems.append(Problem(code="pack.duplicate_name", path=path, params={"name": name}))
    for i, p in enumerate(g.presets):
        pp = f"{path}.presets[{i}]"
        if p.when.strip():
            # 条件只看这张卡的字段：固定条目会影响推导值，条件再引用推导值就绕成圈了
            problems += check_formula(pack, None, p.when, f"{pp}.when", extra=field_names)
        problems += _check_entry(pack, tpl, g, p, derived, pp, required_fields=False)
    return problems


def _check_template(pack: RulePack, tpl: EntityTemplate, path: str) -> list[Problem]:
    problems: list[Problem] = []
    all_names = (
        [x.name for x in tpl.fields]
        + [x.name for x in tpl.derived]
        + [x.name for x in pack.formulas]
    )
    for name in sorted(_dupes(all_names)):
        problems.append(Problem(code="pack.duplicate_name", path=path, params={"name": name}))
    for name in sorted(_dupes(g.name for g in tpl.groups)):
        problems.append(Problem(code="pack.duplicate_name", path=path, params={"name": name}))
    reserved = set(CHECK_VARS)
    for name in all_names:
        if name in reserved or name in f.FUNCTIONS or "." in name or f.is_die_name(name):
            problems.append(Problem(code="pack.reserved_name", path=path, params={"name": name}))
    derived = {d.name for d in tpl.derived}
    for req in REQUIRED_DERIVED:
        if req not in derived:
            problems.append(
                Problem(code="pack.missing_required_derived", path=path, params={"name": req})
            )
    app = next((x for x in tpl.fields if x.name == tpl.appearance_field), None)
    if app is None or app.kind != "text":
        problems.append(
            Problem(
                code="pack.missing_appearance", path=path, params={"name": tpl.appearance_field}
            )
        )
    fly = next((x for x in tpl.fields if x.name == FLY_FIELD), None)
    if fly is None or fly.kind != "boolean":
        problems.append(Problem(code="pack.missing_can_fly", path=path, params={"name": FLY_FIELD}))
    for i, fd in enumerate(tpl.fields):
        problems += _check_field_def(pack, tpl, fd, f"{path}.fields[{i}]")
    for i, d in enumerate(tpl.derived):
        problems += check_formula(pack, tpl, d.formula, f"{path}.derived[{i}]")
    for i, g in enumerate(tpl.groups):
        problems += _check_group(pack, tpl, g, f"{path}.groups[{i}]")
    problems += _check_cycles(pack, tpl, path)
    return problems


def _refs(text: str) -> set[str]:
    try:
        return set(f.names(f.parse(text)))
    except f.FormulaError:
        return set()  # 语法错误另有报告


def _check_cycles(pack: RulePack, tpl: EntityTemplate, path: str) -> list[Problem]:
    """推导值、命名公式、固定条目的效果之间的循环引用，不用等到算的时候才发现。

    效果公式里引用目标自己的名字表示“到上一步为止的值”，不算循环。
    """
    deps: dict[str, set[str]] = {d.name: _refs(d.formula) for d in tpl.derived}
    for x in pack.formulas:
        deps.setdefault(x.name, set()).update(_refs(x.formula))
    for g in tpl.groups:
        for preset in g.presets:
            for eff in preset.effects:
                if eff.is_mechanical and eff.target in deps:
                    assert eff.formula is not None
                    deps[eff.target] |= _refs(eff.formula) - {eff.target}
    nodes = set(deps)
    graph = {k: sorted(v & nodes) for k, v in deps.items()}
    problems: list[Problem] = []
    seen_cycles: set[frozenset[str]] = set()
    state: dict[str, int] = {}  # 1 = 正在走，2 = 走完了
    stack: list[str] = []

    def visit(n: str) -> None:
        state[n] = 1
        stack.append(n)
        for m in graph[n]:
            if state.get(m) == 1:
                loop = [*stack[stack.index(m) :], m]
                key = frozenset(loop)
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    problems.append(
                        Problem(code="formula.cycle", path=path, params={"name": " -> ".join(loop)})
                    )
            elif m not in state:
                visit(m)
        stack.pop()
        state[n] = 2

    for n in sorted(graph):
        if n not in state:
            visit(n)
    return problems


def validate_pack(pack: RulePack) -> list[Problem]:
    problems: list[Problem] = []
    if not pack.templates:
        problems.append(Problem(code="pack.no_templates", path="templates"))
    for name in sorted(_dupes(t.name for t in pack.templates)):
        problems.append(
            Problem(code="pack.duplicate_name", path="templates", params={"name": name})
        )
    for name in sorted(_dupes(t.name for t in pack.tables)):
        problems.append(Problem(code="pack.duplicate_name", path="tables", params={"name": name}))
    for name in sorted(_dupes(c.name for c in pack.checks)):
        problems.append(Problem(code="pack.duplicate_name", path="checks", params={"name": name}))
    for i, x in enumerate(pack.formulas):
        problems += check_formula(
            pack, None, x.formula, f"formulas[{i}]", extra=all_field_names(pack)
        )
    for i, tpl in enumerate(pack.templates):
        problems += _check_template(pack, tpl, f"templates[{i}]")
    if not pack.player_entities:
        problems.append(Problem(code="pack.no_player_entities", path="player_entities"))
    for i, pe in enumerate(pack.player_entities):
        p = f"player_entities[{i}]"
        if pack.template(pe.template) is None:
            problems.append(
                Problem(code="pack.unknown_template", path=p, params={"name": pe.template})
            )
        if pe.min < 0 or pe.max < max(pe.min, 1):
            problems.append(Problem(code="pack.bad_count", path=p))
    for i, c in enumerate(pack.checks):
        p = f"checks[{i}]"
        problems += check_formula(
            pack, None, c.dice, f"{p}.dice", extra=all_field_names(pack), dice=True
        )
        # 检定的 target 在执行检定的实体上求值，所以允许任意模板的名字
        problems += check_formula(pack, None, c.target, f"{p}.target", extra=all_field_names(pack))
        if not c.levels:
            problems.append(Problem(code="pack.check_needs_levels", path=p))
        for j, lv in enumerate(c.levels):
            problems += check_formula(
                pack, None, lv.condition, f"{p}.levels[{j}]", extra=CHECK_VARS
            )
        if c.opposed_by is not None and pack.check(c.opposed_by) is None:
            problems.append(
                Problem(code="pack.unknown_check", path=p, params={"name": c.opposed_by})
            )
    if problems:
        return problems
    # 结构没问题之后才验算例题，否则错误会重复
    for i in range(len(pack.samples)):
        problems += _check_sample(pack, i)
    return problems


def all_field_names(pack: RulePack) -> set[str]:
    out: set[str] = set()
    for t in pack.templates:
        out |= {x.name for x in t.fields} | {x.name for x in t.derived}
    return out


def _check_sample(pack: RulePack, i: int) -> list[Problem]:
    sample = pack.samples[i]
    path = f"samples[{i}]"
    tpl = pack.template(sample.template)
    if tpl is None:
        return [Problem(code="pack.unknown_template", path=path, params={"name": sample.template})]
    try:
        filled = init_sheet(pack, tpl, sample.sheet)
    except f.FormulaError as e:
        return [Problem(code=e.code, path=path, params=dict(e.params))]
    problems = validate_sheet(pack, tpl, filled)
    if problems:
        return [p.model_copy(update={"path": f"{path}.{p.path}"}) for p in problems]
    ctx = EntityContext(pack, tpl, Sheet.model_validate(filled))
    for name, expected in sorted(sample.expected.items()):
        try:
            got = ctx.derived(name).value
        except f.FormulaError as e:
            problems.append(Problem(code=e.code, path=f"{path}.{name}", params=dict(e.params)))
            continue
        if abs(got - expected) > 1e-6 * max(1.0, abs(expected)):
            problems.append(
                Problem(
                    code="pack.sample_mismatch",
                    path=f"{path}.{name}",
                    params={"expected": expected, "got": got},
                )
            )
    return problems


# ---------------- 角色卡 ----------------


def _check_value(
    ctx: EntityContext | None,
    fd: FieldDef,
    value: JsonValue,
    path: str,
) -> list[Problem]:
    if fd.kind == "boolean":
        if not isinstance(value, bool):
            return [Problem(code="sheet.type", path=path, params={"expected": "boolean"})]
        return []
    if fd.kind == "formula":
        if not isinstance(value, str):
            return [Problem(code="sheet.type", path=path, params={"expected": "formula"})]
        if fd.required and fd.cls == "player" and not value.strip():
            return [Problem(code="sheet.required", path=path)]
        return []  # 公式本身由 _check_formula_fields 按模板和条目校验
    if fd.kind == "text":
        if not isinstance(value, str):
            return [Problem(code="sheet.type", path=path, params={"expected": "text"})]
        if fd.choices and value not in fd.choices:
            return [Problem(code="sheet.choice", path=path, params={"value": value})]
        if fd.required and fd.cls == "player" and not value.strip():
            return [Problem(code="sheet.required", path=path)]
        return []
    if isinstance(value, bool) or not isinstance(value, int | float):
        return [Problem(code="sheet.type", path=path, params={"expected": "number"})]
    if ctx is None:
        return []
    problems: list[Problem] = []
    try:
        if fd.min is not None and value < ctx.eval_num(fd.min):
            problems.append(
                Problem(
                    code="sheet.below_min",
                    path=path,
                    params={"value": value, "min": ctx.eval_num(fd.min)},
                )
            )
        if fd.max is not None and value > ctx.eval_num(fd.max):
            problems.append(
                Problem(
                    code="sheet.above_max",
                    path=path,
                    params={"value": value, "max": ctx.eval_num(fd.max)},
                )
            )
    except f.FormulaError as e:
        problems.append(Problem(code=e.code, path=path, params=dict(e.params)))
    return problems


def validate_sheet(pack: RulePack, tpl: EntityTemplate, raw: JsonValue) -> list[Problem]:
    try:
        sheet = Sheet.model_validate(raw)
    except PydanticError as e:
        return [
            Problem(
                code="sheet.malformed",
                path=".".join(str(x) for x in err["loc"]),
                params={"msg": err["type"]},
            )
            for err in e.errors()
        ]
    problems: list[Problem] = []
    if not sheet.name.strip():
        problems.append(Problem(code="sheet.required", path="name"))
    fields = {x.name: x for x in tpl.fields}
    derived = {x.name for x in tpl.derived}
    for name in sorted(sheet.fields):
        if name in derived:
            problems.append(Problem(code="sheet.derived_not_writable", path=f"fields.{name}"))
        elif name not in fields:
            problems.append(Problem(code="sheet.unknown_field", path=f"fields.{name}"))
    for name, fd in fields.items():
        if name not in sheet.fields and (fd.required or fd.cls == "runtime"):
            problems.append(Problem(code="sheet.missing_field", path=f"fields.{name}"))
    groups = {g.name: g for g in tpl.groups}
    for gname in sorted(sheet.groups):
        if gname not in groups:
            problems.append(Problem(code="sheet.unknown_group", path=f"groups.{gname}"))
    # 先在没有上下文的情况下检查类型，类型都对了才能求值上下限
    for name, fd in fields.items():
        if name in sheet.fields:
            problems += _check_value(None, fd, sheet.fields[name], f"fields.{name}")
    problems += _check_formula_fields(pack, tpl, tpl.fields, sheet.fields, "", in_entry=False)
    for g in groups.values():
        problems += _check_group_entries(pack, tpl, g, sheet, derived)
    problems += _check_priorities(sheet)
    for i, st in enumerate(sheet.statuses):
        if st.modifier is not None:
            problems += _check_effect(
                pack, tpl, st.modifier, None, derived, f"statuses[{i}].modifier"
            )
    if problems:
        return problems
    ctx = EntityContext(pack, tpl, sheet)
    for name, fd in fields.items():
        if name in sheet.fields:
            problems += _check_value(ctx, fd, sheet.fields[name], f"fields.{name}")
    if problems:
        return problems
    for d in tpl.derived:
        try:
            ctx.derived(d.name)
        except f.FormulaError as e:
            problems.append(Problem(code=e.code, path=f"derived.{d.name}", params=dict(e.params)))
    return problems


def _check_group_entries(
    pack: RulePack, tpl: EntityTemplate, g: GroupDef, sheet: Sheet, derived: set[str]
) -> list[Problem]:
    entries = sheet.groups.get(g.name, ())
    path = f"groups.{g.name}"
    problems: list[Problem] = []
    if len(entries) < g.min_count or (g.max_count is not None and len(entries) > g.max_count):
        problems.append(
            Problem(code="sheet.group_count", path=path, params={"count": len(entries)})
        )
    for i, entry in enumerate(entries):
        problems += _check_entry(pack, tpl, g, entry, derived, f"{path}[{i}]")
    return problems


def _check_formula_fields(
    pack: RulePack,
    tpl: EntityTemplate,
    defs: Iterable[FieldDef],
    values: dict[str, JsonValue],
    base: str,
    *,
    in_entry: bool,
) -> list[Problem]:
    """掷骰公式字段的值：语法、引用的名字（条目里可以用 self.<字段>），允许掷骰。"""
    defs = list(defs)
    entry_fields = [x.name for x in defs] if in_entry else None
    problems: list[Problem] = []
    for fd in defs:
        v = values.get(fd.name)
        if fd.kind != "formula" or not isinstance(v, str) or not v.strip():
            continue
        path = f"{base}.fields.{fd.name}" if base else f"fields.{fd.name}"
        problems += check_formula(pack, tpl, v, path, entry_fields=entry_fields, dice=True)
    return problems


def _check_priorities(sheet: Sheet) -> list[Problem]:
    """玩家写的带公式的效果必须有 priority，同一张卡上不能重复。"""
    problems: list[Problem] = []
    seen: dict[int, str] = {}
    for gname, entries in sorted(sheet.groups.items()):
        for i, entry in enumerate(entries):
            for j, eff in enumerate(entry.effects):
                if not eff.is_mechanical:
                    continue
                path = f"groups.{gname}[{i}].effects[{j}].priority"
                if eff.priority is None:
                    problems.append(Problem(code="sheet.effect_priority_missing", path=path))
                elif eff.priority in seen:
                    problems.append(
                        Problem(
                            code="sheet.effect_priority_duplicate",
                            path=path,
                            params={"priority": eff.priority, "other": seen[eff.priority]},
                        )
                    )
                else:
                    seen[eff.priority] = entry.name
    return problems


def _check_entry(
    pack: RulePack,
    tpl: EntityTemplate,
    g: GroupDef,
    entry: GroupEntry,
    derived: set[str],
    ep: str,
    *,
    required_fields: bool = True,
) -> list[Problem]:
    """一个条目：玩家写的，或规则包里的固定条目（固定条目的字段可以留空）。"""
    problems: list[Problem] = []
    fdefs = {x.name: x for x in g.fields}
    if not entry.name.strip():
        problems.append(Problem(code="sheet.required", path=f"{ep}.name"))
    for name in sorted(entry.fields):
        if name not in fdefs:
            problems.append(Problem(code="sheet.unknown_field", path=f"{ep}.fields.{name}"))
    for name, fd in fdefs.items():
        if name in entry.fields:
            problems += _check_value(None, fd, entry.fields[name], f"{ep}.fields.{name}")
        elif fd.required and required_fields and fd.kind != "param":
            problems.append(Problem(code="sheet.missing_field", path=f"{ep}.fields.{name}"))
    problems += _check_formula_fields(pack, tpl, g.fields, entry.fields, ep, in_entry=True)
    if entry.effects and not g.effects:
        problems.append(Problem(code="sheet.effects_not_allowed", path=ep))
    for j, eff in enumerate(entry.effects):
        problems += _check_effect(pack, tpl, eff, fdefs, derived, f"{ep}.effects[{j}]")
    if entry.placement is not None:
        if not g.placements:
            problems.append(Problem(code="sheet.placement_not_allowed", path=f"{ep}.placement"))
        spec = entry.placement
        for attr in ("radius", "perceive_multiplier", "charges", "duration"):
            text = str(getattr(spec, attr))
            if attr == "radius" or text.strip():
                problems += check_formula(
                    pack, tpl, text, f"{ep}.placement.{attr}", entry_fields=list(fdefs)
                )
    if entry.shape is not None and entry.shape.kind not in g.shapes.allowed:
        problems.append(Problem(code="sheet.shape_not_allowed", path=f"{ep}.shape"))
    return problems


def _check_effect(
    pack: RulePack,
    tpl: EntityTemplate,
    eff: Effect,
    entry_fields: dict[str, FieldDef] | None,
    derived: set[str],
    path: str,
) -> list[Problem]:
    if eff.target is None and eff.formula is None:
        if not eff.description.strip():
            return [Problem(code="sheet.effect_empty", path=path)]
        return []
    if eff.target is None or eff.formula is None:
        return [Problem(code="sheet.effect_incomplete", path=path)]
    problems: list[Problem] = []
    if eff.target not in derived:
        problems.append(Problem(code="sheet.effect_target", path=path, params={"name": eff.target}))
    problems += check_formula(
        pack,
        tpl,
        eff.formula,
        f"{path}.formula",
        entry_fields=list(entry_fields) if entry_fields is not None else None,
    )
    return problems
