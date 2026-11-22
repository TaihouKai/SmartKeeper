"""记事条目的存储与按实体检索。可见性等同 kp_only；可以从事件日志里的裁定事件重建。"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa

from smartkeeper.contracts import MemoryEntry

metadata = sa.MetaData()

memory_entry = sa.Table(
    "memory_entry",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("game_id", sa.String, nullable=False, index=True),
    sa.Column("round_no", sa.Integer, nullable=False),
    sa.Column("entities", sa.Text, nullable=False),
    sa.Column("features", sa.Text, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("source_seq", sa.Integer, nullable=False),
)


def _entry(m: Any) -> MemoryEntry:
    return MemoryEntry(
        game_id=m["game_id"],
        round_no=m["round_no"],
        entities=tuple(json.loads(m["entities"])),
        features=tuple(json.loads(m["features"])),
        text=m["text"],
        source_seq=m["source_seq"],
    )


class SqlMemoryStore:
    def __init__(self, db: sa.Engine) -> None:
        self._db = db
        metadata.create_all(db)

    def add(self, entries: list[MemoryEntry]) -> None:
        if not entries:
            return
        with self._db.begin() as c:
            c.execute(
                memory_entry.insert(),
                [
                    {
                        "game_id": e.game_id,
                        "round_no": e.round_no,
                        "entities": json.dumps(sorted(set(e.entities))),
                        "features": json.dumps(sorted(set(e.features))),
                        "text": e.text,
                        "source_seq": e.source_seq,
                    }
                    for e in entries
                ],
            )

    def all(self, game_id: str) -> list[MemoryEntry]:
        with self._db.connect() as c:
            rows = c.execute(
                sa.select(memory_entry)
                .where(memory_entry.c.game_id == game_id)
                .order_by(memory_entry.c.id)
            ).all()
        return [_entry(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def recall(
        self, game_id: str, entity_ids: list[str], actor_ids: list[str], feature_ids: list[str]
    ) -> list[MemoryEntry]:
        ents, actors, feats = set(entity_ids), set(actor_ids), set(feature_ids)
        out: list[MemoryEntry] = []
        for e in self.all(game_id):
            tagged = set(e.entities)
            if len(tagged & ents) >= 2 or (tagged & actors and set(e.features) & feats):
                out.append(e)
        return out

    def clear(self, game_id: str) -> None:
        with self._db.begin() as c:
            c.execute(memory_entry.delete().where(memory_entry.c.game_id == game_id))
