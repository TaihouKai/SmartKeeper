"""空间查询的实现。建筑一律当作柱体：先在平面上求交，再比较高度区间。不需要完整的 3D 引擎。"""

from __future__ import annotations

import math
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from shapely import STRtree
from shapely.geometry import LineString, MultiPoint, Polygon
from shapely.geometry import Point as P2
from shapely.geometry.base import BaseGeometry

from smartkeeper.contracts import (
    Body,
    BuildingHit,
    LosResult,
    MapChange,
    MapData,
    Point,
    QueryResult,
    SweepShape,
    ValidationFailed,
)

EPS = 1e-6


@dataclass(frozen=True, slots=True)
class _Feat:
    id: str
    kind: str
    name: str
    geom: BaseGeometry
    min_h: float
    h: float


class _Index:
    def __init__(self, m: MapData) -> None:
        feats: list[_Feat] = []
        for f in m.features:
            if f.polygon is not None:
                g: BaseGeometry = Polygon(f.polygon[0], f.polygon[1:])
            elif f.line is not None:
                g = LineString(f.line)
            else:
                assert f.point is not None
                g = P2(f.point)
            feats.append(_Feat(f.id, f.kind, f.name, g, f.min_height, f.height))
        self.feats = feats
        self.by_id = {f.id: f for f in feats}
        self.tree = STRtree([f.geom for f in feats])

    def candidates(self, g: BaseGeometry) -> Iterable[_Feat]:
        for i in self.tree.query(g):
            yield self.feats[int(i)]


_CACHE: dict[tuple[str, int, tuple[float, float, float, float]], _Index] = {}
_LOCK = threading.Lock()


def index(m: MapData) -> _Index:
    key = (m.id, len(m.features), m.bounds)
    with _LOCK:
        idx = _CACHE.get(key)
        if idx is None:
            if len(_CACHE) > 16:
                _CACHE.clear()
            idx = _Index(m)
            _CACHE[key] = idx
        return idx


def _effective(changes: Sequence[MapChange]) -> dict[str, float | None]:
    """被毁建筑的有效顶高：None 表示整栋没了。"""
    out: dict[str, float | None] = {}
    for c in changes:
        if c.status != "destroyed":
            continue
        if c.feature in out and out[c.feature] is None:
            continue
        if c.above_z is None:
            out[c.feature] = None
        else:
            prev = out.get(c.feature)
            out[c.feature] = c.above_z if prev is None else min(prev, c.above_z)
    return out


def _prism(f: _Feat, eff: dict[str, float | None]) -> tuple[float, float] | None:
    """建筑的有效高度区间 [底高, 顶高]；不是建筑或已全毁时返回 None。"""
    if f.kind != "building":
        return None
    top = f.h
    if f.id in eff:
        cut = eff[f.id]
        if cut is None:
            return None
        top = min(top, cut)
    if top <= f.min_h + EPS:
        return None
    return f.min_h, top


def dist3(a: Point, b: Point) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _interval_dist(z: float, lo: float, hi: float) -> float:
    if z < lo:
        return lo - z
    if z > hi:
        return z - hi
    return 0.0


def _clip(lo: float, hi: float, a: float, b: float) -> tuple[float, float] | None:
    x, y = max(lo, a), min(hi, b)
    return (x, y) if y >= x - EPS else None


def _pieces(geom: BaseGeometry) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom] if geom.length > EPS else []
    out: list[LineString] = []
    for g in getattr(geom, "geoms", []):
        out += _pieces(g)
    return out


# ---------------- within / sphere ----------------


def within(
    m: MapData, changes: Sequence[MapChange], bodies: Sequence[Body], center: Point, radius: float
) -> QueryResult:
    idx = index(m)
    eff = _effective(changes)
    ents = sorted(b.id for b in bodies if dist3(b.pos, center) <= radius + EPS)
    c2 = P2(center.x, center.y)
    feats: list[str] = []
    hits: list[BuildingHit] = []
    for f in idx.candidates(c2.buffer(radius)):
        d_xy = f.geom.distance(c2)
        prism = _prism(f, eff)
        if f.kind == "building":
            if prism is None:
                continue
            d = math.hypot(d_xy, _interval_dist(center.z, *prism))
            if d <= radius + EPS:
                feats.append(f.id)
                span = math.sqrt(max(radius * radius - d_xy * d_xy, 0.0))
                iv = _clip(prism[0], prism[1], center.z - span, center.z + span)
                if iv is not None:
                    hits.append(BuildingHit(feature=f.id, z_from=iv[0], z_to=iv[1]))
        elif math.hypot(d_xy, center.z) <= radius + EPS:
            feats.append(f.id)
    return QueryResult(
        entities=tuple(ents),
        features=tuple(sorted(feats)),
        buildings=tuple(sorted(hits, key=lambda h: h.feature)),
    )


