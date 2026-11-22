# `web`

鉴权、HTTP API、各模块的装配。`app.py` 是唯一的装配点（`build_services`）。

- 依赖：`engine`、`kp`、`chat`、`notify` 的接口（装配时创建全部实现）
- `cli.py`：不经过网站、在命令行跑建角、开场和若干轮：`uv run python -m smartkeeper.web.cli demo --players 2 --rounds 1`
- 单独测试：`uv run pytest tests/web`
