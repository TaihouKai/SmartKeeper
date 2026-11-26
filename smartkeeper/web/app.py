"""唯一的装配点：在这里创建各模块的实现并注入依赖。"""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import event

from smartkeeper.chat import SqlChatStore
from smartkeeper.contracts import (
    Forbidden,
    IllegalState,
    LLMClient,
    NotFound,
    SmartKeeperError,
    ValidationFailed,
)
from smartkeeper.copilot import Copilot
from smartkeeper.dice import DiceRoller, SystemRandomSource
from smartkeeper.engine import Engine
from smartkeeper.eventlog import SqlEventLog
from smartkeeper.handles import SqlHandleStore
from smartkeeper.kp import KP, KPConfig
from smartkeeper.llm import (
    AnthropicLLM,
    FakeLLM,
    OpenAICompatLLM,
    OpenAIResponsesLLM,
    RecordingLLM,
    SqlLLMCallLog,
)
from smartkeeper.mapdata import FileMapStore
from smartkeeper.memory import SqlMemoryStore
from smartkeeper.notify import WebhookNotifier
from smartkeeper.rounds import RoundStateMachine
from smartkeeper.rules import RulesService, SqlRulePackStore
from smartkeeper.rules import render as render_rules
from smartkeeper.spatial import ShapelySpatial
from smartkeeper.web.auth import Auth, enter_seat
from smartkeeper.web.messages import load_messages
from smartkeeper.web.routes_admin import build_admin_router
from smartkeeper.web.routes_books import build_books_router
from smartkeeper.web.routes_lobby import build_lobby_router
from smartkeeper.web.routes_player import build_player_router
from smartkeeper.web.schema import migrate
from smartkeeper.web.scripted import install_scripted
from smartkeeper.web.services import Services
from smartkeeper.world import WorldService


@dataclass(frozen=True)
class Settings:
    """配置一律来自环境变量（见设计文档“技术栈与项目结构”）。"""

    db_path: str = "data/smartkeeper.db"
    maps_dir: str = "maps"
    scenarios_dir: str = "scenarios"
    static_dir: str = "frontend/dist"
    admin_password_hash: str | None = None
    session_secret: str = ""
    judge_provider: str = "anthropic"
    judge_model: str = "claude-opus-5-5"
    writer_provider: str = "anthropic"
    writer_model: str = "claude-opus-5-5"
    writer_concurrency: int = 4
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_compat_search: bool = (
        False  # 兼容服务是否实现了 Responses API 的 web_search，由用户自己配置
    )
    official_openai_key: str | None = None  # provider=openai 用；不填时 SDK 读 OPENAI_API_KEY
    base_url: str | None = None
    extra: dict[str, str] = field(default_factory=dict[str, str])

    @staticmethod
    def from_env() -> Settings:
        env = os.environ
        return Settings(
            db_path=env.get("SMARTKEEPER_DB_PATH", "data/smartkeeper.db"),
            maps_dir=env.get("SMARTKEEPER_MAPS_DIR", "maps"),
            scenarios_dir=env.get("SMARTKEEPER_SCENARIOS_DIR", "scenarios"),
            static_dir=env.get("SMARTKEEPER_STATIC_DIR", "frontend/dist"),
            admin_password_hash=env.get("SMARTKEEPER_ADMIN_PASSWORD_HASH") or None,
            session_secret=env.get("SMARTKEEPER_SESSION_SECRET", ""),
            judge_provider=env.get("SMARTKEEPER_JUDGE_PROVIDER", "anthropic"),
            judge_model=env.get("SMARTKEEPER_JUDGE_MODEL", "claude-opus-5-5"),
            writer_provider=env.get("SMARTKEEPER_WRITER_PROVIDER", "anthropic"),
            writer_model=env.get("SMARTKEEPER_WRITER_MODEL", "claude-opus-5-5"),
            writer_concurrency=int(env.get("SMARTKEEPER_WRITER_CONCURRENCY", "4")),
            openai_base_url=env.get("OPENAI_COMPAT_BASE_URL") or None,
            openai_api_key=env.get("OPENAI_COMPAT_API_KEY") or None,
            openai_compat_search=env.get("OPENAI_COMPAT_WEB_SEARCH", "").lower()
            in ("1", "true", "yes", "on"),
            official_openai_key=env.get("OPENAI_API_KEY") or None,
            base_url=env.get("SMARTKEEPER_BASE_URL") or None,
        )


def make_db(path: str) -> sa.Engine:
    """SQLite（WAL 模式）。"""
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sa.create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30}
    )

    @event.listens_for(db, "connect")
    def _pragmas(conn: object, _rec: object) -> None:  # pyright: ignore[reportUnusedFunction]
        cur = conn.cursor()  # type: ignore[attr-defined]
        cur.execute("PRAGMA journal_mode=WAL")  # pyright: ignore[reportUnknownMemberType]
        cur.execute("PRAGMA synchronous=NORMAL")  # pyright: ignore[reportUnknownMemberType]
        cur.execute("PRAGMA foreign_keys=ON")  # pyright: ignore[reportUnknownMemberType]
        cur.close()  # pyright: ignore[reportUnknownMemberType]

    return db


