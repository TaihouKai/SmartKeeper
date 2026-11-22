# `rules`

规则包的存储与版本、校验、公式求值、检定结算。不依赖 LLM，不产生随机数。

- 依赖：`contracts`（骰子表达式校验经构造函数注入的 `Dice` 接口）
- 接口：
  - `RulesService(dice)`：实现 `contracts.Rules`。校验规则包、公式、角色卡；求推导值；按成功条件结算检定（骰子由 engine 掷好传入）；渲染规则书。
  - `SqlRulePackStore(db, rules)`：实现 `contracts.RulePackStore`。每次保存是一个不可变的新版本，保存前必须通过校验（含例题验算）。
  - `export_pack` / `parse_import`：导入导出文件格式 `{"format": "smartkeeper.rulepack", "format_version": 1, "pack": {...}}`。
- 公式语言（`formula.py`）：数字、`"文字"`、`+ - * /`、比较（结果 1/0）、括号、字段引用 `name` / `self.name`，函数只有 `floor ceil round min max lookup`。不执行任何外部代码。
- 推导值 = (公式 + 全部加法修正) × 全部乘法修正。修正来自分组条目里带公式的效果和状态上的修正。
- 单独测试：`uv run pytest tests/rules`（用 `tests/fixtures` 的假骰子）
