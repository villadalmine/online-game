"""SDD 67 nuclear tribute

Revision ID: 79fc068c4f1e
Revises: 623fd747de84
Create Date: 2026-07-02 06:58:49.934506
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '79fc068c4f1e'
down_revision: str | None = '623fd747de84'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 67: oferta de tributo del defensor sobre una salva nuclear entrante.
    with op.batch_alter_table('strike_missions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('tribute', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('strike_missions', schema=None) as batch_op:
        batch_op.drop_column('tribute')
