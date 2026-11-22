"""测试夹具：两份结构不同的自制规则包（都不是任何具体作品）和手写的小地图。"""

from __future__ import annotations

import json
import re
from pathlib import Path

from smartkeeper.contracts import DiceResult, Problem, RulePack

HERE = Path(__file__).parent
PACKS = ("single", "multi")


def pack_text(name: str) -> str:
    return (HERE / f"rulepack_{name}.json").read_text(encoding="utf-8")


def load_pack(name: str) -> RulePack:
    return RulePack.model_validate(json.loads(pack_text(name))["pack"])


class FakeDice:
    """只做格式校验、按预置序列返回点数的假骰子，供不加载 dice 模块的测试使用。"""

    _RE = re.compile(r"^(\d*d\d+|\d+)([+-](\d*d\d+|\d+))*$")

    def __init__(self, totals: list[int] | None = None) -> None:
        self.totals = list(totals or [])

    def validate(self, expr: str) -> list[Problem]:
        if self._RE.match(expr.replace(" ", "")):
            return []
        return [Problem(code="dice.invalid", params={"expr": expr})]

    def roll(self, expr: str) -> DiceResult:
        total = self.totals.pop(0) if self.totals else 1
        return DiceResult(expr=expr, rolls=(total,), total=total)
