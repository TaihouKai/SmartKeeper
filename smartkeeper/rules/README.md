# `rules`

规则包的存储与版本、校验、公式求值、检定结算。不依赖 LLM，不产生随机数。

- 依赖：`contracts`（骰子表达式校验经构造函数注入的 `Dice` 接口）
- 接口：
  - `RulesService()`：实现 `contracts.Rules`。校验规则包、公式、角色卡；求推导值；求值骰子公式（`roll`，点数来自 engine 传入的 `faces`）；按成功条件结算检定；渲染规则书。
  - `SqlRulePackStore(db, rules)`：实现 `contracts.RulePackStore`。每次保存是一个不可变的新版本，保存前必须通过校验（含例题验算）。另外每个规则包可以有一份不校验内容的草稿（save_draft / get_draft / delete_draft），保存版本时删除。
  - `export_pack` / `parse_import`：导入导出文件格式 `{"format": "smartkeeper.rulepack", "format_version": 1, "pack": {...}}`。
- 公式语言（`formula.py`）：数字、`"文字"`、`+ - * /`、比较（结果 1/0）、括号、字段引用 `name` / `self.name`、掷骰 `NdM`（只在给了 `faces` 时允许），函数见 `FUNCTIONS`（前端“公式速查”同一张表，有测试保证一致）。不执行任何外部代码。
- 推导值 = (公式 + 全部加法修正) × 全部乘法修正。修正来自分组条目里带公式的效果和状态上的修正。
- 分组的固定条目（`GroupDef.presets`）按字段条件生效，不存进卡：`EntityContext.groups()` 把生效的固定条目排在玩家条目前面，推导值修正和 `full_sheet` 都用它。
- 单独测试：`uv run pytest tests/rules`（用 `tests/fixtures` 的假骰子）
