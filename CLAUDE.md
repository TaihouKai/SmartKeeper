# SmartKeeper：给 AI 的说明

由 LLM 担任 KP 的异步文字跑团引擎。完整设计见 [docs/design.md](docs/design.md)，这里只是摘要；冲突时以设计文档和本人最新的口头指示为准。

## 常用命令

| 命令 | 作用 |
| --- | --- |
| `uv sync` | 安装后端依赖（Python 3.12） |
| `cd frontend && npm install` | 安装前端依赖 |
| `uv run python scripts/check.py` | **全部检查**：格式、lint、pyright 严格、依赖方向、私有导入、翻译、专有名词、后端测试、前端类型与测试 |
| `uv run python scripts/check.py --fix` | 同上，先自动格式化 |
| `uv run pytest tests/<模块>` | 单独测一个模块 |
| `uv run pytest -m live` | 需要真模型或联网的测试（默认不跑） |
| `uv run uvicorn smartkeeper.web:create_app --factory --reload` | 本地起后端 |
| `cd frontend && npm run dev` | 本地起前端（代理 `/api` 到 8000） |

每次改动后都跑全部检查，不通过不算完成。类型错误、依赖方向违规、漏翻译、专有名词违规与测试失败同等对待。

## 读前须知（摘要）

- 按设计文档“里程碑”顺序做，每个里程碑结束时汇报。
- “设计约束”和模块通信规则要改必须先问；其余内容可以质疑，发现问题就提出修改。
- 第一个试玩剧本只是测试用例。写代码前先问：换成 COC 或 DND 还成立吗？不成立就应该是规则包里的数据。
- 需要只有本人能提供的内容（试玩规则包、API Key）时停下来问，不要自己编。
- 不写死玩家人数。没写到的细节取最简单的实现，并在汇报里列出假设。

## 设计约束（摘要）

1. LLM 不直接改状态：输出 JSON → schema 校验 → `engine` 应用。
2. 给 LLM 的对局内容只能经由 `engine` 的按受众过滤的读取接口（`view_for`、`state_slice` 等）。
3. 随机数只由 `engine` 产生，并写入事件日志。
4. `engine` 确定性：同一事件日志 + 同一规则包版本 + 同一地图文件 → 同一世界状态。
5. 引擎、数据结构、接口、prompt、界面里不出现只对某一套规则成立的概念。
6. `KP.run_round` 的接口不依赖“一次调用处理全体玩家”。
7. 管理权限只来自管理控制台会话，玩家 token 不带任何管理权限。

## 模块通信规则（摘要）

1. 只能导入别的模块的包本身（`smartkeeper.<模块>`），不得导入其子模块。`scripts/check_private_imports.py` 强制。
2. 跨模块只传 `contracts` 里的不可变数据类型。
3. 依赖经构造函数注入，所有实现只在 `smartkeeper/web/app.py` 装配。
4. 依赖方向见 `.importlinter`（由设计文档的依赖表生成），import-linter 强制。
5. 每个接口附带内存版或假实现；`pytest tests/<模块>` 不联网、不加载其他模块的真实实现。
6. 前后端只通过 HTTP API；前端 API 类型由 OpenAPI 生成（`npm run gen:api`）。
7. 单进程直接调用，不引入队列或微服务。
8. 先定接口和数据类型，再写实现。

## 目录约定

- `smartkeeper/<模块>/`：每个模块一个包，带 README（接口、依赖、怎么单独测）。
- `tests/<模块>/`：对应模块的测试；`tests/fixtures/` 放两份自制夹具规则包和手写小地图。
- `rulepacks/`、`scenarios/`：规则包数据和剧本，是唯一允许出现具体世界观专有名词的地方（另有 `docs/`）。专有名词表在 `scripts/proper_nouns.txt`。
- `frontend/src/i18n/{zh,en}.json`：全部界面文字。源码里不写死文案，后端只返回消息代码和参数。
- 文件保持小而职责单一。
