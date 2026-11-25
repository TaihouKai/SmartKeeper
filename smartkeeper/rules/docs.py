"""语法手册的目录：从公式语言（lang）、技能设置（skillconfig）、检定代码（checkconfig）的定义里生成。

每一项的说明是翻译键（前端按语言显示）；签名和参数名是代码，不翻译。新加的函数、动作、设置项、变量
必须在这里有一条（tests/rules/test_docs.py 检查），手册和编辑器的悬停提示都从这里来。
"""

from __future__ import annotations

from smartkeeper import lang as f
from smartkeeper.contracts import DocEntry
from smartkeeper.rules import checkconfig, skillconfig

# 动作的签名和参数（名字、说明键）。和 lang.VERBS 一一对应
_VERBS: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "damage": (
        'damage(amount, kind="")',
        (("amount", "doc.p.amount_dice"), ("kind", "doc.p.damage_kind")),
    ),
    "add": (
        "add(field, amount, minutes=None)",
        (
            ("field", "doc.p.runtime_field"),
            ("amount", "doc.p.amount_dice"),
            ("minutes", "doc.p.timed_minutes"),
        ),
    ),
    "sub": (
        "sub(field, amount)",
        (("field", "doc.p.runtime_field"), ("amount", "doc.p.amount_dice")),
    ),
    "set": (
        "set(field, amount)",
        (("field", "doc.p.runtime_field"), ("amount", "doc.p.amount_dice")),
    ),
    "negate": ("negate()", ()),
    "modify": (
        "modify(derived, formula, minutes)",
        (
            ("derived", "doc.p.derived"),
            ("formula", "doc.p.modify_formula"),
            ("minutes", "doc.p.minutes"),
        ),
    ),
    "summon": (
        "summon(template, count, minutes=None, field=value, …)",
        (
            ("template", "doc.p.summon_template"),
            ("count", "doc.p.summon_count"),
            ("minutes", "doc.p.summon_minutes"),
        ),
    ),
    "teleport": ("teleport(to)", (("to", "doc.p.teleport_to"),)),
}

# 函数的签名。和 lang.FUNCTIONS 一一对应
_FUNCTIONS: dict[str, str] = {
    "abs": "abs(x)",
    "floor": "floor(x)",
    "ceil": "ceil(x)",
    "round": "round(x)",
    "trunc": "trunc(x)",
    "sign": "sign(x)",
    "sqrt": "sqrt(x)",
    "pow": "pow(x, y)",
    "mod": "mod(x, y)",
    "min": "min(a, b, …)",
    "max": "max(a, b, …)",
    "clamp": "clamp(x, lo, hi)",
    "lookup": "lookup(table, key)",
    "count": "count(group.col, value)",
    "sum": "sum(group.col)",
    "highest": "highest(n, s, k)",
    "lowest": "lowest(n, s, k)",
    "dice": "dice(n, s)",
    "has": 'has("status")',
    "inside": 'inside("entry")',
    "toggled": 'toggled("group")',
}

# 形状和设置物的构造。形状的参数来自 skillconfig.SHAPES，设置物的来自 PLACEMENT_ARGS
_ARG_DOC = {
    "radius": "doc.p.radius_m",
    "length": "doc.p.length_m",
    "width": "doc.p.width_m",
    "height": "doc.p.height_m",
    "angle": "doc.p.angle",
}
_PLACEMENT_ARGS: dict[str, tuple[str, str]] = {
    "radius": ("radius", "doc.p.placement_radius"),
    "perceive": ("perceive=1", "doc.p.perceive"),
    "charges": ("charges=None", "doc.p.charges"),
    "duration": ("duration=None", "doc.p.duration"),
    "notify": ("notify=True", "doc.p.notify"),
    "building": ("building=False", "doc.p.building"),
}

