"""技能设置：GroupEntry.config 的文本 -> SkillConfig。有哪些项、各是什么类型都在这里。

语法见 smartkeeper.lang.config。这里检查名字和值，出错抛 lang.FormulaError（带 line）：
config.unknown_key、config.bad_value（name、expected）、config.bad_call（name、call）、config.bad_arg（name、arg）。
公式本身（名字能不能解析、能不能掷骰）由 validation.check_config 另外检查。
"""

from __future__ import annotations

import contextlib
from typing import Literal, cast

from smartkeeper import lang as f
from smartkeeper.contracts import PlacementSpec, Shape, SkillConfig

type Kind = Literal[
    "choice", "bool", "formula", "shape", "placement", "check", "best", "reactions", "affects"
]

TARGETS = ("single", "self", "none")
# 名字 -> 值的类型。顺序就是编辑器里预先填好的顺序
KEYS: dict[str, Kind] = {
    "target": "choice",
    "range": "formula",
    "visible": "bool",
    "requires": "formula",
    "noise": "formula",
    "cast_time": "formula",
    "cooldown": "formula",
    "check": "best",
    "auto_level": "formula",
    "difficulty": "formula",
    "hit": "formula",
    "reactions": "reactions",
    "save": "check",
    "shape": "shape",
    "affects": "affects",
    "aura": "shape",
    "guard": "bool",
    "placement": "placement",
}
AFFECTS = ("all", "allies", "other_allies", "enemies")
# 范围形状 -> 要写的参数（米、度）
SHAPES: dict[str, tuple[str, ...]] = {
    "capsule": ("length", "width"),
    "box": ("length", "width", "height"),
    "sphere": ("radius",),
    "cone": ("length", "angle"),
}
# 用技能时引擎知道的数：设置的公式里能用 CONFIG_VARS；命中条件 hit 还能用双方的等级；技能脚本全都能用
CONFIG_VARS = ("distance", "unseen")
HIT_VARS = (*CONFIG_VARS, "level", "opp_level", "opposed")
# boost：这次选的参数的总效果倍数；turning_on：开关类用途这一次是不是打开；ally：这个对象是不是友军
SCRIPT_VARS = (*HIT_VARS, "saved", "reacting", "boost", "turning_on", "ally")
# 设置物的参数：radius 必填（building=True 时不用：设置者所在的整栋建筑就是设置物）；
# perceive 是别人发现它的距离系数；duration 按分钟
PLACEMENT_ARGS = ("radius", "perceive", "charges", "duration", "notify", "building")


def _err(code: str, s: f.Setting, **params: str) -> f.FormulaError:
    return f.FormulaError(code, line=s.line, name=s.name, **params)


def _literal(s: f.Setting) -> f.Node | None:
    return f.parse(s.value) if s.value.strip() else None


def _bool(s: f.Setting, text: str) -> bool:
    node = f.parse(text) if text.strip() else None
    if not (isinstance(node, f.Num) and node.value in (0.0, 1.0)):
        raise _err("config.bad_value", s, expected="True / False")
    return node.value == 1.0


def _number(s: f.Setting, arg: str, text: str) -> float:
    node = f.parse(text) if text.strip() else None
    if isinstance(node, f.Unary) and isinstance(node.operand, f.Num):
        node = f.Num(-node.operand.value)
    if not isinstance(node, f.Num):
        raise _err("config.bad_arg", s, arg=arg)
    return node.value


def names(config: str, script: str) -> dict[str, f.Node]:
    """一个条目里起了名字的公式：设置的各项、技能脚本最外层的局部变量（if 里面的只在脚本里用）。
    写错的部分跳过（由各自的检查报）。设置和变量同名时用设置的。"""
    env: dict[str, f.Node] = {}
    try:
        for n in f.parse_script(script):
            if isinstance(n, f.Let):
                env[n.name] = f.parse(n.value)
    except f.FormulaError:
        pass
    try:
        found = f.parse_config(config)
    except f.FormulaError:
        found = ()
    for s in found:
        if s.call is None and s.value.strip():
            with contextlib.suppress(f.FormulaError):
                env[s.name] = f.parse(s.value)
    return env


def expand(node: f.Node, env: dict[str, f.Node], own: str | None = None) -> f.Node:
    """把公式里条目内起了名字的公式换进去（可以层层引用，成环报 formula.cycle）。own 是这条公式自己的名字。"""

    def go(n: f.Node, seen: tuple[str, ...]) -> f.Node:
        def fn(name: str) -> f.Node | None:
            if name not in env:
                return None
            if name in seen:
                raise f.FormulaError("formula.cycle", name=" -> ".join([*seen, name]))
            return go(env[name], (*seen, name))

        return f.substitute(n, fn)

    return go(node, (own,) if own else ())


def settings(text: str, script: str = "") -> tuple[f.Setting, ...]:
    """解析设置，并把公式里引用的其他设置和脚本里的变量换成它们的公式（不分先后，不能绕成圈）。"""
    env = names(text, script)
    out: list[f.Setting] = []
    for s in f.parse_config(text):

        def link(text_: str, own: str = s.name) -> str:
            return f.to_text(expand(f.parse(text_), env, own)) if text_.strip() else text_

        try:
            value = link(s.value)
            args = tuple((a, link(v)) for a, v in s.args)
        except f.FormulaError as e:
            raise f.FormulaError(e.code, **{"line": s.line, **e.params}) from None
        out.append(
            f.Setting(line=s.line, name=s.name, value=value, call=s.call, args=args, items=s.items)
        )
    return tuple(out)


