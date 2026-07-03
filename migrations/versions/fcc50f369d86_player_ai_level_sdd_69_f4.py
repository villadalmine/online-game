"""player ai_level (SDD 69 F4)

Revision ID: fcc50f369d86
Revises: 343867d85a30
Create Date: 2026-07-03 03:23:54.117530
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fcc50f369d86'
down_revision: str | None = '343867d85a30'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_level', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('ai_level')
