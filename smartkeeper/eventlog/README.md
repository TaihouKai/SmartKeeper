# `eventlog`

只追加的事件表，可见性过滤的唯一实现。

- 依赖：`contracts`
- 接口：`SqlEventLog(db)` 实现 `contracts.EventLog`：`append`（一批事件一个事务，`seq` 局内严格递增）、`view_for(game, audience)`（`audience` 为玩家 id、`"kp"`、`"public"`；匿名广播在非 KP 视图里隐去 `actor`）、`get`（不过滤，只供 engine 内部用）
- 过滤在 SQL 里做一遍，再在内存里按 `Visibility.visible_to` 复核一遍。
- 单独测试：`uv run pytest tests/eventlog`（内存 SQLite，含可见性属性测试）
