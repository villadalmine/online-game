"""player status pending approval (SDD 14)

Revision ID: 89031613f456
Revises: 3f208dd03b40
Create Date: 2026-06-25 10:03:39.537496
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '89031613f456'
down_revision: str | None = '3f208dd03b40'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.add_column(sa.Column('status', sa.String(length=20),
                                      server_default='active', nullable=False))
        batch_op.add_column(sa.Column('approved_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('approved_by', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('players', schema=None) as batch_op:
        batch_op.drop_column('approved_by')
        batch_op.drop_column('approved_at')
        batch_op.drop_column('status')
