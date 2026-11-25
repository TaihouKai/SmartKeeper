from pathlib import Path

import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from smartkeeper.web.schema import combined, migrate


def test_migrations_match_code(tmp_path: Path) -> None:
    db = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    migrate(db)
    with db.connect() as c:
        diff = compare_metadata(MigrationContext.configure(c), combined())
    assert diff == []
    migrate(db)  # 再跑一次是空操作


def test_legacy_db_is_stamped(tmp_path: Path) -> None:
    db = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    legacy = combined()
    legacy.remove(legacy.tables["rule_pack_draft"])  # 0002 才加的表，旧库里没有
    legacy.create_all(db)
    with db.begin() as c:  # 0003 之前回合时间是分钟
        c.exec_driver_sql("ALTER TABLE round RENAME COLUMN started_second TO started_minute")
        c.exec_driver_sql("ALTER TABLE round RENAME COLUMN ended_second TO ended_minute")
        # 0009 才加的列
        c.exec_driver_sql("ALTER TABLE player DROP COLUMN character_draft")
        c.exec_driver_sql("ALTER TABLE player DROP COLUMN character_draft_at")
    migrate(db)
    assert "rule_pack_draft" in sa.inspect(db).get_table_names()
    assert "alembic_version" in sa.inspect(db).get_table_names()
