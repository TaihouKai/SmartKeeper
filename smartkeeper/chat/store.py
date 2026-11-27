"""玩家间闲聊的存储。与事件日志无关，engine 和 kp 都不依赖它。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from smartkeeper.contracts import ChatMessage, ValidationFailed

metadata = sa.MetaData()

chat_message = sa.Table(
    "chat_message",
    metadata,
    sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
    sa.Column("game_id", sa.String, nullable=False, index=True),
    sa.Column("sender", sa.String, nullable=False),
    sa.Column("recipient", sa.String, nullable=False),
    sa.Column("text", sa.Text, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
)

MAX_TEXT = 4000


def _msg(m: Any) -> ChatMessage:
    return ChatMessage(
        id=m["id"],
        game_id=m["game_id"],
        sender=m["sender"],
        recipient=m["recipient"],
        text=m["text"],
        created_at=m["created_at"],
    )


class SqlChatStore:
    def __init__(self, db: sa.Engine) -> None:
        self._db = db
        metadata.create_all(db)

    def delete(self, game_id: str, since: str | None = None) -> None:
        """删掉这一局的私聊（since：只删这个时刻以后的，ISO 时间）。重新开始或删除一局时用。"""
        q = chat_message.delete().where(chat_message.c.game_id == game_id)
        if since is not None:
            q = q.where(chat_message.c.created_at >= since)
        with self._db.begin() as c:
            c.execute(q)

    def post(self, game_id: str, sender: str, recipient: str, text: str) -> ChatMessage:
        if not text.strip() or len(text) > MAX_TEXT:
            raise ValidationFailed("text.length", max=MAX_TEXT)
        if sender == recipient:
            raise ValidationFailed("chat.self")
        now = datetime.now(UTC).isoformat()
        with self._db.begin() as c:
            res = c.execute(
                chat_message.insert().values(
                    game_id=game_id, sender=sender, recipient=recipient, text=text, created_at=now
                )
            )
            pk = res.inserted_primary_key
            assert pk is not None
        return ChatMessage(
            id=int(pk[0]),
            game_id=game_id,
            sender=sender,
            recipient=recipient,
            text=text,
            created_at=now,
        )

    def conversation(self, game_id: str, a: str, b: str, since_id: int = 0) -> list[ChatMessage]:
        t = chat_message
        q = sa.select(t).where(
            t.c.game_id == game_id,
            t.c.id > since_id,
            sa.or_(
                sa.and_(t.c.sender == a, t.c.recipient == b),
                sa.and_(t.c.sender == b, t.c.recipient == a),
            ),
        )
        with self._db.connect() as c:
            return [_msg(r._mapping) for r in c.execute(q.order_by(t.c.id)).all()]  # pyright: ignore[reportPrivateUsage]

    def for_player(self, game_id: str, player: str, since_id: int = 0) -> list[ChatMessage]:
        t = chat_message
        q = sa.select(t).where(
            t.c.game_id == game_id,
            t.c.id > since_id,
            sa.or_(t.c.sender == player, t.c.recipient == player),
        )
        with self._db.connect() as c:
            return [_msg(r._mapping) for r in c.execute(q.order_by(t.c.id)).all()]  # pyright: ignore[reportPrivateUsage]
