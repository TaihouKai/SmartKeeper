# `memory`

记事条目的存储与按实体检索。条目只是索引，可以从事件日志里的裁定事件重建（`Engine.rebuild_memory`）。

- 依赖：`contracts`
- 接口：`SqlMemoryStore(db)` 实现 `contracts.MemoryStore`。`recall` 返回同时标了其中任意两个实体的条目，以及标了某个行动者本人和某个相关地物的条目。
- 单独测试：`uv run pytest tests/memory`
