"""SDD 64 bunker raids

Revision ID: 623fd747de84
Revises: 30029a54c5b5
Create Date: 2026-07-01 18:53:43.669911
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '623fd747de84'
down_revision: str | None = '30029a54c5b5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 64: log de incursiones de sabotaje sobre búnkeres (para el tope diario + historial).
    op.create_table('bunker_raids',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('attacker_id', sa.Integer(), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=False),
    sa.Column('bunker_id', sa.Integer(), nullable=False),
    sa.Column('action', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['attacker_id'], ['players.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['bunker_id'], ['bunkers.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['players.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bunker_raids', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_bunker_raids_attacker_id'), ['attacker_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_bunker_raids_target_id'), ['target_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('bunker_raids', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bunker_raids_target_id'))
        batch_op.drop_index(batch_op.f('ix_bunker_raids_attacker_id'))

    op.drop_table('bunker_raids')
    # ### end Alembic commands ###
