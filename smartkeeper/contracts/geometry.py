"""坐标与位置。引擎内部只用米：x 向东，y 向北，z 是离地高度。"""

from __future__ import annotations

from smartkeeper.contracts.base import Frozen


class Point(Frozen):
    x: float
    y: float
    z: float = 0.0


class Location(Frozen):
    pos: Point
    inside: str | None = None  # 所在建筑的地物 id
