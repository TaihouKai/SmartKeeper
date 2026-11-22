"""代号的存储：玩家、实体 ID、不透明引用、代号、玩家备注。代号在一个玩家这里唯一。"""

from __future__ import annotations

import secrets
import threading
from typing import Any

import sqlalchemy as sa

from smartkeeper.contracts import Handle, NotFound, ValidationFailed

metadata = sa.MetaData()

handle = sa.Table(
    "handle",
    metadata,
    sa.Column("player_id", sa.String, primary_key=True),
    sa.Column("entity_id", sa.String, primary_key=True),
    sa.Column("ref", sa.String, nullable=False),
    sa.Column("label", sa.String, nullable=False),
    sa.Column("note", sa.String, nullable=False, default=""),
    sa.Column("auto", sa.Boolean, nullable=False, default=True),
    sa.Column("named", sa.Boolean, nullable=False, default=False),
    sa.Column("n", sa.Integer, nullable=False),
    sa.UniqueConstraint("player_id", "ref"),
    sa.UniqueConstraint("player_id", "label"),
)

MAX_LABEL = 40
MAX_NOTE = 500


def _h(m: Any) -> Handle:
    return Handle(
        player_id=m["player_id"],
        entity_id=m["entity_id"],
        ref=m["ref"],
        label=m["label"],
        note=m["note"],
        auto=bool(m["auto"]),
        named=bool(m["named"]),
    )


class SqlHandleStore:
    def __init__(self, db: sa.Engine) -> None:
        self._db = db
        self._lock = threading.Lock()
        metadata.create_all(db)

    def _one(self, c: sa.Connection, *where: Any) -> Handle | None:
        row = c.execute(sa.select(handle).where(*where)).first()
        return _h(row._mapping) if row is not None else None  # pyright: ignore[reportPrivateUsage]

    def get(self, player_id: str, entity_id: str) -> Handle | None:
        with self._db.connect() as c:
            return self._one(c, handle.c.player_id == player_id, handle.c.entity_id == entity_id)

    def by_ref(self, player_id: str, ref: str) -> Handle | None:
        with self._db.connect() as c:
            return self._one(c, handle.c.player_id == player_id, handle.c.ref == ref)

    def list(self, player_id: str) -> list[Handle]:
        with self._db.connect() as c:
            rows = c.execute(
                sa.select(handle).where(handle.c.player_id == player_id).order_by(handle.c.n)
            ).all()
        return [_h(r._mapping) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def ensure(self, player_id: str, entity_id: str) -> Handle:
        with self._lock, self._db.begin() as c:
            got = self._one(c, handle.c.player_id == player_id, handle.c.entity_id == entity_id)
            if got is not None:
                return got
            n = (
                int(
                    c.execute(
                        sa.select(sa.func.count()).where(handle.c.player_id == player_id)
                    ).scalar()
                    or 0
                )
                + 1
            )
            labels = {
                r[0]
                for r in c.execute(sa.select(handle.c.label).where(handle.c.player_id == player_id))
            }
            label = f"#{n}"
            while label in labels:
                n += 1
                label = f"#{n}"
            c.execute(
                handle.insert().values(
                    player_id=player_id,
                    entity_id=entity_id,
                    ref="h" + secrets.token_hex(6),
                    label=label,
                    note="",
                    auto=True,
                    named=False,
                    n=n,
                )
            )
            got = self._one(c, handle.c.player_id == player_id, handle.c.entity_id == entity_id)
            assert got is not None
            return got

    def set_label(self, player_id: str, entity_id: str, label: str, *, by_player: bool) -> Handle:
        """玩家改名：重名时拒绝。“外观代号”调用命名：重名时自动加序号，且不覆盖玩家自己改过的名字。"""
        label = " ".join(label.split())[:MAX_LABEL]
        if not label:
            raise ValidationFailed("handle.empty_label")
        with self._lock, self._db.begin() as c:
            cur = self._one(c, handle.c.player_id == player_id, handle.c.entity_id == entity_id)
            if cur is None:
                raise NotFound("handle.not_found")
            if not by_player and not cur.auto:
                return cur
            others = {
                r[0]
                for r in c.execute(
                    sa.select(handle.c.label).where(
                        handle.c.player_id == player_id, handle.c.entity_id != entity_id
                    )
                )
            }
            if label in others:
                if by_player:
                    raise ValidationFailed("handle.label_taken", label=label)
                k = 2
                while f"{label} {k}" in others:
                    k += 1
                label = f"{label} {k}"
            values: dict[str, Any] = {"label": label}
            if by_player:
                values["auto"] = False
            else:
                values["named"] = True
            c.execute(
                handle.update()
                .where(handle.c.player_id == player_id, handle.c.entity_id == entity_id)
                .values(**values)
            )
            got = self._one(c, handle.c.player_id == player_id, handle.c.entity_id == entity_id)
            assert got is not None
            return got

    def set_note(self, player_id: str, entity_id: str, note: str) -> Handle:
        with self._db.begin() as c:
            res = c.execute(
                handle.update()
                .where(handle.c.player_id == player_id, handle.c.entity_id == entity_id)
                .values(note=note[:MAX_NOTE])
            )
            if res.rowcount == 0:
                raise NotFound("handle.not_found")
            got = self._one(c, handle.c.player_id == player_id, handle.c.entity_id == entity_id)
            assert got is not None
            return got
