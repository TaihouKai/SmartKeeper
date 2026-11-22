"""唯一的装配点：在这里创建各模块的实现并注入依赖。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import event

from smartkeeper.contracts import LLMClient
from smartkeeper.dice import DiceRoller, SystemRandomSource
from smartkeeper.engine import Engine
from smartkeeper.eventlog import SqlEventLog
from smartkeeper.handles import SqlHandleStore
from smartkeeper.kp import KP, KPConfig
from smartkeeper.llm import AnthropicLLM, FakeLLM, OpenAICompatLLM, RecordingLLM, SqlLLMCallLog
from smartkeeper.mapdata import FileMapStore
from smartkeeper.memory import SqlMemoryStore
from smartkeeper.rounds import RoundStateMachine
from smartkeeper.rules import RulesService, SqlRulePackStore
from smartkeeper.spatial import ShapelySpatial
from smartkeeper.world import WorldService


@dataclass(frozen=True)
class Settings:
    """配置一律来自环境变量（见设计文档“技术栈与项目结构”）。"""

    db_path: str = "data/smartkeeper.db"
    maps_dir: str = "maps"
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
    base_url: str = "http://localhost:8000"
    extra: dict[str, str] = field(default_factory=dict[str, str])

    @staticmethod
    def from_env() -> Settings:
        env = os.environ
        return Settings(
            db_path=env.get("SMARTKEEPER_DB_PATH", "data/smartkeeper.db"),
            maps_dir=env.get("SMARTKEEPER_MAPS_DIR", "maps"),
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
            base_url=env.get("SMARTKEEPER_BASE_URL", "http://localhost:8000"),
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
    if provider == "anthropic":
        return AnthropicLLM()
    if provider == "openai_compat":
        if not settings.openai_base_url or not settings.openai_api_key:
            raise RuntimeError("OPENAI_COMPAT_BASE_URL and OPENAI_COMPAT_API_KEY are required")
        return OpenAICompatLLM(base_url=settings.openai_base_url, api_key=settings.openai_api_key)
    if provider == "fake":
        return FakeLLM()
    raise RuntimeError(f"unknown provider {provider}")


@dataclass
class Services:
    db: sa.Engine
    engine: Engine
    kp: KP
    packs: SqlRulePackStore
    rules: RulesService
    maps: FileMapStore
    llm_log: SqlLLMCallLog
    judge: LLMClient
    writer: LLMClient


def build_services(
    settings: Settings,
    *,
    judge: LLMClient | None = None,
    writer: LLMClient | None = None,
) -> Services:
    db = make_db(settings.db_path)
    dice = DiceRoller(SystemRandomSource())
    rules = RulesService(dice)
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
    j = RecordingLLM(judge or make_llm(settings.judge_provider, settings), log)
    w = RecordingLLM(writer or make_llm(settings.writer_provider, settings), log)
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
    )
    return Services(db, engine, kp, packs, rules, maps, log, j, w)


def create_app() -> FastAPI:
    app = FastAPI(title="SmartKeeper", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
        return {"status": "ok"}

    static_dir = Path(os.environ.get("SMARTKEEPER_STATIC_DIR", "frontend/dist"))
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app
