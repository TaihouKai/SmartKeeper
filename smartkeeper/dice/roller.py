from __future__ import annotations

import random

from smartkeeper.contracts import DiceResult, Problem, RandomSource
from smartkeeper.dice import expr as _expr


class SystemRandomSource:
    """默认随机源。"""

    def __init__(self) -> None:
        self._rng = random.SystemRandom()

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)


class SeededRandomSource:
    """固定种子的随机源，供测试使用。"""

    def __init__(self, seed: int) -> None:
        self._rng = random.Random(seed)

    def randint(self, a: int, b: int) -> int:
        return self._rng.randint(a, b)


class DiceRoller:
    def __init__(self, rng: RandomSource) -> None:
        self._rng = rng

    def validate(self, expr: str) -> list[Problem]:
        return _expr.validate(expr)

    def roll(self, expr: str) -> DiceResult:
        rolls: list[int] = []
        total = 0
        for t in _expr.parse(expr):
            if t.count:
                faces = [self._rng.randint(1, t.sides) for _ in range(t.count)]
                rolls.extend(faces)
                total += t.sign * sum(faces)
            else:
                total += t.sign * t.constant
        return DiceResult(expr=expr.replace(" ", ""), rolls=tuple(rolls), total=total)
