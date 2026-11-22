"""玩家间闲聊的存储；不进事件日志，不属于 engine，kp 不依赖它。"""

from smartkeeper.chat.store import SqlChatStore
from smartkeeper.chat.store import metadata as chat_metadata

__all__ = ["SqlChatStore", "chat_metadata"]
