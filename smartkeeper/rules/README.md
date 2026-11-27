# `rules`

规则包的存储与版本、校验、公式求值、检定结算。不依赖 LLM，不产生随机数。

- 依赖：`contracts`、`lang`（公式和技能脚本的语法）
- 接口：
  - `RulesService()`：实现 `contracts.Rules`。校验规则包、公式、角色卡；求推导值；求值骰子公式（`roll`，点数来自 engine 传入的 `faces`）；按成功条件结算检定；渲染规则书。
  - `SqlRulePackStore(db, rules)`：实现 `contracts.RulePackStore`。每次保存是一个不可变的新版本，保存前必须通过校验（含例题验算）。另外每个规则包可以有一份不校验内容的草稿（save_draft / get_draft / delete_draft），保存版本时删除。
  - `export_pack` / `parse_import`：导入导出文件格式 `{"format": "smartkeeper.rulepack", "format_version": 1, "pack": {...}}`。
- 公式和技能脚本的语法在 `lang` 包；这里负责名字解析（`EntityContext`：字段、推导值、`self.x`、`this.<列>`、`<模板>.x`、`target.x`）、校验（`validation.check_formula` / `check_script`）和技能脚本的规划（`scripts.plan_script`）。
- 推导值 = 公式算出的基础值，再依次经过各个效果的公式（固定条目 → 玩家写的条目按 priority → 状态）。效果公式里写这个推导值自己的名字表示到上一步为止的值。
- 分组的固定条目（`GroupDef.presets`）按字段条件生效，不存进卡：`EntityContext.groups()` 把生效的固定条目排在玩家条目前面，推导值修正和 `full_sheet` 都用它。
- 单独测试：`uv run pytest tests/rules`（用 `tests/fixtures` 的假骰子）
- 资料库（`lore.py`）：从 SillyTavern 世界书（World Info JSON）导入（`from_world_info`），校验标题、关键词、正文。
