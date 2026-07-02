"""SDD 64v2 bunker electronics

Revision ID: b639bf6cca68
Revises: 12f6f91d3989
Create Date: 2026-07-02 08:09:00.759714
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b639bf6cca68'
down_revision: str | None = '12f6f91d3989'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 64 v2: electrónica producida por el búnker (moneda de repoblación).
    with op.batch_alter_table('bunkers', schema=None) as batch_op:
        batch_op.add_column(sa.Column('electronics', sa.Float(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('bunkers', schema=None) as batch_op:
        batch_op.drop_column('electronics')
