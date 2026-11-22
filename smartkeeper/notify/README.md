# `notify`

webhook 通知。消息里不含任何游戏内容和 token。

- 依赖：`contracts`
- 接口：`WebhookNotifier(post=..., background=True)`，`send(url, code, lang, **params)`。代码：`round.started`（玩家 webhook）、`round.review`（管理员 webhook）、`game.ended`。payload 同时带 `text` 和 `content`（适配 Slack 和 Discord），以及 `code`、`params`。
- 在 `web/app.py` 里接到 KP 的 `on_published` / `on_review` 钩子上。发送在后台线程里，失败只记日志。
- 单独测试：`uv run pytest tests/notify`