def make_llm(provider: str, settings: Settings) -> LLMClient:
    """三类模型：anthropic（Claude，默认联网）、openai（ChatGPT，默认联网）、
    openai_compat（DeepSeek 等兼容接口，联网由 OPENAI_COMPAT_WEB_SEARCH 配置，默认关）。"""
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "openai":
        return OpenAIResponsesLLM(api_key=settings.official_openai_key, search=True)
    if provider == "openai_compat":
        if not settings.openai_base_url or not settings.openai_api_key:
            raise RuntimeError("OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_API_KEY are required")
        if settings.openai_compat_search:
            return OpenAIResponsesLLM(
                base_url=settings.openai_base_url,
                api_key=settings.openai_api_key,
                search=True,
                provider="openai_compat",
            )
        return OpenAICompatLLM(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
    if provider == "fake":
        return FakeLLM()
    raise RuntimeError(f"unknown provider {provider}")


def build_services(
    settings: Settings,
    *,
    judge: LLMClient | None = None,
    writer: LLMClient | None = None,
    notifier: WebhookNotifier | None = None,
) -> Services:
    db = make_db(settings.db_path)
    migrate(db)
    dice = DiceRoller(SystemRandomSource())
    rules = RulesService()
    packs = SqlRulePackStore(db, rules)
    maps = FileMapStore(Path(settings.maps_dir))
    engine = Engine(
        db=db,
        events=SqlEventLog(db),
        packs=packs,
        rules=rules,
        world=WorldService(rules),
        rounds=RoundStateMachine(),
        dice=dice,
        maps=maps,
        spatial=ShapelySpatial(),
        handles=SqlHandleStore(db),
        memory=SqlMemoryStore(db),
    )
    log = SqlLLMCallLog(db)
    raw_judge = judge or make_llm(settings.judge_provider, settings)
    raw_writer = writer or make_llm(settings.writer_provider, settings)
    for client in {id(raw_judge): raw_judge, id(raw_writer): raw_writer}.values():
        if isinstance(client, FakeLLM) and not client.handlers:
            install_scripted(client, engine)  # 离线演示与端到端测试用的脚本化 KP
    j = RecordingLLM(raw_judge, log)
    w = RecordingLLM(raw_writer, log)
    notifier = notifier or WebhookNotifier()

    def on_published(game_id: str, round_no: int) -> None:
        g = engine.game(game_id)
        lang = g.settings.kp_language
        if g.status == "ended":
            notifier.send(g.settings.player_webhook, "game.ended", lang, game=g.name)
        else:
            notifier.send(
                g.settings.player_webhook, "round.started", lang, game=g.name, round=round_no + 1
            )

    def on_review(game_id: str, round_no: int) -> None:
        g = engine.game(game_id)
        notifier.send(
            g.settings.admin_webhook,
            "round.review",
            g.settings.kp_language,
            game=g.name,
            round=round_no,
        )

    kp = KP(
        engine,
        j,
        w,
        KPConfig(
            judge_model=settings.judge_model,
            writer_model=settings.writer_model,
            writer_concurrency=settings.writer_concurrency,
        ),
        call_log=log,
        on_published=on_published,
        on_review=on_review,
    )
    return Services(
        db=db,
        engine=engine,
        kp=kp,
        packs=packs,
        rules=rules,
        maps=maps,
        llm_log=log,
        judge=j,
        writer=w,
        chat=SqlChatStore(db),
        dice=dice,
        # 建卡助手：用 KP 的模型配置，但是单独的调用，不碰对局和 KP 的记事
        copilot=Copilot(
            j,
            rules,
            settings.judge_model,
            lambda pack: render_rules(pack, include_hidden=False),
            load_messages(),
        ),
        scenarios_dir=settings.scenarios_dir,
        base_url=settings.base_url,
    )


def _error_body(err: SmartKeeperError) -> dict[str, Any]:
    return {
        "code": err.code,
        "params": err.params,
        "problems": [p.model_dump(mode="json") for p in err.problems],
    }


STATUS = {ValidationFailed: 422, NotFound: 404, IllegalState: 409, Forbidden: 403}


def create_app(settings: Settings | None = None, services: Services | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    s = services or build_services(settings)
    auth = Auth(s.engine, settings.admin_password_hash, settings.session_secret)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        """启动时发现停在“裁定中”的回合，自动重跑一次（后台线程，不挡住启动）。"""

        def run() -> None:
            try:
                s.kp.recover()
            except Exception:
                logging.getLogger("smartkeeper.web").exception("recover failed")

        threading.Thread(target=run, daemon=True).start()
        yield

    app = FastAPI(title="SmartKeeper", version="0.1.0", lifespan=lifespan)
    # 地图数据很大（几十 MB 的 GeoJSON），压缩后传输
    app.add_middleware(GZipMiddleware, minimum_size=1024, compresslevel=6)
    app.state.services = s

    @app.exception_handler(SmartKeeperError)
    def _sk_error(request: Request, err: SmartKeeperError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        status = next((v for k, v in STATUS.items() if isinstance(err, k)), 400)
        return JSONResponse(status_code=status, content={"detail": _error_body(err)})

    @app.get("/api/health")
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    app.include_router(build_player_router(s, auth.require_player))
    app.include_router(build_admin_router(s, auth))

    app.include_router(build_lobby_router(s))
    app.include_router(build_books_router(s))

    @app.get("/join/{token}", include_in_schema=False)
    def join(token: str, request: Request) -> RedirectResponse:  # pyright: ignore[reportUnusedFunction]
        """邀请链接（或个人链接）：把 token 写进 HttpOnly cookie，记进这个浏览器的座位，重定向到不带 token 的地址。"""
        if s.engine.player_by_token(token) is None:
            return RedirectResponse("/join?invalid=1", status_code=303)
        resp = RedirectResponse("/join", status_code=303)
        enter_seat(request, resp, token)
        return resp

    static_dir = Path(settings.static_dir)
    if static_dir.is_dir():
        index = static_dir / "index.html"
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:  # pyright: ignore[reportUnusedFunction]
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            target = (static_dir / path).resolve()
            if path and target.is_file() and static_dir.resolve() in target.parents:
                return FileResponse(target)
            return FileResponse(index)

    return app
