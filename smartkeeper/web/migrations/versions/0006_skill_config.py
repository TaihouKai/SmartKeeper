"""skill config: an entry's cast_time, cooldown, shape and placement move into its config text.

Entries whose script never mentions target get target = "self" (script only uses self) or "none" (no script).

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

COLUMNS = [
    ('rule_pack_draft', 'body'),
    ('rule_pack_version', 'body'),
    ('event', 'payload'),
    ('round', 'snapshot'),
    ('round', 'draft'),
    ('round', 'submitted'),
    ('game', 'settings'),
]
MOVED = ('cast_time', 'cooldown', 'shape', 'placement')
SHAPE_ARGS = ('length', 'width', 'height', 'radius', 'angle')


def _num(v: Any) -> str:
    f = float(v)
    return str(int(f)) if f.is_integer() else repr(f)


def _minutes(seconds: str) -> str:
    s = seconds.strip()
    if re.fullmatch(r'\d+(\.\d+)?', s):
        return _num(float(s) / 60)
    return f'({s}) / 60'


def config_lines(d: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    script = str(d.get('script') or '')
    if 'target.' not in script:
        lines.append('target = "self"' if 'self.' in script else 'target = "none"')
    for key in ('cast_time', 'cooldown'):
        text = str(d.get(key) or '').strip()
        if text:
            lines.append(f'{key} = {text}')
    shape = d.get('shape')
    if isinstance(shape, dict) and shape.get('kind'):
        args = [f'{a}={_num(shape[a])}' for a in SHAPE_ARGS if isinstance(shape.get(a), int | float)]
        lines.append(f"shape = {shape['kind']}({', '.join(args)})")
    pl = d.get('placement')
    if isinstance(pl, dict) and str(pl.get('radius') or '').strip():
        args = [f"radius={pl['radius']}"]
        if str(pl.get('perceive_multiplier') or '1').strip() != '1':
            args.append(f"perceive={pl['perceive_multiplier']}")
        if str(pl.get('charges') or '').strip():
            args.append(f"charges={pl['charges']}")
        if str(pl.get('duration') or '').strip():
            args.append(f"duration={_minutes(str(pl['duration']))}")
        if pl.get('notify_owner') is False:
            args.append('notify=False')
        lines.append(f"placement = placement({', '.join(args)})")
    return lines


def _entry(d: dict[str, Any]) -> None:
    lines = config_lines(d)
    for key in MOVED:
        d.pop(key, None)
    old = str(d.get('config') or '').strip()
    if lines:
        d['config'] = '\n'.join([old, *lines] if old else lines)


def convert(obj: Any) -> Any:
    if isinstance(obj, list):
        return [convert(x) for x in obj]
    if isinstance(obj, dict):
        for k in list(obj):
            obj[k] = convert(obj[k])
        # 条目：有名字，带着要搬的列，或者是带技能脚本的条目（要补 target）
        if 'name' in obj and 'config' not in obj and 'groups' not in obj:
            if any(k in obj for k in MOVED) or ('script' in obj and isinstance(obj.get('fields'), dict)):
                _entry(obj)
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
    raise NotImplementedError('技能设置不能自动拆回原来的列')
