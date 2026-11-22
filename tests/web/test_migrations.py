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
    combined().create_all(db)
    migrate(db)
    assert "alembic_version" in sa.inspect(db).get_table_names()
