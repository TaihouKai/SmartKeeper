"""全部表的 MetaData 汇总，供 Alembic 迁移使用。只有装配层知道所有模块。"""

from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from smartkeeper.chat import chat_metadata
from smartkeeper.engine import engine_metadata
from smartkeeper.eventlog import eventlog_metadata
from smartkeeper.handles import handles_metadata
from smartkeeper.llm import llm_metadata
from smartkeeper.memory import memory_metadata
from smartkeeper.rules import rules_metadata

ALL_METADATA: list[sa.MetaData] = [
    rules_metadata,
    engine_metadata,
    eventlog_metadata,
    handles_metadata,
    memory_metadata,
    llm_metadata,
    chat_metadata,
]

MIGRATIONS = Path(__file__).parent / "migrations"


def combined() -> sa.MetaData:
    md = sa.MetaData()
    for m in ALL_METADATA:
        for t in m.tables.values():
            t.to_metadata(md)
    return md


def alembic_config(db: sa.Engine) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["connection_engine"] = db
    return cfg


def migrate(db: sa.Engine) -> None:
    """把数据库升级到最新结构。以前没有用迁移建的库（只有表、没有版本记录）先标记为初始版本。"""
    insp = sa.inspect(db)
    tables = set(insp.get_table_names())
    cfg = alembic_config(db)
    if tables and "alembic_version" not in tables:
        command.stamp(cfg, "0001")
    command.upgrade(cfg, "head")
