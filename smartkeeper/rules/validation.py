"""规则包与角色卡的校验。全部返回 Problem 列表，不抛异常。"""

from __future__ import annotations

import keyword
import re
from collections.abc import Iterable

from pydantic import JsonValue
from pydantic import ValidationError as PydanticError

from smartkeeper import lang as f
from smartkeeper.contracts import (
    FLY_FIELD,
    HP_FIELD,
    REQUIRED_DERIVED,
    Effect,
    EntityTemplate,
    FieldDef,
    GroupDef,
    GroupEntry,
    Peers,
    Problem,
    RulePack,
    Sheet,
)
from smartkeeper.rules import checkconfig, skillconfig
from smartkeeper.rules.evaluator import EntityContext
from smartkeeper.rules.sheets import init_sheet

CHECK_VARS = ("roll", "natural", "target", "difficulty", "opp_roll", "opp_target")
_ID = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
RESERVED_IDS = {"self", "this", "target", "template"}


def _keyword(name: str) -> bool:
    """Python 的关键字（if、and、class……）不能当名字：公式用 Python 的语法读。"""
    return keyword.iskeyword(name)


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
        ref = name
        if name.startswith("self.") and template is not None:
            ref = f"{template.name}.{name[5:]}"  # self.x：自己的，和写自己的模板名一样
        if "." in name and not name.startswith("this."):
            bad = _check_dotted(pack, ref, set(extra))
            if bad:
                problems.append(Problem(code=bad, path=path, params={"name": name}))
            continue
        if name.startswith("this."):
            if entry is None or name[5:] not in entry:
                problems.append(
                    Problem(code="formula.unknown_name", path=path, params={"name": name})
                )
        elif name not in allowed:
            problems.append(_unknown_name(name, allowed, path))
    for ref in sorted(f.lists(node)):
        bad = _check_list(pack, template, ref)
        if bad:
            problems.append(Problem(code=bad, path=path, params={"name": ref}))
    table_names = {t.name for t in pack.tables}
    for t in sorted(f.tables(node)):
        if t not in table_names:
            problems.append(Problem(code="formula.unknown_table", path=path, params={"name": t}))
    return problems


def check_script(
    pack: RulePack,
    template: EntityTemplate,
    text: str,
    path: str,
    entry_fields: list[str],
    config: str = "",
) -> list[Problem]:
    """技能脚本：语法，每句的字段是不是能改的值，参数公式里的名字。问题的 params 里带 line。"""
    try:
        nodes = f.parse_script(text)
    except f.FormulaError as e:
        return [Problem(code=e.code, path=path, params={"formula": text, **e.params})]
    # 对象可以是任何模板的角色，所以字段在任何一个模板里有就行
    runtime = {
        x.name
        for t in pack.templates
        for x in t.fields
        if x.cls == "runtime" and x.kind in ("number", "resource")
    }
    derived = {d.name for t in pack.templates for d in t.derived}
    problems: list[Problem] = []

    def at(line: int, found: list[Problem]) -> None:
        problems.extend(p.model_copy(update={"params": {**p.params, "line": line}}) for p in found)

    # 到这一句为止定义过的局部变量；设置的各项在哪里都能用
    settings = [n for n in skillconfig.names(config, "") if n in skillconfig.KEYS]
    defined: list[str] = [*settings, "result", "reacting"]
    for n in nodes:
        if isinstance(n, f.Let) and n.name in skillconfig.KEYS:
            at(n.line, [Problem(code="script.setting_name", path=path, params={"name": n.name})])

    def walk(body: tuple[f.ScriptNode, ...]) -> None:
        for node in body:
            if isinstance(node, f.Let):
                # 局部变量不掷骰（掷出来的点数没处记）；之后的句子可以用它
                at(
                    node.line,
                    check_formula(
                        pack, template, node.value, path, entry_fields=entry_fields, extra=defined
                    ),
                )
                defined.append(node.name)
                continue
            if isinstance(node, f.If):
                for b in node.branches:
                    if b.condition is not None:
                        # 条件在声明使用时算，不掷骰（掷出来的点数没处记）
                        at(
                            b.line,
                            check_formula(
                                pack,
                                template,
                                b.condition,
                                path,
                                entry_fields=entry_fields,
                                extra=defined,
                            ),
                        )
                    walk(b.body)
                continue
            st = node
            found: list[Problem] = []
            if st.verb in ("add", "sub", "set") and st.field not in runtime:
                found.append(
                    Problem(code="script.not_runtime", path=path, params={"name": st.field})
                )
            if st.verb == "modify" and st.field not in derived:
                found.append(
                    Problem(code="script.not_derived", path=path, params={"name": st.field})
                )
            for arg in (st.amount, st.minutes):
                if arg is not None:
                    found += check_formula(
                        pack,
                        template,
                        arg,
                        path,
                        entry_fields=entry_fields,
                        extra=defined,
                        dice=True,
                    )
            if st.formula is not None and st.field is not None:
                # 被修正的推导值自己的名字指带着这条修正的角色的值，其余名字取使用者
                found += check_formula(
                    pack,
                    template,
                    st.formula,
                    path,
                    entry_fields=entry_fields,
                    extra=[st.field, *defined],
                )
            at(st.line, found)

    walk(nodes)
    return problems