def read_config(text: str, script: str = "") -> SkillConfig:
    """解析并检查名字和值的类型；没写的项取默认。script 是同一条目的技能脚本（设置可以用里面的变量）。"""
    out: dict[str, object] = {}
    for s in settings(text, script):
        kind = KEYS.get(s.name)
        if kind is None:
            # 不是设置项：当作写定的参数（是不是这个条目的参数由 validation.check_config 查）
            if s.call is not None or s.items is not None or not s.value.strip():
                raise _err("config.unknown_key", s)
            fixed = cast(dict[str, str], out.setdefault("fixed", {}))
            fixed[s.name] = s.value
            continue
        if kind in ("shape", "placement"):
            if s.call is None:
                if s.value.strip():
                    raise _err(
                        "config.bad_value",
                        s,
                        expected=f"{'sphere(radius=…)' if kind == 'shape' else 'placement(radius=…)'}",
                    )
                continue  # None：不设
            args = dict(s.args)
            if kind == "shape":
                need = SHAPES.get(s.call)
                if need is None or (s.name == "aura" and s.call != "sphere"):
                    raise _err("config.bad_call", s, call=s.call)
                for a in args:
                    if a not in need:
                        raise _err("config.bad_arg", s, arg=a)
                for a in need:
                    if a not in args:
                        raise _err("config.missing_arg", s, arg=a)
                out[s.name] = Shape.model_validate(
                    {"kind": s.call, **{a: _number(s, a, v) for a, v in args.items()}}
                )
            else:
                if s.call != "placement":
                    raise _err("config.bad_call", s, call=s.call)
                for a in args:
                    if a not in PLACEMENT_ARGS:
                        raise _err("config.bad_arg", s, arg=a)
                # building：条件公式（可以按参数选），写死的 True 时不用半径
                building = args.get("building", "").strip()
                if building in ("False", "0"):
                    building = ""
                if building not in ("True", "1") and not args.get("radius", "").strip():
                    raise _err("config.missing_arg", s, arg="radius")
                dur = args.get("duration", "").strip()
                out["placement"] = PlacementSpec(
                    radius=args.get("radius", ""),
                    building=building,
                    perceive_multiplier=args.get("perceive", "").strip() or "1",
                    charges=args.get("charges", ""),
                    duration=f"({dur}) * 60" if dur else "",  # 设置里按分钟，设置物按秒
                    notify_owner=_bool(s, args["notify"]) if "notify" in args else True,
                )
            continue
        if kind == "reactions":
            if s.items is not None and s.call is None:
                out[s.name] = s.items
                continue
            node = _literal(s)
            if node is None or (isinstance(node, f.Num) and node.value == 0.0):
                continue
            if isinstance(node, f.Num) and node.value == 1.0:
                out["reactions_any"] = True  # True：对象可以用任何应对技能
                continue
            if not isinstance(node, f.Str):
                raise _err("config.bad_value", s, expected='["dodge", "block"] / True')
            out[s.name] = (node.value,)
            continue
        if kind == "best":
            if s.call is not None:
                if s.call != "best" or not s.items:
                    raise _err("config.bad_call", s, call=s.call)
                out[s.name] = s.items
                continue
            node = _literal(s)
            if node is None or (isinstance(node, f.Num) and node.value in (0.0, 1.0)):
                continue  # None / True：不掷骰，必中
            if isinstance(node, f.Str):
                out[s.name] = (node.value,)
                continue
            raise _err("config.bad_value", s, expected='"check_name" / best("a", "b")')
        if s.items is not None:
            raise _err("config.bad_value", s, expected=kind)
        if kind == "check":
            node = _literal(s)
            if node is None or (isinstance(node, f.Num) and node.value in (0.0, 1.0)):
                continue  # None / True：不掷骰，必中
            if not isinstance(node, f.Str):
                raise _err("config.bad_value", s, expected='"check_name"')
            out[s.name] = node.value
            continue
        if s.call is not None:
            raise _err("config.bad_value", s, expected=kind)
        if kind in ("choice", "affects"):
            allowed = TARGETS if kind == "choice" else AFFECTS
            node = _literal(s)
            if not (isinstance(node, f.Str) and node.value in allowed):
                raise _err("config.bad_value", s, expected=" / ".join(f'"{x}"' for x in allowed))
            out[s.name] = node.value
        elif kind == "bool":
            out[s.name] = _bool(s, s.value)
        else:
            out[s.name] = s.value
    return SkillConfig.model_validate(out)


def formulas(text: str, script: str = "") -> list[tuple[int, str, str]]:
    """设置里要按公式检查的值：(行号, 名字, 公式文本)。设置物的参数也算。语法错时返回空（由 read_config 报）。"""
    try:
        found = settings(text, script)
    except f.FormulaError:
        return []
    out: list[tuple[int, str, str]] = []
    for s in found:
        if (KEYS.get(s.name) == "formula" or s.name not in KEYS) and s.value.strip():
            out.append((s.line, s.name, s.value))
        if KEYS.get(s.name) == "placement" and s.call == "placement":
            out += [(s.line, f"{s.name}.{a}", v) for a, v in s.args if a != "notify" and v.strip()]
    return out
