# 局域网部署（Windows）

部署副本在 `C:\SmartKeeper-deploy`（这个仓库的另一份克隆），和开发目录分开，开发时的改动不会影响正在跑的服务器。

- 配置：`%APPDATA%\SmartKeeper\server.json`（数据库、地图、剧本目录，端口，模型提供方和模型名，管理员密码哈希）。
- 密钥：`%APPDATA%\SmartKeeper\secrets\*.dpapi`，用 Windows DPAPI 加密，只有这台机器上的这个用户能解开。
  - `deepseek.dpapi`：DeepSeek（OpenAI 兼容）的 key；`anthropic.dpapi`：有的话就会设成 `ANTHROPIC_API_KEY`；`openai.dpapi`：有的话就会设成 `OPENAI_API_KEY`。
  - `session_secret.dpapi`：控制台会话签名用的随机密钥。
  - `admin_password.dpapi`：管理员密码的明文（只给 AI 自己查用）。
- 数据：`C:\SmartKeeper-deploy\data\`（数据库、日志 `server.log`、地图 `maps\`、剧本 `scenarios\`）。
- 启动：计划任务 “SmartKeeper Server”（登录时启动，失败自动重启），运行 `deploy\start_server.ps1`。
- 更新：在部署目录里 `git pull`、`uv sync`、`cd frontend; npm ci; npm run build`，然后重启计划任务。
- 端口：8000，防火墙入站规则 “SmartKeeper 8000”。

价格：`server.json` 里可以加 `"model_prices": {"gpt-6-luna": [0.10, 0.01, 0.50]}`（美元 / 百万 token：输入、命中缓存的输入、输出；模型名按前缀匹配），管理台的 LLM 调用面板据此算花费。

换模型：改 `server.json` 里的 `judge_provider` / `judge_model` / `writer_provider` / `writer_model`，改完重启计划任务。provider 有三类：
- `anthropic`（Claude）：key 存成 `anthropic.dpapi`。默认允许联网搜索。
- `openai`（ChatGPT，走 Responses API）：key 存成 `openai.dpapi`。默认允许联网搜索。
- `openai_compat`（DeepSeek 等 OpenAI 兼容接口）：`openai_base_url` 和 `openai_key_secret`。默认不联网；兼容服务实现了 Responses API 的 web_search 时，在 `server.json` 里加 `"openai_compat_web_search": true`。

每一局还可以在控制台的局设置里关掉“联网搜索”。