def check_config(
    pack: RulePack,
    template: EntityTemplate,
    g: GroupDef | None,
    text: str,
    path: str,
    entry_fields: list[str],
    script: str = "",
) -> list[Problem]:
    """技能设置：名字和值的类型、分组允不允许（范围形状、设置物、施放时间和冷却），各个公式。问题带 line。"""
    try:
        cfg = skillconfig.read_config(text, script)
    except f.FormulaError as e:
        return [Problem(code=e.code, path=path, params={"formula": text, **e.params})]
    problems: list[Problem] = []
    for line, _name, formula in skillconfig.formulas(text, script):
        found = check_formula(pack, template, formula, path, entry_fields=entry_fields)
        problems += [p.model_copy(update={"params": {**p.params, "line": line}}) for p in found]
    if g is not None:
        settings = {s.name: s.line for s in skillconfig.settings(text, script)}

        def off(name: str, code: str) -> None:
            problems.append(
                Problem(
                    code=code,
                    path=path,
                    params={"name": name, "line": settings.get(name, 1)},
                )
            )

        if cfg.shape is not None and cfg.shape.kind not in g.shapes.allowed:
            off("shape", "sheet.shape_not_allowed")
        if cfg.placement is not None and not g.placements:
            off("placement", "sheet.placement_not_allowed")
        for name in [x for x in (cfg.check, *cfg.reactions) if x]:
            if pack.check(name) is None:
                key = "check" if name == cfg.check else "reactions"
                problems.append(
                    Problem(
                        code="config.unknown_check",
                        path=path,
                        params={"name": name, "line": settings.get(key, 1)},
                    )
                )
        if (cfg.cast_time.strip() or cfg.cooldown.strip()) and not g.timing:
            off("cast_time" if cfg.cast_time.strip() else "cooldown", "sheet.timing_not_allowed")
    return problems


def preset_ids(tpl: EntityTemplate) -> dict[str, list[str]]:
    """模板里固定条目的 ID -> 那个分组里可以引用的列（“使用时填写”的列不能引用）。"""
    out: dict[str, list[str]] = {}
    for g in tpl.groups:
        cols = [x.name for x in g.fields if x.kind != "param"]
        for p in g.presets:
            if p.id:
                out[p.id] = cols
    return out


