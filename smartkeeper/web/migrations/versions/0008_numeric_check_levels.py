"""check results become numbers: `level = ...` (0 failure, 1 success, higher is better) and `levels = [...]` names.
critical_success / critical_failure lines are folded into a level formula:
level = 2 if <critical_success> else -1 if <critical_failure> else 1 if <success> else 0.

Revision ID: 0008
Revises: 0007
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = '0008'
down_revision = '0007'
branch_labels = None
depends_on = None

COLUMNS = [
    ('rule_pack_draft', 'body'),
    ('rule_pack_version', 'body'),
    ('event', 'payload'),
    ('round', 'snapshot'),
    ('round', 'draft'),
    ('round', 'submitted'),
]


def _value(lines: list[str], key: str) -> str | None:
    for line in lines:
        if line.split('=', 1)[0].strip() == key and '=' in line:
            return line.split('=', 1)[1].split('#', 1)[0].strip()
    return None


def check(c: dict[str, Any]) -> None:
    text = str(c.get('config') or '')
    lines = text.split(chr(10))
    cs = _value(lines, 'critical_success')
    cf = _value(lines, 'critical_failure')
    if cs is None and cf is None:
        return
    keep = [x for x in lines if x.split('=', 1)[0].strip() not in ('critical_success', 'critical_failure')]
    cs = None if cs in (None, '', 'False', '0') else cs
    cf = None if cf in (None, '', 'False', '0') else cf
    if cs or cf:
        success = _value(keep, 'success') or 'False'
        keep = [x for x in keep if x.split('=', 1)[0].strip() != 'success']
        parts = []
        if cs:
            parts.append(f'2 if {cs} else')
        if cf:
            parts.append(f'-1 if {cf} else')
        keep.append('level = ' + ' '.join(parts) + f' 1 if {success} else 0')
    c['config'] = chr(10).join(keep)


def convert(obj: Any) -> Any:
    if isinstance(obj, list):
        return [convert(x) for x in obj]
    if isinstance(obj, dict):
        for k in list(obj):
            obj[k] = convert(obj[k])
        checks = obj.get('checks')
        if isinstance(checks, list) and 'templates' in obj:
            for c in checks:
                if isinstance(c, dict) and 'config' in c:
                    check(c)
    return obj


def upgrade() -> None:
    conn = op.get_bind()
    for table, col in COLUMNS:
        rows = conn.execute(
            sa.text(f'SELECT rowid, {col} FROM {table} WHERE {col} IS NOT NULL')
        ).fetchall()
        for rowid, raw in rows:
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                continue
            new = json.dumps(convert(data), ensure_ascii=False)
            if new != json.dumps(json.loads(raw), ensure_ascii=False):
                conn.execute(
                    sa.text(f'UPDATE {table} SET {col} = :v WHERE rowid = :r'),
                    {'v': new, 'r': rowid},
                )


def downgrade() -> None:
    raise NotImplementedError('数字等级不能自动转回固定的四个结果')
