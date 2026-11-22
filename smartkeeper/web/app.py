"""唯一的装配点：在这里创建各模块的实现并注入依赖。"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles


def create_app() -> FastAPI:
    app = FastAPI(title="SmartKeeper", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    static_dir = Path(os.environ.get("SMARTKEEPER_STATIC_DIR", "frontend/dist"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