def _check_dotted(pack: RulePack, name: str, extra: set[str]) -> str | None:
    """<模板>.x / <模板>.<条目ID>.<列> / target.x 的名字是否说得通。返回问题代码。"""
    head, *rest = name.split(".")
    if not rest or len(rest) > 2:
        return "formula.unknown_name"
    if head == "target":
        templates = list(pack.templates)
    else:
        tpl = pack.template(head)
        if tpl is None:
            return "formula.unknown_name"
        templates = [tpl]
    if rest == ["template"]:
        return None
    for tpl in templates:
        plain = known_names(pack, tpl)
        ids = preset_ids(tpl)
        if len(rest) == 1 and (rest[0] in plain or rest[0] in ids or rest[0] in extra):
            return None
        if len(rest) == 2:
            if rest[0] in ids and rest[1] in ids[rest[0]]:
                return None
            if rest[0] in extra:
                return None  # 这张卡上玩家写的条目：列在求值时再看
            group_cols = {c for g in tpl.groups for c in [x.name for x in g.fields]}
            if rest[0] in ids and rest[1] in group_cols:
                return "formula.param_not_referenceable"
    return "formula.unknown_name"


def _check_list(pack: RulePack, template: EntityTemplate | None, ref: str) -> str | None:
    """count/sum 的分组引用：[<模板>. 或 target.]分组[.列]。"""
    head, *rest = ref.split(".")
    if head == "target":
        templates = list(pack.templates)
    elif pack.template(head) is not None:
        templates = [t for t in [pack.template(head)] if t is not None]
    else:
        templates = [template] if template is not None else list(pack.templates)
        rest = [head, *rest]
    if not rest or len(rest) > 2:
        return "formula.unknown_group"
    for tpl in templates:
        g = next((x for x in tpl.groups if x.name == rest[0]), None)
        if g is None:
            continue
        if len(rest) == 1:
            return None
        col = next((x for x in g.fields if x.name == rest[1]), None)
        if col is not None:
            return "formula.param_not_referenceable" if col.kind == "param" else None
    return "formula.unknown_group"


