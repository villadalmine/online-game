"""bunker grid_level (SDD 69 expansion)

Revision ID: a0c34235e05b
Revises: b639bf6cca68
Create Date: 2026-07-03 02:06:26.848112
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0c34235e05b'
down_revision: str | None = 'b639bf6cca68'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('bunkers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('grid_level', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('bunkers', schema=None) as batch_op:
        batch_op.drop_column('grid_level')
