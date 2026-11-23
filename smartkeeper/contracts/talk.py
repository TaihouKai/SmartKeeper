"""对话模式：两个实体之间的实时对话。对话内容是事件，状态由事件推出来。"""

from __future__ import annotations

from typing import Literal

from smartkeeper.contracts.base import Frozen

TalkStatus = Literal["invited", "active", "declined", "ended"]


class TalkMessage(Frozen):
    seq: int
    speaker: str  # 实体 id
    text: str


class Talk(Frozen):
    id: str
    round_no: int
    status: TalkStatus
    a_player: str  # 发起方
    a_entity: str
    b_entity: str
    b_player: str | None  # 对方是 NPC 时为 None，由 KP 扮演
    messages: tuple[TalkMessage, ...] = ()