# ---------------- sweep ----------------


def _seg_dist(p: Point, a: Point, b: Point) -> float:
    ab = (b.x - a.x, b.y - a.y, b.z - a.z)
    ap = (p.x - a.x, p.y - a.y, p.z - a.z)
    ll = ab[0] ** 2 + ab[1] ** 2 + ab[2] ** 2
    t = 0.0 if ll == 0 else max(0.0, min(1.0, (ap[0] * ab[0] + ap[1] * ab[1] + ap[2] * ab[2]) / ll))
    q = Point(x=a.x + ab[0] * t, y=a.y + ab[1] * t, z=a.z + ab[2] * t)
    return dist3(p, q)


def _need(v: float | None, name: str) -> float:
    if v is None or v <= 0:
        raise ValidationFailed("spatial.bad_shape", param=name)
    return v


def _need_pt(v: Point | None, name: str) -> Point:
    if v is None:
        raise ValidationFailed("spatial.bad_shape", param=name)
    return v


def _heading(o: Point, t: Point) -> tuple[float, float]:
    dx, dy = t.x - o.x, t.y - o.y
    n = math.hypot(dx, dy)
    if n < EPS:
        raise ValidationFailed("spatial.no_direction")
    return dx / n, dy / n


def _sweep_capsule(
    m: MapData, eff: dict[str, float | None], bodies: Sequence[Body], s: SweepShape
) -> QueryResult:
    a, b, r = _need_pt(s.a, "a"), _need_pt(s.b, "b"), _need(s.radius, "radius")
    ents = sorted(x.id for x in bodies if _seg_dist(x.pos, a, b) <= r + EPS)
    idx = index(m)
    seg2 = LineString([(a.x, a.y), (b.x, b.y)]) if math.hypot(b.x - a.x, b.y - a.y) > EPS else None
    footprint = seg2.buffer(r) if seg2 is not None else P2(a.x, a.y).buffer(r)
    hits: list[BuildingHit] = []
    for f in idx.candidates(footprint):
        prism = _prism(f, eff)
        if prism is None or not f.geom.intersects(footprint):
            continue
        if seg2 is None:
            zlo, zhi = min(a.z, b.z) - r, max(a.z, b.z) + r
        else:
            zs: list[float] = []
            for piece in _pieces(seg2.intersection(f.geom.buffer(r))):
                for x, y in piece.coords:
                    t = seg2.project(P2(x, y), normalized=True)
                    zs.append(a.z + (b.z - a.z) * t)
            if not zs:
                # 线段只擦到缓冲区的一个点
                t = seg2.project(f.geom.centroid, normalized=True)
                zs = [a.z + (b.z - a.z) * t]
            zlo, zhi = min(zs) - r, max(zs) + r
        iv = _clip(prism[0], prism[1], zlo, zhi)
        if iv is not None and iv[1] > iv[0] + EPS:
            hits.append(BuildingHit(feature=f.id, z_from=iv[0], z_to=iv[1]))
    return QueryResult(
        entities=tuple(ents), features=tuple(h.feature for h in hits), buildings=tuple(hits)
    )


def _box_polygon(s: SweepShape) -> tuple[Polygon, float, float]:
    o, t = _need_pt(s.origin, "origin"), _need_pt(s.toward, "toward")
    length, width, height = (
        _need(s.length, "length"),
        _need(s.width, "width"),
        _need(s.height, "height"),
    )
    dx, dy = _heading(o, t)
    nx, ny = -dy, dx
    hw = width / 2
    corners = [
        (o.x + nx * hw, o.y + ny * hw),
        (o.x + dx * length + nx * hw, o.y + dy * length + ny * hw),
        (o.x + dx * length - nx * hw, o.y + dy * length - ny * hw),
        (o.x - nx * hw, o.y - ny * hw),
    ]
    return Polygon(corners), o.z - height / 2, o.z + height / 2


