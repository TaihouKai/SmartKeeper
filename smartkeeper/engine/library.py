"""角色库：按规则书存的角色（一整套卡），和局分开。密码用 scrypt 加盐哈希；设了密码的查看和使用都要密码。"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from typing import Any

from pydantic import JsonValue

from smartkeeper.contracts import LibraryCharacter, LibraryCharacterFull, ValidationFailed

MAX_BYTES = 500_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def check_password(stored: str | None, password: str | None) -> bool:
    """没设密码的谁都能用；设了的要对上。"""
    if not stored:
        return True
    if not password:
        return False
    try:
        _, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=2**14, r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(got.hex(), digest)


def templates_of(sheets: JsonValue) -> tuple[str, ...]:
    if not isinstance(sheets, list):
        return ()
    return tuple(str(s.get("template", "")) for s in sheets if isinstance(s, dict))


def auto_name(sheets: JsonValue) -> str:
    """没起名字时：各张卡的角色名连起来（例如“鹿苑寺汐 / 白骑士”）。"""
    names: list[str] = []
    if isinstance(sheets, list):
        for s in sheets:
            if isinstance(s, dict):
                sheet = s.get("sheet")
                name = sheet.get("name") if isinstance(sheet, dict) else None
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
    return " / ".join(names)


def check_size(sheets: JsonValue) -> None:
    if len(json.dumps(sheets, ensure_ascii=False)) > MAX_BYTES:
        raise ValidationFailed("library.too_big")


def summary_of(row: dict[str, Any]) -> LibraryCharacter:
    return LibraryCharacter(
        id=row["id"],
        rulepack_id=row["rulepack_id"],
        name=row["name"],
        summary=row["summary"] or "",
        templates=templates_of(json.loads(row["sheets"])),
        locked=bool(row["password_hash"]),
        created_by=row["created_by"] or "",
        updated_at=row["updated_at"],
    )


def full_of(row: dict[str, Any]) -> LibraryCharacterFull:
    s = summary_of(row)
    return LibraryCharacterFull(**s.model_dump(), sheets=json.loads(row["sheets"]))
