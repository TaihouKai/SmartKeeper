"""鉴权、HTTP API、各模块的装配（`web/app.py` 是唯一的装配点）。"""

from smartkeeper.web.app import Settings, build_services, create_app
from smartkeeper.web.auth import hash_password
from smartkeeper.web.schema import alembic_config, combined, migrate

__all__ = [
    "Settings",
    "alembic_config",
    "build_services",
    "combined",
    "create_app",
    "hash_password",
    "migrate",
]
