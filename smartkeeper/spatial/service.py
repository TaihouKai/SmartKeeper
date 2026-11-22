"""Spatial 接口的实现，薄薄包一层 geometry 里的纯函数。"""

from __future__ import annotations

from collections.abc import Sequence

from smartkeeper.contracts import (
    Body,
    LosResult,
    MapChange,
    MapData,
    Point,
    QueryResult,
    SweepShape,
)
from smartkeeper.spatial import geometry as g


class ShapelySpatial:
    def within(
        self,
        m: MapData,
        changes: Sequence[MapChange],
        bodies: Sequence[Body],
        center: Point,
        radius: float,
    ) -> QueryResult:
        return g.within(m, changes, bodies, center, radius)

    def sweep(
        self, m: MapData, changes: Sequence[MapChange], bodies: Sequence[Body], shape: SweepShape
    ) -> QueryResult:
        return g.sweep(m, changes, bodies, shape)

    def line_of_sight(
        self, m: MapData, changes: Sequence[MapChange], a: Point, b: Point
    ) -> LosResult:
        return g.line_of_sight(m, changes, a, b)

    def perceivable(
        self, m: MapData, changes: Sequence[MapChange], observer: Body, bodies: Sequence[Body]
    ) -> list[str]:
        return g.perceivable(m, changes, observer, bodies)

    def distance(self, a: Point, b: Point) -> float:
        return g.dist3(a, b)

    def locate(self, m: MapData, name: str | None = None, point: Point | None = None) -> list[str]:
        return g.locate(m, name, point)

    def in_bounds(self, m: MapData, p: Point) -> bool:
        return g.in_bounds(m, p)

    def inside_feature(self, m: MapData, feature_id: str, p: Point) -> bool:
        return g.inside_feature(m, feature_id, p)

    def feature_within(
        self,
        m: MapData,
        changes: Sequence[MapChange],
        feature_id: str,
        center: Point,
        radius: float,
    ) -> bool:
        return g.feature_within(m, changes, feature_id, center, radius)
