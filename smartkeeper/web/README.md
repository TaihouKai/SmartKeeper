# `web`

鉴权、HTTP API、各模块的装配（`web/app.py` 是唯一的装配点）。

- 依赖：`engine`、`kp`、`chat`、`notify` 的接口
- 接口：见 `__init__.py` 的导出（尚未实现）
- 单独测试：`uv run pytest tests/web`
