# `world`

世界状态的折叠、校验与状态到期。世界状态是一个 JSON 文档，由 `state_patch` 事件按顺序折叠得到。

- 依赖：`contracts`；`rules` 的接口（经构造函数注入）
- 接口：`WorldService(rules)` 实现 `contracts.World`：`initial_state`、`apply`（RFC 6902，失败抛 `ValidationFailed`）、`validate`（顶层结构、控制关系、每个实体的角色卡）、`expire`、`canonical`
- 单独测试：`uv run pytest tests/world`（用假的 Rules）
