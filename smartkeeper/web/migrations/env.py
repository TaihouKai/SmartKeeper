from __future__ import annotations

from alembic import context

from smartkeeper.web.schema import combined

config = context.config
target_metadata = combined()


def run() -> None:
    db = config.attributes["connection_engine"]
    with db.connect() as connection:
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run()
