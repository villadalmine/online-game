"""ai_brain_stats on player

Revision ID: d7ff71187c52
Revises: 81577f5a3965
Create Date: 2026-07-04 18:27:28.957397
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7ff71187c52'
down_revision: str | None = '81577f5a3965'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 81 v2: rendimiento del cerebro por ruta (readout + auto-switch). Solo la columna nueva;
    # la deriva de intel_reports (uq rename) es espuria del autogen y se descarta.
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(sa.Column('ai_brain_stats', sa.Text(), server_default='{}', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('ai_brain_stats')
