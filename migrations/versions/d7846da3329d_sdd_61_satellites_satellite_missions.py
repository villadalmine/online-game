"""SDD 61 satellites: satellite_missions

Revision ID: d7846da3329d
Revises: b8f1c2a4e6d0
Create Date: 2026-06-30 18:07:10.117255
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7846da3329d'
down_revision: str | None = 'b8f1c2a4e6d0'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 61: satélites en órbita (recon propio + espía que mapea al enemigo).
    op.create_table('satellite_missions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner_id', sa.Integer(), nullable=False),
    sa.Column('target_id', sa.Integer(), nullable=True),
    sa.Column('unit_key', sa.String(length=50), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('target_planet', sa.String(length=50), nullable=False),
    sa.Column('shield_grade', sa.Integer(), server_default='0', nullable=False),
    sa.Column('energy', sa.Float(), nullable=False),
    sa.Column('discovered_pct', sa.Float(), server_default='0', nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('last_tick_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['owner_id'], ['players.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['target_id'], ['players.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('satellite_missions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_satellite_missions_owner_id'), ['owner_id'], unique=False)
        batch_op.create_index(
            batch_op.f('ix_satellite_missions_target_id'), ['target_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('satellite_missions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_satellite_missions_target_id'))
        batch_op.drop_index(batch_op.f('ix_satellite_missions_owner_id'))
    op.drop_table('satellite_missions')
