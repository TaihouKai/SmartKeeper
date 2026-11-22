"""裁定 JSON 在应用前的校验（不涉及空间的部分）。任何一项不通过，整份裁定被拒绝。"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from smartkeeper.contracts import (
    Adjudication,
    Frozen,
    PatchOp,
    Problem,
)

ENGINE_ONLY_PATHS = ("/game_minutes", "/map")
_POS_PATH = re.compile(r"^/entities/[^/]+/(pos|inside)(/|$)")
_ENTITY_PATH = re.compile(r"^/entities/([^/]+)$")


def check_patch_paths(ops: Sequence[PatchOp], existing: set[str]) -> list[Problem]:
    """KP 的 state_patch 不能写时间和地图，也不能绕过 movements 改位置。"""
    problems: list[Problem] = []
    for i, op in enumerate(ops):
        paths = [op.path] + ([op.from_] if op.from_ else [])
        for path in paths:
            if any(path == p or path.startswith(p + "/") for p in ENGINE_ONLY_PATHS):
                problems.append(
                    Problem(
                        code="adj.patch_engine_only",
                        path=f"state_patch[{i}]",
                        params={"path": path},
                    )
                )
            if _POS_PATH.match(path):
                problems.append(
                    Problem(
                        code="adj.patch_position", path=f"state_patch[{i}]", params={"path": path}
                    )
                )
            m = _ENTITY_PATH.match(path)
            if m and m.group(1) in existing and op.op in ("replace", "add", "move", "copy"):
                # 整个替换已有实体等于绕过位置规则和模板历史，不允许
                problems.append(
                    Problem(
                        code="adj.patch_replace_entity",
                        path=f"state_patch[{i}]",
                        params={"path": path},
                    )
                )
    return problems


class ItemInfo(Frozen):
    player: str
    actor: str
    targets: frozenset[str]


def check_sources(
    adj: Adjudication,
    *,
    required: Sequence[str],
    items: Mapping[str, ItemInfo],
    controls: Mapping[str, set[str]],
    entities: set[str],
) -> list[Problem]:
    """行动来源：outcome 与 resolves、movements 的 because。

    - 每个需要行动的玩家恰好一条 outcome，resolves 只能列他本轮确认过的条目。
    - movement 的 because 必须是本轮确认过的条目，或 npc:<不受玩家控制的实体>。
    - 玩家控制的实体因别的玩家的条目移动（被推开），那个条目必须以该实体为目标；
      否则就是借别人的条目自主移动，拒绝。
    """
    problems: list[Problem] = []
    seen: dict[str, int] = {}
    for i, o in enumerate(adj.outcomes):
        seen[o.player_id] = seen.get(o.player_id, 0) + 1
        if o.player_id not in required:
            problems.append(
                Problem(
                    code="adj.outcome_unknown_player",
                    path=f"outcomes[{i}]",
                    params={"player": o.player_id},
                )
            )
            continue
        for rid in o.resolves:
            info = items.get(rid)
            if info is None or info.player != o.player_id:
                problems.append(
                    Problem(
                        code="adj.resolves_foreign_item",
                        path=f"outcomes[{i}]",
                        params={"item": rid},
                    )
                )
    for pid in required:
        if seen.get(pid, 0) != 1:
            problems.append(
                Problem(
                    code="adj.outcome_count",
                    path="outcomes",
                    params={"player": pid, "count": seen.get(pid, 0)},
                )
            )
    owner = {e: pid for pid, ents in controls.items() for e in ents}
    for i, mv in enumerate(adj.movements):
        path = f"movements[{i}]"
        if mv.entity not in entities:
            problems.append(Problem(code="adj.unknown_entity", path=path, params={"id": mv.entity}))
            continue
        if mv.because.startswith("npc:"):
            npc = mv.because[4:]
            if npc not in entities or npc in owner:
                problems.append(Problem(code="adj.because_not_npc", path=path, params={"id": npc}))
            continue
        info = items.get(mv.because)
        if info is None:
            problems.append(
                Problem(code="adj.because_unknown_item", path=path, params={"item": mv.because})
            )
            continue
        mover = owner.get(mv.entity)
        if mover is not None and mover != info.player and mv.entity not in info.targets:
            problems.append(
                Problem(
                    code="adj.because_foreign_item",
                    path=path,
                    params={"item": mv.because, "entity": mv.entity},
                )
            )
    return problems


def check_memory_entities(adj: Adjudication, entities: set[str]) -> list[Problem]:
    problems: list[Problem] = []
    for i, m in enumerate(adj.memory_entries):
        for e in m.entities:
            if e not in entities:
                problems.append(
                    Problem(
                        code="adj.memory_unknown_entity",
                        path=f"memory_entries[{i}]",
                        params={"id": e},
                    )
                )
        if not m.text.strip():
            problems.append(Problem(code="adj.memory_empty", path=f"memory_entries[{i}]"))
    return problems
