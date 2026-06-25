"""transport_missions escort column

Revision ID: 3f208dd03b40
Revises: f34d016beb6d
Create Date: 2026-06-25 07:03:16.593585
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3f208dd03b40'
down_revision: str | None = 'f34d016beb6d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table('transport_missions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('escort', sa.Text(), server_default='{}', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('transport_missions', schema=None) as batch_op:
        batch_op.drop_column('escort')
