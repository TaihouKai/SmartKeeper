# `web`

鉴权、HTTP API、各模块的装配。

- `app.py`：唯一的装配点。`build_services` 创建全部实现（启动时先跑数据库迁移），`create_app` 挂上路由、错误处理和前端静态文件；启动时自动重跑停在“裁定中”的回合。
- `services.py`：装配好的实现的类型（只是类型，实例在 app.py 里创建）。
- `auth.py`：`require_player`（HttpOnly cookie 或 Bearer token）和 `require_admin`（签名的会话 cookie，路径限定 /api/admin）是仅有的两个权限检查点。登录限流。
- `routes_player.py` / `routes_admin.py`：设计文档“接口”一节的 HTTP API。玩家接口里不出现实体 ID（换成玩家自己的 ref），坐标附带经纬度。错误只返回消息代码和参数。
- `schema.py` + `migrations/`：Alembic 迁移。改了表结构后运行 `uv run python scripts/make_migration.py "说明" --rev 000N`。
- `scripted.py`：provider=fake 时的脚本化假 KP，用于离线演示和浏览器端到端测试。
- `cli.py`：命令行跑建角、开场和若干轮。
- 单独测试：`uv run pytest tests/web`