def _sweep_box(
    m: MapData, eff: dict[str, float | None], bodies: Sequence[Body], s: SweepShape
) -> QueryResult:
    poly, zlo, zhi = _box_polygon(s)
    ents = sorted(
        x.id
        for x in bodies
        if zlo - EPS <= x.pos.z <= zhi + EPS and poly.buffer(EPS).covers(P2(x.pos.x, x.pos.y))
    )
    hits: list[BuildingHit] = []
    for f in index(m).candidates(poly):
        prism = _prism(f, eff)
        if prism is None or not f.geom.intersects(poly):
            continue
        iv = _clip(prism[0], prism[1], zlo, zhi)
        if iv is not None and iv[1] > iv[0] + EPS:
            hits.append(BuildingHit(feature=f.id, z_from=iv[0], z_to=iv[1]))
    return QueryResult(
        entities=tuple(ents), features=tuple(h.feature for h in hits), buildings=tuple(hits)
    )


def _sweep_cone(
    m: MapData, eff: dict[str, float | None], bodies: Sequence[Body], s: SweepShape
) -> QueryResult:
    o, t = _need_pt(s.origin, "origin"), _need_pt(s.toward, "toward")
    length, angle = _need(s.length, "length"), _need(s.angle, "angle")
    if angle >= 90:
        raise ValidationFailed("spatial.bad_shape", param="angle")
    d = (t.x - o.x, t.y - o.y, t.z - o.z)
    n = math.sqrt(sum(c * c for c in d))
    if n < EPS:
        raise ValidationFailed("spatial.no_direction")
    d = (d[0] / n, d[1] / n, d[2] / n)
    cos_a = math.cos(math.radians(angle))

    def inside(p: Point) -> bool:
        v = (p.x - o.x, p.y - o.y, p.z - o.z)
        along = v[0] * d[0] + v[1] * d[1] + v[2] * d[2]
        if along < -EPS or along > length + EPS:
            return False
        vn = math.sqrt(sum(c * c for c in v))
        return vn < EPS or along / vn >= cos_a - EPS

    ents = sorted(x.id for x in bodies if inside(x.pos))
    # 底面圆上取点，和顶点一起求平面投影的凸包
    r = length * math.tan(math.radians(angle))
    up = (0.0, 0.0, 1.0) if abs(d[2]) < 0.9 else (1.0, 0.0, 0.0)
    u = (d[1] * up[2] - d[2] * up[1], d[2] * up[0] - d[0] * up[2], d[0] * up[1] - d[1] * up[0])
    un = math.sqrt(sum(c * c for c in u))
    u = (u[0] / un, u[1] / un, u[2] / un)
    w = (d[1] * u[2] - d[2] * u[1], d[2] * u[0] - d[0] * u[2], d[0] * u[1] - d[1] * u[0])
    base = [(o.x + d[0] * length, o.y + d[1] * length, o.z + d[2] * length)]
    pts3 = [(o.x, o.y, o.z)]
    for k in range(32):
        th = 2 * math.pi * k / 32
        c, sn = math.cos(th) * r, math.sin(th) * r
        pts3.append(
            (
                base[0][0] + u[0] * c + w[0] * sn,
                base[0][1] + u[1] * c + w[1] * sn,
                base[0][2] + u[2] * c + w[2] * sn,
            )
        )
    hull = MultiPoint([(p[0], p[1]) for p in pts3]).convex_hull
    zlo, zhi = min(p[2] for p in pts3), max(p[2] for p in pts3)
    hits: list[BuildingHit] = []
    for f in index(m).candidates(hull):
        prism = _prism(f, eff)
        if prism is None or not f.geom.intersects(hull):
            continue
        # 简化：用整个锥体的高度范围与建筑的高度区间求交
        iv = _clip(prism[0], prism[1], zlo, zhi)
        if iv is not None and iv[1] > iv[0] + EPS:
            hits.append(BuildingHit(feature=f.id, z_from=iv[0], z_to=iv[1]))
    return QueryResult(
        entities=tuple(ents), features=tuple(h.feature for h in hits), buildings=tuple(hits)
    )


