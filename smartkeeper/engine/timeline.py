"""连续时间：移动耗时、进行中的行动、某一时刻的位置、回合的结束时刻。全是确定性的纯计算。

- 能飞：沿直线（三维距离）以 fly_speed 飞过去。
- 不能飞：先在竖直方向走到目标高度，再在水平方向直线走过去，都按 move_speed。
- 速度单位是米/分钟，时间单位是秒，耗时向上取整到整秒。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import JsonValue

from smartkeeper.contracts import (
    FLY_FIELD,
    ActionItem,
    Activity,
    Location,
    Point,
    Step,
    ValidationFailed,
)
from smartkeeper.engine.space import Space, point_of


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def can_fly(space: Space, entity_id: str) -> bool:
    """能不能飞：“能飞”字段经过修正之后的值（例如限时的飞行魔术让它变成是）。"""
    try:
        return space.derived(entity_id, FLY_FIELD) != 0
    except ValidationFailed:
        return False


def travel_seconds(space: Space, entity_id: str, start: Point, to: Point) -> tuple[int, bool]:
    """从 start 到 to 要几秒，以及是不是飞过去的。"""
    fly = can_fly(space, entity_id)
    speed = space.derived(entity_id, "fly_speed" if fly else "move_speed")
    dx, dy, dz = to.x - start.x, to.y - start.y, to.z - start.z
    dist = math.sqrt(dx * dx + dy * dy + dz * dz) if fly else math.hypot(dx, dy) + abs(dz)
    if dist <= 1e-9:
        return 0, fly
    if speed <= 0:
        raise ValidationFailed("move.cannot_move", entity=entity_id)
    return math.ceil(dist / speed * 60 - 1e-9), fly


def _moves(space: Space, items: Sequence[ActionItem]) -> list[tuple[Point | None, int, bool]]:
    """每一条的起点、移动耗时、飞不飞。同一实体的条目按顺序衔接：下一条从上一条的终点出发。

    一起走的（同一个 group）一起到：到达时刻 = 组里最晚能出发的人（前面还有别的事要做）+ 最慢的路程；
    先能出发的人走得慢一些，同一时刻到。"""
    here: dict[str, Point | None] = {}
    alone: list[tuple[Point | None, int, bool]] = []
    for it in items:
        if it.actor not in here:
            here[it.actor] = point_of(_obj(space.entities.get(it.actor)).get("pos"))
        start = here[it.actor]
        move, fly = 0, False
        if it.destination is not None and start is not None:
            move, fly = travel_seconds(space, it.actor, start, it.destination.pos)
        if it.destination is not None:
            here[it.actor] = it.destination.pos
        alone.append((start, move, fly))
    members: dict[str, list[int]] = {}
    for k, it in enumerate(items):
        if it.group is not None:
            members.setdefault(it.group, []).append(k)
    ready: dict[str, int] = {}  # 每个人前面的事做完的时刻
    moves = [m for _, m, _ in alone]
    done: set[str] = set()
    for k, it in enumerate(items):
        g = it.group
        if g is not None and g not in done:
            done.add(g)
            idx = members[g]
            leave = max(ready.get(items[x].actor, 0) for x in idx)
            slowest = max(alone[x][1] for x in idx)
            for x in idx:
                moves[x] = leave + slowest - ready.get(items[x].actor, 0)
        ready[it.actor] = ready.get(it.actor, 0) + moves[k] + it.act_seconds
    return [(start, moves[k], fly) for k, (start, _, fly) in enumerate(alone)]


def plan_items(space: Space, items: Sequence[ActionItem]) -> list[ActionItem]:
    """给每个带目的地的条目算出移动耗时（一起走的取组里最慢的）。"""
    return [
        it.model_copy(update={"move_seconds": move})
        for it, (_, move, _) in zip(items, _moves(space, items), strict=True)
    ]


def build_activities(
    space: Space, player: str, now: int, items: Sequence[ActionItem]
) -> dict[str, Activity]:
    """把一份确认过的行动声明变成各实体进行中的行动。"""
    steps: dict[str, list[Step]] = {}
    for it, (start, move, fly) in zip(items, _moves(space, items), strict=True):
        assert it.id is not None
        targets = tuple(t.id for t in it.targets if t.kind == "entity" and t.id)
        steps.setdefault(it.actor, []).append(
            Step(
                item=it.id,
                targets=targets,
                start=start if it.destination is not None else None,
                to=it.destination,
                move=move,
                act=it.act_seconds,
                fly=fly,
                entry=it.entry,
                params=dict(it.params),
            )
        )
    return {
        eid: Activity(
            player=player, start=now, end=now + sum(s.move + s.act for s in ss), steps=tuple(ss)
        )
        for eid, ss in steps.items()
    }


def _along(step: Step, frac: float) -> Point:
    assert step.start is not None and step.to is not None
    a, b = step.start, step.to.pos
    if step.fly:
        return Point(
            x=a.x + (b.x - a.x) * frac, y=a.y + (b.y - a.y) * frac, z=a.z + (b.z - a.z) * frac
        )
    vertical = abs(b.z - a.z)
    total = vertical + math.hypot(b.x - a.x, b.y - a.y)
    if total <= 1e-9:
        return b
    done = total * frac
    if done <= vertical:
        z = a.z + math.copysign(done, b.z - a.z)
        return Point(x=a.x, y=a.y, z=z)
    h = (done - vertical) / (total - vertical)
    return Point(x=a.x + (b.x - a.x) * h, y=a.y + (b.y - a.y) * h, z=b.z)


def location_at(act: Activity, t: int, current: Location | None) -> Location | None:
    """进行中的行动在 t 时刻把实体带到了哪里。没有移动过就返回 current（原位置）。"""
    clock = act.start
    loc = current
    for s in act.steps:
        if s.to is not None and s.start is not None:
            if t >= clock + s.move:
                loc = s.to
            else:
                frac = (t - clock) / s.move if s.move > 0 else 1.0
                if frac <= 0:
                    return loc
                inside = (
                    loc.inside
                    if (loc is not None and not s.fly and _vertical_phase(s, frac))
                    else None
                )
                return Location(pos=_along(s, frac), inside=inside)
        clock += s.move + s.act
        if t < clock:
            return loc
    return loc


def _vertical_phase(step: Step, frac: float) -> bool:
    assert step.start is not None and step.to is not None
    a, b = step.start, step.to.pos
    vertical = abs(b.z - a.z)
    total = vertical + math.hypot(b.x - a.x, b.y - a.y)
    return total > 0 and total * frac <= vertical


def cut_time(activities: Mapping[str, Activity], now: int, min_round: int) -> int:
    """回合结束时刻：最早结束的行动，至少是 now + min_round。"""
    ends = [a.end for a in activities.values()]
    return max(now + min_round, min(ends) if ends else now)


def activities_of(state_activities: JsonValue) -> dict[str, Activity]:
    return {eid: Activity.model_validate(a) for eid, a in _obj(state_activities).items()}
