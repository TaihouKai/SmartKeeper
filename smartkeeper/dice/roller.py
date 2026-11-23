from __future__ import annotations

import random

from smartkeeper.contracts import RandomSource, ValidationFailed

MAX_DICE = 1000
MAX_SIDES = 100000


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

    def faces(self, count: int, sides: int) -> tuple[int, ...]:
        if not (0 <= count <= MAX_DICE) or not (1 <= sides <= MAX_SIDES):
            raise ValidationFailed("formula.dice_range", count=count, sides=sides)
        return tuple(self._rng.randint(1, sides) for _ in range(count))
