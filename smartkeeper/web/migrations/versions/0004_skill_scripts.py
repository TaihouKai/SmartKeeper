"""skill scripts: on-use effects and timed effects become a script; self. -> this.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

import json
import re
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None

# 存 JSON 的列：规则包（草稿、版本）、事件、回合、局
COLUMNS = [
    ('rule_pack_draft', 'body'),
    ('rule_pack_version', 'body'),
    ('event', 'payload'),
    ('round', 'snapshot'),
    ('round', 'draft'),
    ('round', 'submitted'),
    ('game', 'settings'),
]
# 这些键下的字符串是公式：旧写法 self.<列> 指条目的列，现在写 this.<列>
FORMULA_KEYS = {
    'formula', 'amount', 'duration', 'when', 'cast_time', 'cooldown', 'min', 'max', 'initial',
    'radius', 'perceive_multiplier', 'charges', 'per_minute',
}
_SELF = re.compile(r'(?<![\w.])self\.')
_VERB = {'damage': 'damage', 'add': 'add', 'subtract': 'sub', 'set': 'set'}


def _rename(text: str) -> str:
    return _SELF.sub('this.', text)


def _minutes(seconds: str) -> str:
    s = seconds.strip()
    return str(int(s) / 60).removesuffix('.0') if s.isdigit() else f'({s}) / 60'


def _entry(d: dict[str, Any]) -> None:
    """条目：作用效果和限时效果 -> 技能脚本。"""
    lines: list[str] = []
    effects = d.get('effects')
    if isinstance(effects, list):
        keep: list[Any] = []
        for eff in effects:
            if isinstance(eff, dict) and 'duration' in eff:
                dur = str(eff.pop('duration') or '')
                if dur.strip() and eff.get('target') and eff.get('formula'):
                    lines.append(f"target.modify({eff['target']}, {eff['formula']}, {_minutes(dur)})")
                    continue
            keep.append(eff)
        d['effects'] = keep
    actions = d.pop('actions', None)
    for a in actions if isinstance(actions, list) else []:
        if not isinstance(a, dict) or a.get('op') not in _VERB:
            continue
        who = 'self' if a.get('who') == 'self' else 'target'
        args = [str(a.get('amount') or '0')]
        if a['op'] != 'damage':
            args.insert(0, str(a.get('field')))
        dur = str(a.get('duration') or '')
        if a['op'] == 'add' and dur.strip():
            args.append(_minutes(dur))
        lines.append(f"{who}.{_VERB[a['op']]}({', '.join(args)})")
    if lines:
        old = str(d.get('script') or '').strip()
        d['script'] = '\n'.join([old, *lines] if old else lines)


def convert(obj: Any, key: str = '') -> Any:
    """返回转换后的对象（就地修改字典和列表）。"""
    if isinstance(obj, str):
        return _rename(obj) if key in FORMULA_KEYS else obj
    if isinstance(obj, list):
        return [convert(x) for x in obj]
    if isinstance(obj, dict):
        for k in list(obj):
            v = obj[k]
            if k == 'fields' and isinstance(v, dict):
                # 条目和角色卡的值：掷骰公式列里的 self.<列> 也要改
                obj[k] = {fk: convert(fv, 'formula') for fk, fv in v.items()}
            else:
                obj[k] = convert(v, k)
        if 'name' in obj and 'fields' in obj and ('actions' in obj or 'effects' in obj):
            _entry(obj)
        mod = obj.get('modifier')
        if isinstance(mod, dict):
            mod.pop('duration', None)  # 状态里的修正
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
    raise NotImplementedError('技能脚本不能自动转回作用效果')
