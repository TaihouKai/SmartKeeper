# `copilot`

建卡助手：玩家在建卡页（局里，或者规则书下的角色编辑页）问问题，助手回答；要写或改条目、字段时，给出可以一键应用的修改。

- **和 KP 分开**：不读对局内容、不读 KP 的记事，只看规则书正文、规则书结构、语法手册和玩家正在写的卡。问答历史只在页面里，不存。
- **接口**：`Copilot(llm, rules, model, describe, messages).ask(pack, question, game_id=None) -> CopilotAnswer`。
  - `llm`：`LLMClient`（用 KP 那套模型配置，但是单独的调用，purpose 是 `copilot`）。
  - `rules`：`Rules` 接口，用来列语法手册（`docs()`）和检查给出的修改（`validate_sheet`）。
  - `describe`：把规则包写成结构说明的函数（web 装配时传 `rules.render`）。
  - `messages`：界面的翻译表（语言 -> 文案键 -> 文字），用来把语法手册和问题代码写成文字。
- **检查**：每处修改放进玩家现在的卡里按规则书检查，只留这处修改自己的问题；有问题时把问题告诉模型改一次，还不行就带着问题返回，界面上显示出来。
- **依赖**：只依赖 `contracts`。
- **单独测**：`pytest tests/copilot`（用假的 LLM）。
