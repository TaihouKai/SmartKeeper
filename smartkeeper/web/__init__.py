"""鉴权、HTTP API、各模块的装配（`web/app.py` 是唯一的装配点）。"""

from smartkeeper.web.app import create_app

__all__ = ["create_app"]
