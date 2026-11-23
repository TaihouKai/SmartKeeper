"""规则书：由规则包的表单内容自动生成的全文（Markdown）。给 KP 阅读，也是玩家的规则页面。

这里只输出规则包里的原文和结构，不加任何成句的说明文字，标题用固定的结构标记。
"""

from __future__ import annotations

from smartkeeper.contracts import EntityTemplate, FieldDef, RulePack


def _field(fd: FieldDef) -> str:
    bits = [f"`{fd.name}`", fd.label or "", f"[{fd.kind}/{fd.cls}]"]
    if fd.unit:
        bits.append(f"({fd.unit})")
    if fd.min is not None:
        bits.append(f"min={fd.min}")
    if fd.max is not None:
        bits.append(f"max={fd.max}")
    if fd.initial is not None:
        bits.append(f"initial={fd.initial}")
    if fd.choices:
        bits.append("{" + " | ".join(fd.choices) + "}")
    if fd.spends:
        bits.append(f"spends={fd.spends}")
    if fd.per_minute:
        bits.append(f"per_minute={fd.per_minute}")
    if fd.description:
        bits.append(f"— {fd.description}")
    return "- " + " ".join(b for b in bits if b)


def _template(t: EntityTemplate, include_hidden: bool) -> list[str]:
    out = [f"### {t.label or t.name} (`{t.name}`)", ""]
    for fd in t.fields:
        if include_hidden or not fd.hidden:
            out.append(_field(fd))
    for d in t.derived:
        if include_hidden or not d.hidden:
            unit = f" ({d.unit})" if d.unit else ""
            out.append(f"- `{d.name}` {d.label} = `{d.formula}`{unit}")
    for g in t.groups:
        if not include_hidden and g.hidden:
            continue
        count = f"{g.min_count}..{g.max_count if g.max_count is not None else 'n'}"
        out.append(f"- [{g.label or g.name}] (`{g.name}`, {count})")
        for fd in g.fields:
            out.append("  " + _field(fd))
        for p in g.presets:
            cond = f" when `{p.when}`" if p.when.strip() else ""
            vals = ", ".join(f"{k}={v}" for k, v in p.fields.items())
            line = f"  - * {p.name}{cond}"
            if vals:
                line += f" ({vals})"
            if p.description:
                line += f": {p.description}"
            out.append(line)
            for eff in p.effects:
                mech = f" `{eff.target} = {eff.formula}`" if eff.is_mechanical else ""
                out.append(f"    - {eff.description}{mech}")
    out.append("")
    return out


def render(pack: RulePack, include_hidden: bool = True) -> str:
    w = pack.world
    out = [f"# {w.name}", ""]
    if w.canon:
        out += [f"> {w.canon}", ""]
    if w.description:
        out += [w.description, ""]
    if w.reference_sites:
        out += [*(f"- <{u}>" for u in w.reference_sites), ""]
    out += ["## templates", ""]
    for t in pack.templates:
        out += _template(t, include_hidden)
    out += ["## player_entities", ""]
    for pe in pack.player_entities:
        out.append(f"- `{pe.template}` × {pe.min}..{pe.max}")
    out.append("")
    if pack.formulas:
        out += ["## formulas", ""]
        out += [f"- `{x.name}` {x.label} = `{x.formula}`" for x in pack.formulas]
        out.append("")
    if pack.tables:
        out += ["## tables", ""]
        for t in pack.tables:
            rows = ", ".join(f"{k}→{v}" for k, v in t.rows)
            out.append(f"- `{t.name}` ({t.kind}): {rows}")
        out.append("")
    if pack.checks:
        out += ["## checks", ""]
        for c in pack.checks:
            out.append(f"- `{c.name}` {c.label}: `{c.dice}` vs `{c.target}`")
            for lv in c.levels:
                out.append(f"  - {lv.name}: `{lv.condition}`")
        out.append("")
    if pack.rules_text.strip():
        out += ["## rules", "", pack.rules_text.strip(), ""]
    return "\n".join(out)
