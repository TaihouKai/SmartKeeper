"""生成一个新的迁移：uv run python scripts/make_migration.py "说明" [--rev 0002]

在一个临时空库上升级到当前最新版本，再和代码里的表结构比较，生成差异。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import sqlalchemy as sa
from alembic import command

from smartkeeper.web import alembic_config


def main() -> int:
    message = sys.argv[1]
    rev = sys.argv[sys.argv.index("--rev") + 1] if "--rev" in sys.argv else None
    with tempfile.TemporaryDirectory() as d:
        db = sa.create_engine(f"sqlite:///{Path(d) / 'm.db'}")
        cfg = alembic_config(db)
        if any((Path(cfg.get_main_option("script_location") or "") / "versions").glob("*.py")):
            command.upgrade(cfg, "head")
        command.revision(cfg, message=message, autogenerate=True, rev_id=rev)
        db.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
