"""检定的代码：CheckDef.config 的文本 -> CheckSpec。和技能设置一样是一串 名字 = 值（见 smartkeeper.lang.config）。

    label = "感知检定"
    dice = 1d20 + per
    target = 0
    critical_success = natural == 20
    critical_failure = natural == 1
    success = roll > difficulty
    opposed_by = "perception"

出错抛 lang.FormulaError（带 line）：config.unknown_key、config.bad_value、config.duplicate……
"""

from __future__ import annotations

from typing import Literal

from smartkeeper import lang as f
from smartkeeper.contracts import CheckSpec

type Kind = Literal["text", "formula", "check"]

# 名字 -> 类型。顺序就是编辑器里预先填好的顺序
KEYS: dict[str, Kind] = {
    "label": "text",
    "dice": "formula",
    "target": "formula",
    "critical_success": "formula",
    "critical_failure": "formula",
    "success": "formula",
    "opposed_by": "check",
}
# 结果条件里能用的变量
VARS = ("roll", "natural", "target", "difficulty", "opp_roll", "opp_target")


def read_check(text: str) -> CheckSpec:
    out: dict[str, object] = {}
    for s in f.parse_config(text):
        kind = KEYS.get(s.name)
        if kind is None:
            raise f.FormulaError("config.unknown_key", line=s.line, name=s.name)
        if s.call is not None or s.items is not None:
            raise f.FormulaError("config.bad_value", line=s.line, name=s.name, expected=kind)
        if kind == "formula":
            out[s.name] = s.value
            continue
        node = f.parse(s.value) if s.value.strip() else None
        if node is None:
            continue
        if not isinstance(node, f.Str):
            raise f.FormulaError("config.bad_value", line=s.line, name=s.name, expected='"…"')
        out[s.name] = node.value
    return CheckSpec.model_validate(out)


def lines(text: str) -> dict[str, int]:
    """每一项在第几行（报问题用）。语法错时是空。"""
    try:
        return {s.name: s.line for s in f.parse_config(text)}
    except f.FormulaError:
        return {}
