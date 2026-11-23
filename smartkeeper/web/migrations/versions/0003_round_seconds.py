"""round times in seconds

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from alembic import op


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 游戏内时间改成秒（连续时间回合）。旧局的世界状态仍是分钟制，不再兼容。
    with op.batch_alter_table('round') as batch:
        batch.alter_column('started_minute', new_column_name='started_second')
        batch.alter_column('ended_minute', new_column_name='ended_second')
    op.execute('UPDATE round SET started_second = started_second * 60, ended_second = ended_second * 60')


def downgrade() -> None:
    op.execute('UPDATE round SET started_second = started_second / 60, ended_second = ended_second / 60')
    with op.batch_alter_table('round') as batch:
        batch.alter_column('started_second', new_column_name='started_minute')
        batch.alter_column('ended_second', new_column_name='ended_minute')
