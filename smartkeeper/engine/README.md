# `engine`

`Engine` 门面：唯一的游戏逻辑入口。HTTP API 和 KP 只经由这里读写对局。

- 依赖：各模块的接口，经构造函数注入（`EventLog`、`RulePackStore`、`Rules`、`World`、`RoundMachine`、`Dice`、`MapStore`、`Spatial`、`HandleStore`）
- 自己的表：`game`、`player`、`round`（`repo.py`）
- 主要方法：建角（`assign_identity`、`submit_character`、`approve_character`/`reject_character`）、`start_game`、行动期（`post_broadcast`、`post_kp_chat`、`declare_action`）、结算（`close_round`、`roll`、`run_check`、`apply_adjudication`、`set_feedback_draft`、`publish_round`、`rerun_round`）、读取（`view_for`、`world_state`、`sheets`、`rulebook`）
- 裁定在 `apply_adjudication` 时校验并存为草稿，`publish_round` 时才写入事件；所以重跑和人工修改只替换草稿，日志里不会有作废的状态变更。
- 空间（`space.py`）：把世界状态翻成 `Body` 交给 spatial。`scene`（在场列表、已知地图变化）、`state_slice`（给澄清对话）、`spatial_query`（写 `spatial_query` 事件）、`refresh_handles`、`resolve_mentions`（`@[文字](ref)` → 实体 ID）。裁定校验含移动距离与终点、相遇的感知、范围效果对象必须来自查询结果。
- 连续时间（`timeline.py`）：移动耗时（能飞走直线，不能飞先上下再平地）、进行中的行动（世界状态 `/activities`）、某一时刻的位置、回合结束时刻。`close_round` 把确认的行动变成进行中的行动，结束时刻取最早做完的那个；`plan_adjudication` 把移动中的实体推到那一刻，并要求做完了的、受到影响的玩家都有结果；有结果的玩家的行动到此结束，其余继续、不被通知。
- 玩家自己的时间（`player_seconds`）和看到的世界（`_player_state`）：行动进行中的玩家看到的是他上一次被通知时那一刻的世界。
- 对话模式（`start_talk`、`answer_talk`、`say`、`end_talk`、`talks`）：状态由 `talk_*` 事件推出来；有进行中的对话时不结算。
- 情报（`intel.py`）：`intel_gained` 事件，只给得知的玩家看；来源是规则包的“看见就知道”（`_insights`，每轮开始）、分组定了暴露条件的技能被认出来（`_noticed_events`）、裁定的 `intel`。`player_intel` 合并出“我知道的”，`known_intel_all` 给 KP。
- 剧本的结构化部分写在 Markdown 的 YAML front matter 里（`scenario.py`）。
- 单独测试：`uv run pytest tests/engine`（各模块真实实现加内存 SQLite；按规则包 × 人数参数化）
