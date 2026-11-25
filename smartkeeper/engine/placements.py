"""设置物（陷阱、结界等）：谁发现得了、本轮谁触发了。全是确定性的计算。

- 发现：设置者总能看到自己放的；别人按“感知半径 × 设置物的感知系数”，和实体之间的感知同一套算法（含视线）。
- 触发：本轮有人从范围外走进范围内（圆形按三维距离，整栋建筑的按进没进建筑）就算触发一次；设置者和设置者的玩家控制的实体不触发。
  按进入的先后排序，剩余次数用完后面的就不算了。本轮新放下的设置物从下一轮起才会被触发。
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from smartkeeper.contracts import Activity, Body, Location, Placement, Point
from smartkeeper.engine.space import Space
from smartkeeper.engine.timeline import location_at


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def placements_of(raw: JsonValue) -> dict[str, Placement]:
    return {pid: Placement.model_validate(p) for pid, p in _obj(raw).items()}


def _dist(a: Point, b: Point) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def contains(space: Space, p: Placement, pt: Point) -> bool:
    """这个点在不在设置物的范围里：整栋建筑的看在不在建筑里，其余的看离中心的三维距离。"""
    if p.building is not None:
        return space.spatial.inside_feature(space.map, p.building, pt)
    return _dist(pt, p.pos) <= p.radius


def inside_tags(space: Space) -> dict[str, set[str]]:
    """每个实体此刻站在自己放的哪些设置物里：实体 -> {in:<条目名>}（公式里 inside("条目名")）。"""
    places = placements_of(space.state.get("placements"))
    out: dict[str, set[str]] = {}
    for p in places.values():
        body = space.bodies.get(p.owner)
        if body is not None and contains(space, p, body.pos):
            out.setdefault(p.owner, set()).add(f"in:{p.entry}")
    return out


def perceived_placements(space: Space, entity_id: str) -> list[str]:
    """这个实体此刻能察觉到的设置物。"""
    places = placements_of(space.state.get("placements"))
    obs = space.bodies.get(entity_id)
    # 设置者、以及触发过它的实体，总能看到它（感知系数为 0 的也一样）
    mine = sorted(
        pid for pid, p in places.items() if p.owner == entity_id or entity_id in p.known_by
    )
    if obs is None:
        return mine
    others = [
        Body(
            id=pid,
            pos=p.pos,
            inside=p.inside,
            perception_radius=0.0,
            concealment=p.perceive_multiplier,
        )
        for pid, p in sorted(places.items())
        if p.owner != entity_id and entity_id not in p.known_by and p.perceive_multiplier > 0
    ]
    seen = space.spatial.perceivable(space.map, space.changes, obs, others) if others else []
    return sorted(set(mine) | set(seen))


def triggers(
    space: Space,
    acts: Mapping[str, Activity],
    moved_to: Mapping[str, Point],
    now: int,
    end: int,
) -> dict[str, list[str]]:
    """本轮被触发的设置物 -> 按进入先后排列的触发者（已按剩余次数截断）。

    移动路线：有进行中的行动的按行动推算；KP 另行安排了位置的（moved_to）按直线从起点到终点。
    """
    places = placements_of(space.state.get("placements"))
    if not places or end <= now:
        return {}
    step = max(1, (end - now) // 240)
    times = [*range(now, end, step), end]
    paths: dict[str, list[tuple[int, Point]]] = {}
    for eid, body in space.bodies.items():
        start = body.pos
        here = Location(pos=start, inside=body.inside)
        if eid in moved_to:
            to = moved_to[eid]
            span = end - now
            paths[eid] = [
                (
                    t,
                    Point(
                        x=start.x + (to.x - start.x) * (t - now) / span,
                        y=start.y + (to.y - start.y) * (t - now) / span,
                        z=start.z + (to.z - start.z) * (t - now) / span,
                    ),
                )
                for t in times
            ]
        elif eid in acts:
            pts: list[tuple[int, Point]] = []
            for t in times:
                loc = location_at(acts[eid], t, here)
                if loc is not None:
                    pts.append((t, loc.pos))
            paths[eid] = pts
    out: dict[str, list[str]] = {}
    for pid, p in sorted(places.items()):
        owner_player = space.owner.get(p.owner)
        hits: list[tuple[int, str]] = []
        for eid, pts in sorted(paths.items()):
            if eid == p.owner or (
                owner_player is not None and space.owner.get(eid) == owner_player
            ):
                continue
            if not pts or contains(space, p, pts[0][1]):
                continue  # 本轮开始时已经在范围里：不算“进入”
            entered = next((t for t, pt in pts if contains(space, p, pt)), None)
            if entered is not None:
                hits.append((entered, eid))
        hits.sort()
        names = [eid for _, eid in hits]
        if p.charges is not None:
            names = names[: p.charges]
        if names:
            out[pid] = names
    return out
