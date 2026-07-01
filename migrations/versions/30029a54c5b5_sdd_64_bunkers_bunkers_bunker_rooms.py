"""SDD 64 bunkers: bunkers + bunker_rooms

Revision ID: 30029a54c5b5
Revises: d7846da3329d
Create Date: 2026-07-01 18:36:07.503617
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '30029a54c5b5'
down_revision: str | None = 'd7846da3329d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 64: búnker subterráneo + sus habitaciones.
    op.create_table('bunkers',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('player_id', sa.Integer(), nullable=False),
    sa.Column('base_id', sa.Integer(), nullable=False),
    sa.Column('food_health', sa.Float(), server_default='100', nullable=False),
    sa.Column('water_health', sa.Float(), server_default='100', nullable=False),
    sa.Column('people_health', sa.Float(), server_default='100', nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['base_id'], ['bases.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['player_id'], ['players.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('base_id', name='uq_bunker_base')
    )
    with op.batch_alter_table('bunkers', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bunkers_base_id'), ['base_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_bunkers_player_id'), ['player_id'], unique=False)

    op.create_table('bunker_rooms',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('bunker_id', sa.Integer(), nullable=False),
    sa.Column('room_key', sa.String(length=50), nullable=False),
    sa.Column('cell', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('completes_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['bunker_id'], ['bunkers.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bunker_rooms', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_bunker_rooms_bunker_id'), ['bunker_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('bunker_rooms', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bunker_rooms_bunker_id'))

    op.drop_table('bunker_rooms')
    with op.batch_alter_table('bunkers', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_bunkers_player_id'))
        batch_op.drop_index(batch_op.f('ix_bunkers_base_id'))

    op.drop_table('bunkers')
    # ### end Alembic commands ###
