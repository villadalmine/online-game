"""SDD 62 garrison: UnitStock.base_id

Revision ID: a2749737ed1d
Revises: 4e2f998dc2ef
Create Date: 2026-06-30 16:29:45.685749
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a2749737ed1d'
down_revision: str | None = '4e2f998dc2ef'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # SDD 62: `base_id` ubica la unidad en una base (NULL = pool global, modo histórico). Se cambia el
    # unique de (player, unit) a (player, unit, base). La FK lleva nombre (SQLite batch_alter lo exige).
    with op.batch_alter_table('unit_stocks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('base_id', sa.Integer(), nullable=True))
        batch_op.drop_constraint(batch_op.f('uq_player_unit'), type_='unique')
        batch_op.create_index(batch_op.f('ix_unit_stocks_base_id'), ['base_id'], unique=False)
        batch_op.create_unique_constraint(
            'uq_player_unit_base', ['player_id', 'unit_key', 'base_id']
        )
        batch_op.create_foreign_key(
            'fk_unit_stocks_base_id', 'bases', ['base_id'], ['id'], ondelete='CASCADE'
        )


def downgrade() -> None:
    with op.batch_alter_table('unit_stocks', schema=None) as batch_op:
        batch_op.drop_constraint('fk_unit_stocks_base_id', type_='foreignkey')
        batch_op.drop_constraint('uq_player_unit_base', type_='unique')
        batch_op.drop_index(batch_op.f('ix_unit_stocks_base_id'))
        batch_op.create_unique_constraint(
            batch_op.f('uq_player_unit'), ['player_id', 'unit_key']
        )
        batch_op.drop_column('base_id')
