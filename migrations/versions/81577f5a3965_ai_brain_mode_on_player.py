"""ai_brain_mode on player

Revision ID: 81577f5a3965
Revises: c7d410ab31e2
Create Date: 2026-07-04 15:59:11.619685
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '81577f5a3965'
down_revision: str | None = 'c7d410ab31e2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_brain_mode', sa.String(length=10),
                                      server_default='rules', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('ai_brain_mode')
