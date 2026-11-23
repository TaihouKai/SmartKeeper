"""规则包的存储。每次保存生成一个不可变的新版本。"""

from __future__ import annotations

import json
import secrets
from datetime import UTC, datetime
from typing import cast

import sqlalchemy as sa
from pydantic import ValidationError

from smartkeeper.contracts import (
    NotFound,
    Problem,
    RulePack,
    RulePackDraft,
    RulePackInfo,
    RulePackVersion,
    Rules,
    ValidationFailed,
)

metadata = sa.MetaData()

rule_pack = sa.Table(
    "rule_pack",
    metadata,
    sa.Column("id", sa.String, primary_key=True),
    sa.Column("name", sa.String, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
)

rule_pack_version = sa.Table(
    "rule_pack_version",
    metadata,
    sa.Column("pack_id", sa.String, sa.ForeignKey("rule_pack.id"), primary_key=True),
    sa.Column("version", sa.Integer, primary_key=True),
    sa.Column("body", sa.Text, nullable=False),
    sa.Column("created_at", sa.String, nullable=False),
)

rule_pack_draft = sa.Table(
    "rule_pack_draft",
    metadata,
    sa.Column("pack_id", sa.String, sa.ForeignKey("rule_pack.id"), primary_key=True),
    sa.Column("body", sa.Text, nullable=False),
    sa.Column("updated_at", sa.String, nullable=False),
)

EXPORT_FORMAT = "smartkeeper.rulepack"
EXPORT_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SqlRulePackStore:
    def __init__(self, db: sa.Engine, rules: Rules) -> None:
        self._db = db
        self._rules = rules
        metadata.create_all(db)

    def create_pack(self, name: str) -> str:
        pack_id = "rp_" + secrets.token_hex(4)
        with self._db.begin() as c:
            c.execute(rule_pack.insert().values(id=pack_id, name=name, created_at=_now()))
        return pack_id

    def save_version(self, pack_id: str, pack: RulePack) -> RulePackVersion:
        problems = self._rules.validate_pack(pack)
        if problems:
            raise ValidationFailed("rulepack.invalid", problems)
        with self._db.begin() as c:
            if (
                c.execute(sa.select(rule_pack.c.id).where(rule_pack.c.id == pack_id)).first()
                is None
            ):
                raise NotFound("rulepack.not_found", pack_id=pack_id)
            cur = c.execute(
                sa.select(sa.func.max(rule_pack_version.c.version)).where(
                    rule_pack_version.c.pack_id == pack_id
                )
            ).scalar()
            version = int(cur or 0) + 1
            now = _now()
            c.execute(
                rule_pack_version.insert().values(
                    pack_id=pack_id, version=version, body=pack.model_dump_json(), created_at=now
                )
            )
            c.execute(
                rule_pack.update().where(rule_pack.c.id == pack_id).values(name=pack.world.name)
            )
            c.execute(rule_pack_draft.delete().where(rule_pack_draft.c.pack_id == pack_id))
        return RulePackVersion(pack_id=pack_id, version=version, pack=pack, created_at=now)

    def save_draft(self, pack_id: str, pack: RulePack) -> RulePackDraft:
        now = _now()
        with self._db.begin() as c:
            if (
                c.execute(sa.select(rule_pack.c.id).where(rule_pack.c.id == pack_id)).first()
                is None
            ):
                raise NotFound("rulepack.not_found", pack_id=pack_id)
            c.execute(rule_pack_draft.delete().where(rule_pack_draft.c.pack_id == pack_id))
            c.execute(
                rule_pack_draft.insert().values(
                    pack_id=pack_id, body=pack.model_dump_json(), updated_at=now
                )
            )
            if pack.world.name:
                c.execute(
                    rule_pack.update().where(rule_pack.c.id == pack_id).values(name=pack.world.name)
                )
        return RulePackDraft(pack_id=pack_id, pack=pack, updated_at=now)

    def get_draft(self, pack_id: str) -> RulePackDraft:
        with self._db.connect() as c:
            row = c.execute(
                sa.select(rule_pack_draft).where(rule_pack_draft.c.pack_id == pack_id)
            ).first()
        if row is None:
            raise NotFound("rulepack.draft_not_found", pack_id=pack_id)
        return RulePackDraft(
            pack_id=pack_id, pack=RulePack.model_validate_json(row.body), updated_at=row.updated_at
        )

    def delete_draft(self, pack_id: str) -> None:
        with self._db.begin() as c:
            c.execute(rule_pack_draft.delete().where(rule_pack_draft.c.pack_id == pack_id))
            has_version = c.execute(
                sa.select(rule_pack_version.c.version)
                .where(rule_pack_version.c.pack_id == pack_id)
                .limit(1)
            ).first()
            if has_version is None:
                c.execute(rule_pack.delete().where(rule_pack.c.id == pack_id))

    def get_version(self, pack_id: str, version: int) -> RulePackVersion:
        with self._db.connect() as c:
            row = c.execute(
                sa.select(rule_pack_version).where(
                    rule_pack_version.c.pack_id == pack_id, rule_pack_version.c.version == version
                )
            ).first()
        if row is None:
            raise NotFound("rulepack.version_not_found", pack_id=pack_id, version=version)
        return RulePackVersion(
            pack_id=pack_id,
            version=version,
            pack=RulePack.model_validate_json(row.body),
            created_at=row.created_at,
        )

    def list_packs(self) -> list[RulePackInfo]:
        with self._db.connect() as c:
            packs = c.execute(sa.select(rule_pack).order_by(rule_pack.c.created_at)).all()
            versions = c.execute(
                sa.select(rule_pack_version.c.pack_id, rule_pack_version.c.version)
            ).all()
            drafts = dict(
                c.execute(sa.select(rule_pack_draft.c.pack_id, rule_pack_draft.c.updated_at)).all()
            )
        by_pack: dict[str, list[int]] = {}
        for pid, v in versions:
            by_pack.setdefault(pid, []).append(v)
        return [
            RulePackInfo(
                pack_id=p.id,
                name=p.name,
                versions=tuple(sorted(by_pack.get(p.id, []))),
                draft_updated_at=drafts.get(p.id),
            )
            for p in packs
            if p.id in by_pack or p.id in drafts
        ]

    def delete_version(self, pack_id: str, version: int) -> None:
        with self._db.begin() as c:
            res = c.execute(
                rule_pack_version.delete().where(
                    rule_pack_version.c.pack_id == pack_id, rule_pack_version.c.version == version
                )
            )
            if res.rowcount == 0:
                raise NotFound("rulepack.version_not_found", pack_id=pack_id, version=version)


def export_pack(pack: RulePack) -> str:
    body = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_VERSION,
        "pack": pack.model_dump(mode="json", by_alias=True),
    }
    return json.dumps(body, ensure_ascii=False, indent=2)


def parse_import(text: str) -> RulePack:
    """解析导入文件。格式不对抛 ValidationFailed；内容校验由 save_version 完成。"""
    try:
        raw: object = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValidationFailed("rulepack.import_not_json", line=e.lineno) from e
    if not isinstance(raw, dict):
        raise ValidationFailed("rulepack.import_bad_format")
    body = cast(dict[str, object], raw)
    if body.get("format") != EXPORT_FORMAT:
        raise ValidationFailed("rulepack.import_bad_format")
    if body.get("format_version") != EXPORT_VERSION:
        raise ValidationFailed("rulepack.import_bad_version")
    try:
        return RulePack.model_validate(body.get("pack"))
    except ValidationError as e:
        raise ValidationFailed(
            "rulepack.import_malformed",
            [
                Problem(
                    code="pack.malformed",
                    path=".".join(str(x) for x in err["loc"]),
                    params={"msg": err["msg"]},
                )
                for err in e.errors()
            ],
        ) from e