def _unknown_name(name: str, allowed: set[str], path: str) -> Problem:
    """未知名字；如果它其实是“名字d名字”连写的掷骰，提示在 d 两边加空格。"""
    for i, ch in enumerate(name):
        if ch in "dD" and 0 < i < len(name) - 1:
            a, b = name[:i], name[i + 1 :]
            if (a in allowed or a.isdigit()) and (b in allowed or b.isdigit()):
                return Problem(
                    code="formula.dice_needs_space",
                    path=path,
                    params={"name": name, "fixed": f"dice({a}, {b})"},
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
    for attr in ("min", "max", "initial"):
        text = getattr(fd, attr)
        if text is not None:
            problems += check_formula(pack, tpl, text, f"{path}.{attr}", entry_fields=entry_fields)
    if fd.kind == "boolean" and fd.initial is not None and fd.initial.strip():
        # 是/否的初值：True / False、0 / 1 或一个条件；别的数字和文字多半是填错了
        try:
            node = f.parse(fd.initial)
        except f.FormulaError:
            node = None
        if isinstance(node, f.Str) or (isinstance(node, f.Num) and node.value not in (0.0, 1.0)):
            problems.append(
                Problem(
                    code="pack.boolean_initial",
                    path=f"{path}.initial",
                    params={"value": fd.initial},
                )
            )
    if fd.vital and (fd.cls != "runtime" or fd.kind not in ("number", "resource")):
        problems.append(Problem(code="pack.vital_needs_runtime", path=path))
    if fd.per_minute is not None:
        if fd.cls != "runtime" or fd.kind not in ("number", "resource"):
            problems.append(Problem(code="pack.per_minute_needs_runtime", path=path))
        problems += check_formula(pack, tpl, fd.per_minute, f"{path}.per_minute")
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
    for pid in sorted(_dupes(p.id for g2 in tpl.groups for p in g2.presets if p.id)):
        problems.append(Problem(code="pack.duplicate_name", path=path, params={"name": pid}))
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
    for name in [tpl.name, *(g.name for g in tpl.groups)]:
        if _keyword(name):
            problems.append(Problem(code="pack.reserved_name", path=path, params={"name": name}))
    reserved = set(CHECK_VARS)
    for name in all_names:
        if (
            name in reserved
            or name in f.FUNCTIONS
            or "." in name
            or f.is_die_name(name)
            or _keyword(name)
        ):
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
    hp = next((x for x in tpl.fields if x.name == HP_FIELD), None)
    if hp is None or hp.kind not in ("number", "resource") or hp.cls != "runtime":
        problems.append(Problem(code="pack.missing_hp", path=path, params={"name": HP_FIELD}))
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
        problems += check_check(pack, c.config, f"{p}.config")
    if problems:
        return problems
    # 结构没问题之后才验算例题，否则错误会重复
    for i in range(len(pack.samples)):
        problems += _check_sample(pack, i)
    return problems


def check_check(pack: RulePack, text: str, path: str) -> list[Problem]:
    """一个检定的代码：名字和值的类型、骰子（可以掷骰）、目标值、三个结果条件（用 roll、natural……）、对抗检定。"""
    try:
        spec = checkconfig.read_check(text)
    except f.FormulaError as e:
        return [Problem(code=e.code, path=path, params={"formula": text, **e.params})]
    lines = checkconfig.lines(text)
    problems: list[Problem] = []

    def at(key: str, found: list[Problem]) -> None:
        line = lines.get(key, 1)
        problems.extend(p.model_copy(update={"params": {**p.params, "line": line}}) for p in found)

    fields = all_field_names(pack)
    if not spec.dice.strip():
        at("dice", [Problem(code="pack.check_needs_dice", path=path)])
    else:
        at("dice", check_formula(pack, None, spec.dice, path, extra=fields, dice=True))
    at("target", check_formula(pack, None, spec.target, path, extra=fields))
    if not spec.success.strip():
        at("success", [Problem(code="pack.check_needs_success", path=path)])
    for key in ("critical_success", "success", "critical_failure"):
        cond = str(getattr(spec, key))
        if cond.strip():
            at(key, check_formula(pack, None, cond, path, extra=checkconfig.VARS))
    if spec.opposed_by and pack.check(spec.opposed_by) is None:
        at(
            "opposed_by",
            [Problem(code="pack.unknown_check", path=path, params={"name": spec.opposed_by})],
        )
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


def validate_sheet(
    pack: RulePack, tpl: EntityTemplate, raw: JsonValue, peers: Peers | None = None
) -> list[Problem]:
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
    own_ids = [e.id for entries in sheet.groups.values() for e in entries if e.id]
    for eid in sorted(_dupes([*own_ids, *preset_ids(tpl)])):
        problems.append(Problem(code="sheet.duplicate_entry_id", path="groups", params={"id": eid}))
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
    ctx = EntityContext(pack, tpl, sheet, peers=peers or {})
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
    """掷骰公式字段的值：语法、引用的名字（条目里可以用 this.<字段>），允许掷骰。"""
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
    if entry.id and (not _ID.fullmatch(entry.id) or entry.id in RESERVED_IDS or _keyword(entry.id)):
        problems.append(
            Problem(code="sheet.bad_entry_id", path=f"{ep}.id", params={"id": entry.id})
        )
    elif entry.id and entry.id in known_names(pack, tpl) | {t.name for t in pack.templates}:
        problems.append(
            Problem(code="sheet.entry_id_clash", path=f"{ep}.id", params={"id": entry.id})
        )
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
    if entry.script.strip():
        problems += check_script(pack, tpl, entry.script, f"{ep}.script", list(fdefs), entry.config)
    for j, eff in enumerate(entry.effects):
        problems += _check_effect(pack, tpl, eff, fdefs, derived, f"{ep}.effects[{j}]")
    if entry.config.strip():
        problems += check_config(
            pack, tpl, g, entry.config, f"{ep}.config", list(fdefs), entry.script
        )
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
