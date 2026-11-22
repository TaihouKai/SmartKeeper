# `engine`

`Engine` 门面：唯一的游戏逻辑入口。HTTP API 和 KP 只经由这里读写对局。

- 依赖：各模块的接口，经构造函数注入（`EventLog`、`RulePackStore`、`Rules`、`World`、`RoundMachine`、`Dice`、`MapStore`、`Spatial`、`HandleStore`）
- 自己的表：`game`、`player`、`round`（`repo.py`）
- 主要方法：建角（`assign_identity`、`submit_character`、`approve_character`/`reject_character`）、`start_game`、行动期（`post_broadcast`、`post_kp_chat`、`declare_action`）、结算（`close_round`、`roll`、`run_check`、`apply_adjudication`、`set_feedback_draft`、`publish_round`、`rerun_round`）、读取（`view_for`、`world_state`、`sheets`、`rulebook`）
- 裁定在 `apply_adjudication` 时校验并存为草稿，`publish_round` 时才写入事件；所以重跑和人工修改只替换草稿，日志里不会有作废的状态变更。
- 空间（`space.py`）：把世界状态翻成 `Body` 交给 spatial。`scene`（在场列表、已知地图变化）、`state_slice`（给澄清对话）、`spatial_query`（写 `spatial_query` 事件）、`refresh_handles`、`resolve_mentions`（`@[文字](ref)` → 实体 ID）。裁定校验含移动距离与终点、相遇的感知、范围效果对象必须来自查询结果。
- 剧本的结构化部分写在 Markdown 的 YAML front matter 里（`scenario.py`）。
- 单独测试：`uv run pytest tests/engine`（各模块真实实现加内存 SQLite；按规则包 × 人数参数化）
