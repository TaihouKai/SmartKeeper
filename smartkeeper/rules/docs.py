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
    "locate": ("locate()", ()),
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
    ("clock", "time >= 10:00 and time < 14:00    time >= 22:00 or time < 2:00", "fh.b.clock"),
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
    ("change", "target.hp -= 10    self.mp -= this.mp_spent    target.shield += 5", "doc.s.change"),
    (
        "minutes",
        "with minutes(10):\n    target.str -= 2\n    target.move_speed *= 0.5",
        "doc.s.minutes",
    ),
    (
        "bonus",
        'self.str += 2  # 力量 +2\nif self.template == "master":\n    self.move_speed *= 1.2',
        "doc.s.bonus",
    ),
    ("let", "heal = 2 + this.level * 3", "fh.s.let"),
    ("if", 'if target.template == "monster":\n    target.hp -= 5', "fh.s.if"),
    ("else", "elif …: / else:", "fh.s.else"),
)
_KEYWORDS: tuple[tuple[str, str, str], ...] = (
    ("self", "self", "doc.kw.self"),
    ("target", "target", "doc.kw.target"),
    ("this", "this", "doc.kw.this"),
    ("time", "time", "doc.kw.time"),
    ("day", "day", "doc.kw.day"),
    ("and", "a and b", "doc.kw.and"),
    ("or", "a or b", "doc.kw.or"),
    ("not", "not a", "doc.kw.not"),
    ("None", "None", "doc.kw.none"),
    ("pass", "pass", "doc.kw.pass"),
)


# 技能设置每一项能填什么（写法、说明键）和一行例子。和 skillconfig.KEYS 一一对应（有测试）
_CONFIG_VALUES: dict[str, tuple[tuple[str, str], ...]] = {
    "target": (
        ('"single"', "docs.v.target.0"),
        ('"self"', "docs.v.target.1"),
        ('"none"', "docs.v.target.2"),
    ),
    "range": (
        ("公式", "docs.v.range.0"),
        ("None", "docs.v.range.1"),
    ),
    "visible": (
        ("True", "docs.v.visible.0"),
        ("False", "docs.v.visible.1"),
    ),
    "seen_within": (
        ("公式", "docs.v.seen_within.0"),
        ("None", "docs.v.seen_within.1"),
    ),
    "requires": (
        ("条件公式", "docs.v.requires.0"),
        ("None", "docs.v.requires.1"),
    ),
    "noise": (
        ("公式", "docs.v.noise.0"),
        ("None", "docs.v.noise.1"),
    ),
    "cast_time": (
        ("公式", "docs.v.cast_time.0"),
        ("None", "docs.v.cast_time.1"),
    ),
    "cooldown": (
        ("公式", "docs.v.cooldown.0"),
        ("None", "docs.v.cooldown.1"),
    ),
    "check": (
        ('"检定名"', "docs.v.check.0"),
        ('best("a", "b")', "docs.v.check.1"),
        ("None / True", "docs.v.check.2"),
    ),
    "auto_level": (("公式", "docs.v.auto_level.0"),),
    "difficulty": (
        ("公式", "docs.v.difficulty.0"),
        ("None", "docs.v.difficulty.1"),
    ),
    "hit": (
        ("条件公式", "docs.v.hit.0"),
        ("None", "docs.v.hit.1"),
    ),
    "reactions": (
        ('["检定名或应对技能", …]', "docs.v.reactions.0"),
        ("True", "docs.v.reactions.1"),
        ("[]", "docs.v.reactions.2"),
    ),
    "save": (('"检定名"', "docs.v.save.0"),),
    "shape": (
        ("sphere(radius=…)", "docs.v.shape.0"),
        ("cone(length=…, angle=…)", "docs.v.shape.1"),
        ("capsule(length=…, width=…)", "docs.v.shape.2"),
        ("box(length=…, width=…, height=…)", "docs.v.shape.3"),
        ("None", "docs.v.shape.4"),
    ),
    "affects": (
        ('"all"', "docs.v.affects.0"),
        ('"allies"', "docs.v.affects.1"),
        ('"other_allies"', "docs.v.affects.3"),
        ('"enemies"', "docs.v.affects.2"),
    ),
    "aura": (
        ("sphere(radius=…)", "docs.v.aura.0"),
        ("None", "docs.v.aura.1"),
    ),
    "guard": (
        ("True", "docs.v.guard.0"),
        ("False", "docs.v.guard.1"),
    ),
    "placement": (
        ("placement(radius=…, …)", "docs.v.placement.0"),
        ("None", "docs.v.placement.1"),
    ),
    "toggle": (
        ("条件公式", "docs.v.toggle.0"),
        ("None", "docs.v.toggle.1"),
    ),
    "reaction_only": (
        ("True", "docs.v.reaction_only.0"),
        ("False", "docs.v.reaction_only.1"),
    ),
}
_CONFIG_EXAMPLES: dict[str, str] = {
    "target": 'target = "single"',
    "range": "range = 30 + this.level * 5",
    "visible": "visible = True",
    "seen_within": "seen_within = 60",
    "requires": "requires = self.mp >= 5",
    "noise": "noise = 20",
    "cast_time": "cast_time = 10",
    "cooldown": "cooldown = 60",
    "check": 'check = "perception"',
    "auto_level": "auto_level = this.level",
    "difficulty": "difficulty = floor(distance / 500)",
    "hit": "hit = level >= 2",
    "reactions": 'reactions = ["dodge"]',
    "save": 'save = "constitution"',
    "shape": "shape = cone(length=10, angle=60)",
    "affects": 'affects = "allies"',
    "aura": "aura = sphere(radius=50)",
    "guard": "guard = True",
    "placement": "placement = placement(radius=3, charges=1)",
    "toggle": "toggle = self.spirit_form",
    "reaction_only": "reaction_only = True",
}

