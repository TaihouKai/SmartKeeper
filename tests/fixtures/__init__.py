"""测试夹具：两份结构不同的自制规则包（都不是任何具体作品）和手写的小地图。"""

from __future__ import annotations

import json
from pathlib import Path

from smartkeeper.contracts import RulePack

HERE = Path(__file__).parent
PACKS = ("single", "multi")


def pack_text(name: str) -> str:
    return (HERE / f"rulepack_{name}.json").read_text(encoding="utf-8")


def load_pack(name: str) -> RulePack:
    return RulePack.model_validate(json.loads(pack_text(name))["pack"])


class FakeDice:
    """按预置序列返回点数的假骰子，供不加载 dice 模块的测试使用；序列用完后每颗都是 1。"""

    def __init__(self, faces: list[int] | None = None) -> None:
        self.queue = list(faces or [])
        self.calls: list[tuple[int, int]] = []

    def faces(self, count: int, sides: int) -> tuple[int, ...]:
        self.calls.append((count, sides))
        return tuple(self.queue.pop(0) if self.queue else 1 for _ in range(count))
