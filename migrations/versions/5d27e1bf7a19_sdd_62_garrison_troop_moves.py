"""SDD 62 garrison: troop_moves

Revision ID: 5d27e1bf7a19
Revises: cfcbb3d53d70
Create Date: 2026-06-30 17:04:08.043548
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5d27e1bf7a19'
down_revision: str | None = 'cfcbb3d53d70'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 62: traslados de tropas entre bases propias (guarnición).
    op.create_table('troop_moves',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('from_base_id', sa.Integer(), nullable=False),
    sa.Column('to_base_id', sa.Integer(), nullable=False),
    sa.Column('units', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('arrives_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['from_base_id'], ['bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['to_base_id'], ['bases.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('troop_moves', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_troop_moves_player_id'), ['player_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('troop_moves', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_troop_moves_player_id'))
    op.drop_table('troop_moves')
