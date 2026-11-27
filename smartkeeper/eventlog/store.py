"""只追加的事件表。可见性过滤只在这里实现。"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from smartkeeper.contracts import KP, PUBLIC, Audience, Event, EventType, NewEvent, Visibility

metadata = sa.MetaData()

event = sa.Table(
    "event",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("game_id", sa.String, nullable=False),
    sa.Column("round_no", sa.Integer, nullable=False),
    sa.Column("seq", sa.Integer, nullable=False),
    sa.Column("type", sa.String, nullable=False),
    sa.Column("actor", sa.String, nullable=True),
    sa.Column("vis_kind", sa.String, nullable=False),
    # 以 ",p1,p2," 的形式存可见玩家，便于用 LIKE 过滤
    sa.Column("vis_players", sa.String, nullable=False, default=""),
    sa.Column("payload", sa.Text, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
    sa.UniqueConstraint("game_id", "seq"),
    sa.Index("ix_event_game_seq", "game_id", "seq"),
)


def _row_to_event(row: sa.Row[tuple[object, ...]]) -> Event:
    m = row._mapping  # pyright: ignore[reportPrivateUsage]
    players = tuple(p for p in str(m["vis_players"]).split(",") if p)
    return Event(
        id=int(m["id"]),  # type: ignore[arg-type]
        game_id=str(m["game_id"]),
        round_no=int(m["round_no"]),  # type: ignore[arg-type]
        seq=int(m["seq"]),  # type: ignore[arg-type]
        type=m["type"],  # type: ignore[arg-type]
        actor=m["actor"],  # type: ignore[arg-type]
        visibility=Visibility(kind=m["vis_kind"], players=players),  # type: ignore[arg-type]
        payload=json.loads(str(m["payload"])),
        created_at=datetime.fromisoformat(str(m["created_at"])),
    )


def _redact(e: Event, audience: Audience) -> Event:
    """匿名广播在 KP 以外的视图里隐去 actor。"""
    if audience != KP and e.type == "broadcast" and e.payload.get("anonymous") is True:
        return e.model_copy(update={"actor": None})
    return e


class SqlEventLog:
    def __init__(self, db: sa.Engine) -> None:
        self._db = db
        self._lock = threading.Lock()
        metadata.create_all(db)

    def truncate(self, game_id: str, from_seq: int) -> None:
        with self._lock, self._db.begin() as c:
            c.execute(event.delete().where(event.c.game_id == game_id, event.c.seq >= from_seq))

    def delete_game(self, game_id: str) -> None:
        with self._lock, self._db.begin() as c:
            c.execute(event.delete().where(event.c.game_id == game_id))

    def append(self, game_id: str, round_no: int, events: Sequence[NewEvent]) -> list[Event]:
        if not events:
            return []
        now = datetime.now(UTC).isoformat()
        with self._lock, self._db.begin() as c:
            last = c.execute(
                sa.select(sa.func.max(event.c.seq)).where(event.c.game_id == game_id)
            ).scalar()
            seq = int(last or 0)
            rows: list[dict[str, object]] = []
            for ev in events:
                seq += 1
                rows.append(
                    {
                        "game_id": game_id,
                        "round_no": round_no,
                        "seq": seq,
                        "type": ev.type,
                        "actor": ev.actor,
                        "vis_kind": ev.visibility.kind,
                        "vis_players": ","
                        + ",".join(ev.visibility.players)
                        + ("," if ev.visibility.players else ""),
                        "payload": json.dumps(ev.payload, ensure_ascii=False, sort_keys=True),
                        "created_at": now,
                    }
                )
            c.execute(event.insert(), rows)
            first = seq - len(events) + 1
            got = c.execute(
                sa.select(event)
                .where(event.c.game_id == game_id, event.c.seq >= first)
                .order_by(event.c.seq)
            ).all()
        return [_row_to_event(r) for r in got]

    def view_for(
        self,
        game_id: str,
        audience: Audience,
        since_seq: int = 0,
        types: Sequence[EventType] | None = None,
        round_no: int | None = None,
    ) -> list[Event]:
        q = sa.select(event).where(event.c.game_id == game_id, event.c.seq > since_seq)
        if types is not None:
            q = q.where(event.c.type.in_(list(types)))
        if round_no is not None:
            q = q.where(event.c.round_no == round_no)
        if audience == PUBLIC:
            q = q.where(event.c.vis_kind == "public")
        elif audience != KP:
            q = q.where(
                sa.or_(
                    event.c.vis_kind == "public",
                    sa.and_(
                        event.c.vis_kind == "players",
                        event.c.vis_players.like(f"%,{_escape(audience)},%", escape="\\"),
                    ),
                )
            )
        with self._db.connect() as c:
            rows = c.execute(q.order_by(event.c.seq)).all()
        out = [_redact(_row_to_event(r), audience) for r in rows]
        # 数据库过滤之外再在内存里按同一规则复核一遍，任何一边出错都不会漏出事件
        return [e for e in out if e.visibility.visible_to(audience)]

    def get(self, game_id: str, seq: int) -> Event | None:
        with self._db.connect() as c:
            row = c.execute(
                sa.select(event).where(event.c.game_id == game_id, event.c.seq == seq)
            ).first()
        return _row_to_event(row) if row is not None else None


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
