"""SDD 62 garrison: AttackMission.source_base_id

Revision ID: cfcbb3d53d70
Revises: a2749737ed1d
Create Date: 2026-06-30 16:45:29.703472
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cfcbb3d53d70'
down_revision: str | None = 'a2749737ed1d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 62: la base de la que salen las tropas (guarnición). NULL = pool global (histórico).
    with op.batch_alter_table('attack_missions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('source_base_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('attack_missions', schema=None) as batch_op:
        batch_op.drop_column('source_base_id')