# 检定代码每一项能填什么。和 checkconfig.KEYS 一一对应
_CHECK_VALUES: dict[str, tuple[tuple[str, str], ...]] = {
    "label": (('"显示名"', "docs.v.check_label.0"),),
    "dice": (("骰子公式", "docs.v.check_dice.0"),),
    "target": (("公式", "docs.v.check_target.0"),),
    "success": (("条件公式", "docs.v.check_success.0"),),
    "level": (("公式", "docs.v.check_level.0"),),
    "levels": (('["失败", "成功", …]', "docs.v.check_levels.0"),),
    "opposed_by": (
        ('"检定名"', "docs.v.check_opposed_by.0"),
        ("None", "docs.v.check_opposed_by.1"),
    ),
}
_CHECK_EXAMPLES: dict[str, str] = {
    "label": 'label = "感知"',
    "dice": "dice = 1d20 + self.per",
    "target": "target = 0",
    "success": "success = roll > 10 + difficulty",
    "level": "level = 0 if roll <= 10 else 1 if roll <= 15 else 2",
    "levels": 'levels = ["失败", "成功", "大成功"]',
    "opposed_by": 'opposed_by = "agility"',
}


def catalog() -> tuple[DocEntry, ...]:
    out: list[DocEntry] = []
    out += [DocEntry(name=n, category="basics", sig=s, desc=d) for n, s, d in (*_BASICS, *_DICE)]
    for key in skillconfig.KEYS:
        out.append(
            DocEntry(
                name=key,
                category="config",
                sig=f"{key} = …",
                desc=f"config.c.{key}",
                values=_CONFIG_VALUES[key],
                example=_CONFIG_EXAMPLES[key],
            )
        )
    # 写定的参数：“怎么用”里 参数名 = 值
    out.append(
        DocEntry(
            name="fixed_param",
            category="config",
            sig="<param> = …",
            desc="config.c.fixed_param",
            values=(("公式", "docs.v.fixed_param.0"),),
            example="release = 1    # 这个用法一定选这个参数的这个值",
        )
    )
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
        out.append(
            DocEntry(
                name=key,
                category="check",
                sig=f"{key} = …",
                desc=f"check.c.{key}",
                values=_CHECK_VALUES[key],
                example=_CHECK_EXAMPLES[key],
            )
        )
    for var in checkconfig.VARS:
        if var != "target":  # 和上面的项同名
            out.append(DocEntry(name=var, category="check", sig=var, desc=f"check.v.{var}"))
    return tuple(out)
