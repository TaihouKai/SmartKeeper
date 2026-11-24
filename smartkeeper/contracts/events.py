"""事件日志的数据类型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import JsonValue, model_validator

from smartkeeper.contracts.base import Frozen

EventType = Literal[
    "broadcast",
    "pm_kp",
    "action_declared",
    "claim_check",
    "dice_roll",
    "spatial_query",
    "adjudication",
    "state_patch",
    "feedback",
    "round_opened",
    "round_closed",
    "character_submitted",
    "character_approved",
    "character_rejected",
    "identity_assigned",
    "admin_override",
    "summary",
    "talk_invited",
    "talk_accepted",
    "talk_declined",
    "talk_message",
    "talk_ended",
    "plan_started",
    "entry_used",
    "entry_noticed",
    "plan_done",
    "reaction_requested",
    "reaction_resolved",
]

KP = "kp"
ENGINE = "engine"
ADMIN = "admin"
PUBLIC = "public"

# 受众：玩家 id、"kp" 或 "public"。
type Audience = str


class Visibility(Frozen):
    kind: Literal["public", "players", "kp_only"]
    players: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> Visibility:
        if self.kind == "players" and not self.players:
            raise ValueError("players visibility needs at least one player")
        if self.kind != "players" and self.players:
            raise ValueError("only players visibility lists players")
        return self

    @staticmethod
    def public() -> Visibility:
        return Visibility(kind="public")

    @staticmethod
    def kp_only() -> Visibility:
        return Visibility(kind="kp_only")

    @staticmethod
    def to(*players: str) -> Visibility:
        return Visibility(kind="players", players=tuple(sorted(set(players))))

    def visible_to(self, audience: Audience) -> bool:
        if audience == KP:
            return True
        if self.kind == "public":
            return True
        if audience == PUBLIC:
            return False
        return self.kind == "players" and audience in self.players


class NewEvent(Frozen):
    """待追加的事件；seq、id、时间由 eventlog 分配。"""

    type: EventType
    actor: str | None
    visibility: Visibility
    payload: dict[str, JsonValue] = {}


class Event(Frozen):
    id: int
    game_id: str
    round_no: int
    seq: int
    type: EventType
    actor: str | None
    visibility: Visibility
    payload: dict[str, JsonValue]
    created_at: datetime
