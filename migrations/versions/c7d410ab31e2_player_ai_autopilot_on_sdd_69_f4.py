"""player ai_autopilot_on (SDD 69 F4)

Revision ID: c7d410ab31e2
Revises: fcc50f369d86
Create Date: 2026-07-03 04:20:51.030132
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7d410ab31e2'
down_revision: str | None = 'fcc50f369d86'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('ai_autopilot_on', sa.Boolean(), server_default='1', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('ai_autopilot_on')
