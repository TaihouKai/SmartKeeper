# `dice`

掷骰的随机源。随机数只在这里产生；`engine` 调用它并把结果写成 `dice_roll` 事件。

- 依赖：`contracts`
- 接口：`DiceRoller(rng)`（实现 `contracts.Dice`：`faces(个数, 面数)` 返回每颗骰子的点数）、`SystemRandomSource`、`SeededRandomSource`（测试用）
- 骰子公式（`3d6+2`、`1d str`、`highest(4, 6, 3)`）属于规则包的公式语言，由 `rules` 解析和求值；`rules` 求值时通过 engine 传进来的 `faces` 回调拿到点数
- 单独测试：`uv run pytest tests/dice`
