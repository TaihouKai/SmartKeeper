"""玩家间闲聊。不属于游戏内交流，不进事件日志，KP 看不到。"""

from __future__ import annotations

from typing import Protocol

from smartkeeper.contracts.base import Frozen


class ChatMessage(Frozen):
    id: int
    game_id: str
    sender: str
    recipient: str
    text: str
    created_at: str


class ChatStore(Protocol):
    def post(self, game_id: str, sender: str, recipient: str, text: str) -> ChatMessage: ...

    def conversation(
        self, game_id: str, a: str, b: str, since_id: int = 0
    ) -> list[ChatMessage]: ...

    def for_player(self, game_id: str, player: str, since_id: int = 0) -> list[ChatMessage]: ...
