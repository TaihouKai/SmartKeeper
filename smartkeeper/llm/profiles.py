"""llm_profile 表：管理员建的几套模型选择（比如“正式版”“测试版”），开局时选一套。"""

from __future__ import annotations

import uuid

import sqlalchemy as sa

from smartkeeper.contracts import LLMProfile, NotFound
from smartkeeper.llm.recording import metadata

llm_profile = sa.Table(
    "llm_profile",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("judge_provider", sa.String, nullable=False),
    sa.Column("judge_model", sa.String, nullable=False),
    sa.Column("writer_provider", sa.String, nullable=False),
    sa.Column("writer_model", sa.String, nullable=False),
)

_FIELDS = ("name", "judge_provider", "judge_model", "writer_provider", "writer_model")


class SqlLLMProfiles:
    def __init__(self, db: sa.Engine) -> None:
        self._db = db
        metadata.create_all(db)

    def list(self) -> list[LLMProfile]:
        with self._db.connect() as c:
            rows = c.execute(sa.select(llm_profile).order_by(llm_profile.c.name)).all()
        return [LLMProfile.model_validate(dict(r._mapping)) for r in rows]  # pyright: ignore[reportPrivateUsage]

    def get(self, profile_id: str) -> LLMProfile | None:
        with self._db.connect() as c:
            row = c.execute(sa.select(llm_profile).where(llm_profile.c.id == profile_id)).first()
        return None if row is None else LLMProfile.model_validate(dict(row._mapping))  # pyright: ignore[reportPrivateUsage]

    def save(self, profile: LLMProfile) -> LLMProfile:
        """id 为空时新建；否则覆盖那一套。"""
        values = {k: getattr(profile, k) for k in _FIELDS}
        with self._db.begin() as c:
            if not profile.id:
                profile = profile.model_copy(update={"id": uuid.uuid4().hex[:12]})
                c.execute(llm_profile.insert().values(id=profile.id, **values))
                return profile
            n = c.execute(
                llm_profile.update().where(llm_profile.c.id == profile.id).values(**values)
            ).rowcount
        if n == 0:
            raise NotFound("llm_profile.not_found", id=profile.id)
        return profile

    def delete(self, profile_id: str) -> None:
        with self._db.begin() as c:
            c.execute(llm_profile.delete().where(llm_profile.c.id == profile_id))
