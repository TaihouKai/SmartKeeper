# 局域网部署（Windows）

部署副本在 `C:\SmartKeeper-deploy`（这个仓库的另一份克隆），和开发目录分开，开发时的改动不会影响正在跑的服务器。

- 配置：`%APPDATA%\SmartKeeper\server.json`（数据库、地图、剧本目录，端口，模型提供方和模型名，管理员密码哈希）。
- 密钥：`%APPDATA%\SmartKeeper\secrets\*.dpapi`，用 Windows DPAPI 加密，只有这台机器上的这个用户能解开。
  - `deepseek.dpapi`：DeepSeek（OpenAI 兼容）的 key；`anthropic.dpapi`：有的话就会设成 `ANTHROPIC_API_KEY`。
  - `session_secret.dpapi`：控制台会话签名用的随机密钥。
  - `admin_password.dpapi`：管理员密码的明文（只给 AI 自己查用）。
- 数据：`C:\SmartKeeper-deploy\data\`（数据库、日志 `server.log`、地图 `maps\`、剧本 `scenarios\`）。
- 启动：计划任务 “SmartKeeper Server”（登录时启动，失败自动重启），运行 `deploy\start_server.ps1`。
- 更新：在部署目录里 `git pull`、`uv sync`、`cd frontend; npm ci; npm run build`，然后重启计划任务。
- 端口：8000，防火墙入站规则 “SmartKeeper 8000”。

换模型：改 `server.json` 里的 `judge_provider` / `judge_model` / `writer_provider` / `writer_model`；
用 Claude 时把 key 加密存成 `anthropic.dpapi`，provider 写 `anthropic`。改完重启计划任务。
