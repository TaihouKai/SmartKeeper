"""checks become code (label, dice, target, critical_success, critical_failure, success, opposed_by),
with four fixed results (critical success, success, failure, critical failure) instead of a free list of levels.

Old levels are sorted by name: critical / extreme / 大成功 -> critical_success; fumble / critical fail / 大失败 ->
critical_failure; fail / 失败 -> failure (dropped: it's what's left); the first other one -> success.

Revision ID: 0007
Revises: 0006
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = '0007'
down_revision = '0006'
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


def kind(name: str) -> str:
    n = name.lower()
    if '大成功' in n or 'extreme' in n or ('crit' in n and 'fail' not in n) or 'critical success' in n:
        return 'critical_success'
    if '大失败' in n or 'fumble' in n or ('crit' in n and 'fail' in n):
        return 'critical_failure'
    if '失败' in n or 'fail' in n or 'miss' in n or 'lose' in n or 'loss' in n:
        return 'failure'
    return 'success'


def _text(v: str) -> str:
    return json.dumps(v, ensure_ascii=False)


def check(c: dict[str, Any]) -> None:
    """一个检定：骰子、目标值、结果等级（或者已经拆好的三个条件）-> 代码。"""
    levels = c.pop('levels', None)
    out = {
        'critical_success': str(c.pop('critical_success', 'False') or 'False'),
        'success': str(c.pop('success', '') or ''),
        'critical_failure': str(c.pop('critical_failure', 'False') or 'False'),
    }
    for lv in levels if isinstance(levels, list) else []:
        if not isinstance(lv, dict):
            continue
        cond = str(lv.get('condition') or '').strip()
        k = kind(str(lv.get('name') or ''))
        if k == 'failure' or not cond:
            continue
        if k == 'success' and out['success']:
            continue  # 好几档成功：只留第一档
        if k != 'success' and out[k] != 'False':
            continue
        out[k] = cond
    lines: list[str] = []
    label = str(c.pop('label', '') or '')
    if label:
        lines.append(f'label = {_text(label)}')
    lines.append(f"dice = {str(c.pop('dice', '') or '1d20')}")
    lines.append(f"target = {str(c.pop('target', '0') or '0')}")
    lines.append(f"critical_success = {out['critical_success']}")
    lines.append(f"critical_failure = {out['critical_failure']}")
    lines.append(f"success = {out['success'] or 'None'}")  # 空着：校验会提示要写
    opp = c.pop('opposed_by', None)
    if opp:
        lines.append(f'opposed_by = {_text(str(opp))}')
    c['config'] = chr(10).join(lines)


def convert(obj: Any) -> Any:
    if isinstance(obj, list):
        return [convert(x) for x in obj]
    if isinstance(obj, dict):
        for k in list(obj):
            obj[k] = convert(obj[k])
        checks = obj.get('checks')
        if isinstance(checks, list) and 'templates' in obj:
            for c in checks:
                if isinstance(c, dict) and 'dice' in c and 'config' not in c:
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
    raise NotImplementedError('固定的结果等级不能自动转回列表')
