# `rounds`

回合状态机：`collecting → adjudicating → review → published`。转换表在 `machine.py` 的 `TRANSITIONS`。

- 依赖：`contracts`
- 接口：`RoundStateMachine` 实现 `contracts.RoundMachine`；非法转换抛 `IllegalState`
- 单独测试：`uv run pytest tests/rounds`
