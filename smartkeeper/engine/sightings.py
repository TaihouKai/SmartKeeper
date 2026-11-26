"""目击：哪一方在游戏内什么时候掌握了谁的位置。技能设置的 seen_within（多少分钟之内掌握过对象的位置）按它判。

“一方”是一个玩家（他控制的所有实体算一起：同伴看见了就是这一方看见了），或者一个 NPC 实体自己。
记在世界状态里被掌握的那个实体上：entities.<id>.seen_at = {一方: 游戏内秒}，每一方只留最新的一次。来源：

- sight：每轮开始时引擎按此刻的感知，给每一方察觉到的每个实体记一次；
- told：裁定里写的转告（A 把 X 在哪告诉 B）：把 A 关于 X 的那次目击复制给 B，时间还是 A 当初目击的时间；
  A 没有就什么都不给——编不出来；
- locate：技能脚本 target.locate()（占卜、远视、使魔回报……）：使用者这一方在生效那一刻掌握了对象的位置。

都经由 patch 记进日志，所以同一份日志总得出同样的结果。
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from pydantic import JsonValue

from smartkeeper.contracts import PatchOp, State
from smartkeeper.engine.space import Space

KEY = "seen_at"


def _obj(v: JsonValue) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], v) if isinstance(v, dict) else {}


def stamps(state: State, target: str) -> dict[str, int]:
    """各方最近一次掌握这个实体位置的游戏内秒。"""
    raw = _obj(_obj(_obj(state.get("entities")).get(target)).get(KEY))
    return {k: int(v) for k, v in raw.items() if isinstance(v, int) and not isinstance(v, bool)}


def side_of(state: State, entity: str) -> str:
    """实体属于哪一方：控制它的玩家；NPC 是它自己。"""
    for pid, ents in _obj(state.get("controls")).items():
        if isinstance(ents, list) and entity in ents:
            return str(pid)
    return entity


def perceived(space: Space, side: str) -> set[str]:
    """这一方此刻察觉到的实体（不含自己这一方的）。"""
    if side in space.controls:
        return space.player_perceived(side)
    return set(space.perceived_by(side)) - {side}


def observe(space: Space, dead: Callable[[str], bool]) -> dict[str, set[str]]:
    """每一方（玩家，和活着的 NPC）此刻察觉到的实体。"""
    out: dict[str, set[str]] = {}
    for pid in sorted(space.controls):
        seen = perceived(space, pid)
        if seen:
            out[pid] = seen
    for eid in sorted(space.entities):
        if eid in space.owner or dead(eid):
            continue
        seen = perceived(space, eid)
        if seen:
            out[eid] = seen
    return out


def stamp_ops(state: State, marks: Mapping[str, Mapping[str, int]]) -> list[PatchOp]:
    """marks：被掌握的实体 -> {一方: 游戏内秒}。比已有的新才记；返回改动（每个实体一条）。"""
    ops: list[PatchOp] = []
    entities = _obj(state.get("entities"))
    for target in sorted(marks):
        if target not in entities:
            continue
        have = stamps(state, target)
        merged = dict(have)
        for side, sec in marks[target].items():
            if side not in merged or merged[side] < sec:
                merged[side] = sec
        if merged != have:
            value: dict[str, JsonValue] = {k: merged[k] for k in sorted(merged)}
            ops.append(PatchOp(op="add", path=f"/entities/{target}/{KEY}", value=value))
    return ops


def sight_marks(found: Mapping[str, set[str]], seconds: int) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for side, targets in found.items():
        for t in targets:
            out.setdefault(t, {})[side] = seconds
    return out


def told_marks(state: State, source: str, to: str, about: str) -> dict[str, dict[str, int]]:
    """转告：source 这一方关于 about 的目击复制给 to 这一方（时间不变）；source 没有就是空的。"""
    sec = stamps(state, about).get(source)
    return {} if sec is None else {about: {to: sec}}


def minutes_since(state: State, space: Space, side: str, target: str, now: int) -> float | None:
    """这一方最近一次掌握对象的位置是多少分钟前：此刻就察觉得到是 0；从没掌握过是 None。"""
    if target in perceived(space, side):
        return 0.0
    last = stamps(state, target).get(side)
    return None if last is None else max(0.0, (now - last) / 60)
