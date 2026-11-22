# `dice`

骰子表达式与掷骰。随机数只在这里产生；`engine` 调用它并把结果写成 `dice_roll` 事件。

- 依赖：`contracts`
- 接口：`DiceRoller(rng)`（实现 `contracts.Dice`）、`SystemRandomSource`、`SeededRandomSource`（测试用）、`parse` / `validate` / `bounds`
- 表达式：若干项用 `+`/`-` 连接，每项是 `NdM`、`dM` 或整数，例如 `1d100`、`3d6+2`、`2d6-1d4+1`
- 单独测试：`uv run pytest tests/dice`
