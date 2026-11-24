"""技能设置：GroupEntry.config 的文本 -> SkillConfig。有哪些项、各是什么类型都在这里。

语法见 smartkeeper.lang.config。这里检查名字和值，出错抛 lang.FormulaError（带 line）：
config.unknown_key、config.bad_value（name、expected）、config.bad_call（name、call）、config.bad_arg（name、arg）。
公式本身（名字能不能解析、能不能掷骰）由 validation.check_config 另外检查。
"""

from __future__ import annotations

from typing import Literal

from smartkeeper import lang as f
from smartkeeper.contracts import PlacementSpec, Shape, SkillConfig

type Kind = Literal["choice", "bool", "formula", "shape", "placement"]

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
    "shape": "shape",
    "placement": "placement",
}
# 范围形状 -> 要写的参数（米、度）
SHAPES: dict[str, tuple[str, ...]] = {
    "capsule": ("length", "width"),
    "box": ("length", "width", "height"),
    "sphere": ("radius",),
    "cone": ("length", "angle"),
}
# 设置物的参数：radius 必填；perceive 是别人发现它的距离系数；duration 按分钟
PLACEMENT_ARGS = ("radius", "perceive", "charges", "duration", "notify")


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


def read_config(text: str) -> SkillConfig:
    """解析并检查名字和值的类型；没写的项取默认。"""
    out: dict[str, object] = {}
    for s in f.parse_config(text):
        kind = KEYS.get(s.name)
        if kind is None:
            raise _err("config.unknown_key", s)
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
                if need is None:
                    raise _err("config.bad_call", s, call=s.call)
                for a in args:
                    if a not in need:
                        raise _err("config.bad_arg", s, arg=a)
                for a in need:
                    if a not in args:
                        raise _err("config.missing_arg", s, arg=a)
                out["shape"] = Shape.model_validate(
                    {"kind": s.call, **{a: _number(s, a, v) for a, v in args.items()}}
                )
            else:
                if s.call != "placement":
                    raise _err("config.bad_call", s, call=s.call)
                for a in args:
                    if a not in PLACEMENT_ARGS:
                        raise _err("config.bad_arg", s, arg=a)
                if not args.get("radius", "").strip():
                    raise _err("config.missing_arg", s, arg="radius")
                dur = args.get("duration", "").strip()
                out["placement"] = PlacementSpec(
                    radius=args["radius"],
                    perceive_multiplier=args.get("perceive", "").strip() or "1",
                    charges=args.get("charges", ""),
                    duration=f"({dur}) * 60" if dur else "",  # 设置里按分钟，设置物按秒
                    notify_owner=_bool(s, args["notify"]) if "notify" in args else True,
                )
            continue
        if s.call is not None:
            raise _err("config.bad_value", s, expected=kind)
        if kind == "choice":
            node = _literal(s)
            if not (isinstance(node, f.Str) and node.value in TARGETS):
                raise _err("config.bad_value", s, expected=" / ".join(f'"{x}"' for x in TARGETS))
            out[s.name] = node.value
        elif kind == "bool":
            out[s.name] = _bool(s, s.value)
        else:
            out[s.name] = s.value
    return SkillConfig.model_validate(out)


def formulas(text: str) -> list[tuple[int, str, str]]:
    """设置里要按公式检查的值：(行号, 名字, 公式文本)。设置物的参数也算。语法错时返回空（由 read_config 报）。"""
    try:
        settings = f.parse_config(text)
    except f.FormulaError:
        return []
    out: list[tuple[int, str, str]] = []
    for s in settings:
        if KEYS.get(s.name) == "formula" and s.value.strip():
            out.append((s.line, s.name, s.value))
        if KEYS.get(s.name) == "placement" and s.call == "placement":
            out += [(s.line, f"{s.name}.{a}", v) for a, v in s.args if a != "notify" and v.strip()]
    return out