# 公式和骰子的写法（例子）
_BASICS: tuple[tuple[str, str, str], ...] = (
    ("arith", "self.str * 2 + (self.dex - 10) / 2", "fh.b.arith"),
    ("compare", "self.str >= 50", "fh.b.compare"),
    ("text", 'self.occupation == "doctor"', "fh.b.text"),
    ("ifexp", '2 if self.job == "mage" else 1', "fh.b.ifexp"),
    ("logic", "1 < x <= 3 and not dead", "fh.b.logic"),
    ("ops", "x % 3    x // 2    x ** 2", "fh.b.ops"),
    ("names", "hp_max", "fh.b.names"),
    ("self", "self.hp", "fh.b.self"),
    ("this", "this.level", "fh.b.this"),
    ("peer", "companion.str", "fh.b.peer"),
    ("entry", "hero.fireball", "fh.b.entry"),
    ("entry_col", "hero.fireball.level", "fh.b.entry_col"),
    ("target", "target.hp", "fh.b.target"),
    ("template", 'target.template == "monster"', "fh.b.template"),
    ("count", "count(companion.traits.rank, 3)", "fh.b.count"),
    ("sum", "sum(talents.cost)", "fh.b.sum"),
)
_DICE: tuple[tuple[str, str, str], ...] = (
    ("dice_basic", "3d6", "fh.d.basic"),
    ("dice_one", "d20    d%", "fh.d.one"),
    ("dice_field", "1dstr    2d(str + 1)", "fh.d.field"),
    ("dice_names", "dice(level, luck)", "fh.d.names"),
    ("dice_order", "2d6 * 5", "fh.d.order"),
    ("dice_keep", "highest(4, 6, 3)", "fh.d.keep"),
)
_SCRIPT: tuple[tuple[str, str, str], ...] = (
    ("let", "heal = 2 + this.level * 3", "fh.s.let"),
    ("if", 'if target.template == "monster":', "fh.s.if"),
    ("else", "elif …: / else:", "fh.s.else"),
)
_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("self", "self", "doc.kw.self"),
    ("target", "target", "doc.kw.target"),
    ("this", "this", "doc.kw.this"),
    ("and", "a and b", "doc.kw.and"),
    ("or", "a or b", "doc.kw.or"),
    ("not", "not a", "doc.kw.not"),
    ("None", "None", "doc.kw.none"),
    ("pass", "pass", "doc.kw.pass"),
)


def catalog() -> tuple[DocEntry, ...]:
    out: list[DocEntry] = []
    out += [DocEntry(name=n, category="basics", sig=s, desc=d) for n, s, d in (*_BASICS, *_DICE)]
    for key in skillconfig.KEYS:
        out.append(DocEntry(name=key, category="config", sig=f"{key} = …", desc=f"config.c.{key}"))
    for shape, args in skillconfig.SHAPES.items():
        out.append(
            DocEntry(
                name=shape,
                category="shape",
                sig=f"{shape}({', '.join(args)})",
                desc=f"doc.shape.{shape}",
                params=tuple((a, _ARG_DOC[a]) for a in args),
            )
        )
    out.append(
        DocEntry(
            name="placement",
            category="shape",
            sig=f"placement({', '.join(_PLACEMENT_ARGS[a][0] for a in skillconfig.PLACEMENT_ARGS)})",
            desc="doc.placement",
            params=tuple((a, _PLACEMENT_ARGS[a][1]) for a in skillconfig.PLACEMENT_ARGS),
        )
    )
    for verb in f.VERBS:
        sig, params = _VERBS[verb]
        out.append(
            DocEntry(
                name=verb,
                category="verb",
                sig=sig,
                desc=f"doc.verb.{verb}",
                params=params,
            )
        )
    out += [DocEntry(name=n, category="script", sig=s, desc=d) for n, s, d in _SCRIPT]
    for name in f.FUNCTIONS:
        out.append(
            DocEntry(name=name, category="function", sig=_FUNCTIONS[name], desc=f"fh.fn.{name}")
        )
    out += [DocEntry(name=n, category="variable", sig=s, desc=d) for n, s, d in _KEYWORDS]
    for var in skillconfig.SCRIPT_VARS:
        out.append(DocEntry(name=var, category="variable", sig=var, desc=f"doc.kw.{var}"))
    for key in checkconfig.KEYS:
        out.append(DocEntry(name=key, category="check", sig=f"{key} = …", desc=f"check.c.{key}"))
    for var in checkconfig.VARS:
        if var != "target":  # 和上面的项同名
            out.append(DocEntry(name=var, category="check", sig=var, desc=f"check.v.{var}"))
    return tuple(out)
