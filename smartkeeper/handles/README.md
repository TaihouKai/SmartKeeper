# `handles`

代号的存储。每个玩家一套，代号在该玩家这里唯一且稳定。

- 依赖：`contracts`
- 接口：`SqlHandleStore(db)` 实现 `contracts.HandleStore`：`ensure`（首次感知时分配临时代号 `#n`）、`set_label`（`by_player=False` 是“外观代号”调用命名，不覆盖玩家改过的名字，重名自动加序号；`by_player=True` 是玩家改名，重名拒绝）、`set_note`、`by_ref`、`list`
- `ref` 是给玩家的不透明引用：界面和 API 里只出现 ref，不出现实体 ID，所以 PC 和 NPC 不可区分。
- 单独测试：`uv run pytest tests/handles`
