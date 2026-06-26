"""player active_power_plants para tope/regen de energia

Revision ID: 1bf3ad4fdcc3
Revises: 89031613f456
Create Date: 2026-06-26 19:02:56.724629
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '1bf3ad4fdcc3'
down_revision: str | None = '89031613f456'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Plantas de energía activas cacheadas (suben tope/regen). server_default '0' para filas existentes.
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('active_power_plants', sa.Integer(), server_default='0', nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('active_power_plants')
