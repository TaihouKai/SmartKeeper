"""裁定 JSON 及相关结果类型。"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, JsonValue

from smartkeeper.contracts.base import Frozen
from smartkeeper.contracts.geometry import Location, Point


class PatchOp(Frozen):
    """RFC 6902 JSON Patch 的一个操作。"""

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    op: Literal["add", "remove", "replace", "move", "copy", "test"]
    path: str
    value: JsonValue = None
    from_: str | None = Field(default=None, alias="from")


class Outcome(Frozen):
    player_id: str
    resolves: tuple[str, ...] = ()
    result: str
    observations: tuple[str, ...] = ()


class Encounter(Frozen):
    players: tuple[str, ...]
    observed_by: dict[str, str]


class Movement(Frozen):
    entity: str
    to: Point
    inside: str | None = None
    because: str  # 行动条目 id，或 npc:<实体 ID>
    ability: str | None = None  # 依据某个能力的特殊移动


class AreaEffect(Frozen):
    query_id: str
    affected: tuple[str, ...]


class MemoryEntryIn(Frozen):
    entities: tuple[str, ...] = ()
    features: tuple[str, ...] = ()
    text: str


class Adjudication(Frozen):
    """一回合的裁定。推进多久由引擎决定（最早结束的行动），KP 只裁定这段时间里发生的事。"""

    outcomes: tuple[Outcome, ...]
    encounters: tuple[Encounter, ...] = ()
    movements: tuple[Movement, ...] = ()
    area_effects: tuple[AreaEffect, ...] = ()
    public_events: tuple[str, ...] = ()
    state_patch: tuple[PatchOp, ...] = ()
    memory_entries: tuple[MemoryEntryIn, ...] = ()
    kp_notes: str | None = None
    game_over: bool = False


class DiceResult(Frozen):
    expr: str
    rolls: tuple[int, ...]  # 每颗骰子的点数（含 highest/lowest 舍弃的）
    total: float
    seq: int | None = None  # 对应的 dice_roll 事件


class CheckResult(Frozen):
    entity: str
    check: str
    roll: DiceResult
    target: float
    difficulty: float | None = None
    opponent: str | None = None
    opp_roll: DiceResult | None = None
    opp_target: float | None = None
    level: str
    reason: str = ""


class AdHocCheck(Frozen):
    """规则包没有覆盖时 KP 声明的临时检定。"""

    dice: str  # 骰子公式，可以引用执行检定的实体的字段
    target: float
    success_when: Literal["roll<=target", "roll>=target"] = "roll<=target"


class Opening(Frozen):
    broadcast: str
    messages: dict[str, str]  # 玩家 id -> 开场私信
    positions: dict[str, Location] = {}  # 实体 id -> 初始位置；剧本没有指定的
