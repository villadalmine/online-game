"""bunker_stocks vault (SDD 69)

Revision ID: 343867d85a30
Revises: a0c34235e05b
Create Date: 2026-07-03 02:19:23.187485
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '343867d85a30'
down_revision: str | None = 'a0c34235e05b'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('bunker_stocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bunker_id', sa.Integer(), nullable=False),
    sa.Column('mineral_key', sa.String(length=50), nullable=False),
    sa.Column('amount', sa.Float(), server_default='0', nullable=False),
    sa.ForeignKeyConstraint(['bunker_id'], ['bunkers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('bunker_id', 'mineral_key', name='uq_bunker_stock')
    )
    with op.batch_alter_table('bunker_stocks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bunker_stocks_bunker_id'), ['bunker_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('bunker_stocks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bunker_stocks_bunker_id'))
    op.drop_table('bunker_stocks')
