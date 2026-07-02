"""SDD 66 building condition

Revision ID: 12f6f91d3989
Revises: 79fc068c4f1e
Create Date: 2026-07-02 07:50:32.946828
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '12f6f91d3989'
down_revision: str | None = '79fc068c4f1e'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 66: condición 0-100 por edificio (averiada/sana).
    with op.batch_alter_table('buildings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('condition', sa.Float(), server_default='100', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('buildings', schema=None) as batch_op:
        batch_op.drop_column('condition')
