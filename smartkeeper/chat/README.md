# `chat`

玩家之间的场外闲聊。不进事件日志，不属于 engine；kp 和 engine 都不导入它（import-linter 强制），KP 看不到，控制台日志也不含它。

- 依赖：`contracts`
- 接口：`SqlChatStore(db)` 实现 `contracts.ChatStore`：`post`、`conversation`、`for_player`
- 单独测试：`uv run pytest tests/chat`