def sweep(
    m: MapData, changes: Sequence[MapChange], bodies: Sequence[Body], shape: SweepShape
) -> QueryResult:
    eff = _effective(changes)
    if shape.kind == "sphere":
        return within(
            m, changes, bodies, _need_pt(shape.center, "center"), _need(shape.radius, "radius")
        )
    if shape.kind == "capsule":
        return _sweep_capsule(m, eff, bodies, shape)
    if shape.kind == "box":
        return _sweep_box(m, eff, bodies, shape)
    return _sweep_cone(m, eff, bodies, shape)


# ---------------- 视线与感知 ----------------


def line_of_sight(m: MapData, changes: Sequence[MapChange], a: Point, b: Point) -> LosResult:
    eff = _effective(changes)
    idx = index(m)
    blockers: list[str] = []
    flat = math.hypot(b.x - a.x, b.y - a.y) <= EPS
    if flat:
        p = P2(a.x, a.y)
        zlo, zhi = min(a.z, b.z), max(a.z, b.z)
        for f in idx.candidates(p):
            prism = _prism(f, eff)
            if prism and f.geom.covers(p) and zhi >= prism[0] - EPS and zlo < prism[1] - EPS:
                blockers.append(f.id)
        return LosResult(visible=not blockers, blockers=tuple(sorted(blockers)))
    seg = LineString([(a.x, a.y), (b.x, b.y)])
    for f in idx.candidates(seg):
        prism = _prism(f, eff)
        if prism is None:
            continue
        for piece in _pieces(seg.intersection(f.geom)):
            zs = [
                a.z + (b.z - a.z) * seg.project(P2(x, y), normalized=True) for x, y in piece.coords
            ]
            # 楼底闭、楼顶开：地面上的视线会被楼挡住，正好贴着楼顶的视线不算被挡
            if max(zs) >= prism[0] - EPS and min(zs) < prism[1] - EPS:
                blockers.append(f.id)
                break
    return LosResult(visible=not blockers, blockers=tuple(sorted(blockers)))


def perceivable(
    m: MapData, changes: Sequence[MapChange], observer: Body, bodies: Sequence[Body]
) -> list[str]:
    """距离不超过“观察者的感知半径 × 对方的匿踪系数”，并且有视线或在同一栋建筑内。"""
    out: list[str] = []
    for b in bodies:
        if b.id == observer.id:
            continue
        if dist3(observer.pos, b.pos) > observer.perception_radius * b.concealment + EPS:
            continue
        if (observer.inside is not None and observer.inside == b.inside) or line_of_sight(
            m, changes, observer.pos, b.pos
        ).visible:
            out.append(b.id)
    return sorted(out)


def locate(m: MapData, name: str | None = None, point: Point | None = None) -> list[str]:
    idx = index(m)
    if name is not None:
        key = name.strip().casefold()
        exact = [f.id for f in idx.feats if f.name and f.name.casefold() == key]
        if exact:
            return sorted(exact)
        return sorted(f.id for f in idx.feats if key and f.name and key in f.name.casefold())
    if point is not None:
        p = P2(point.x, point.y)
        hit = [f.id for f in idx.candidates(p.buffer(5.0)) if f.geom.distance(p) <= 5.0]
        inside = [fid for fid in hit if idx.by_id[fid].geom.covers(p)]
        return sorted(inside or hit)
    return []


def in_bounds(m: MapData, p: Point) -> bool:
    minx, miny, maxx, maxy = m.bounds
    return minx - EPS <= p.x <= maxx + EPS and miny - EPS <= p.y <= maxy + EPS


def inside_feature(m: MapData, feature_id: str, p: Point) -> bool:
    f = index(m).by_id.get(feature_id)
    return f is not None and isinstance(f.geom, Polygon) and f.geom.buffer(EPS).covers(P2(p.x, p.y))


def feature_within(
    m: MapData, changes: Sequence[MapChange], feature_id: str, center: Point, radius: float
) -> bool:
    f = index(m).by_id.get(feature_id)
    if f is None:
        return False
    d_xy = f.geom.distance(P2(center.x, center.y))
    lo, hi = (f.min_h, f.h) if f.kind == "building" else (0.0, 0.0)
    return math.hypot(d_xy, _interval_dist(center.z, lo, hi)) <= radius + EPS
