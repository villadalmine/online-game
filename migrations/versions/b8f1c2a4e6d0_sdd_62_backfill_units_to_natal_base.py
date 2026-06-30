"""SDD 62 garrison: backfill de unidades globales a la base natal

Antes de prender `garrison_enabled`, las unidades existentes viven en `base_id=NULL` (pool global).
Con guarnición el combate usa solo las unidades de la base atacada → sin este backfill cada base
quedaría indefensa y nadie podría atacar. Acá asignamos cada fila NULL a la base natal (la primera
base del jugador). Idempotente y seguro con el flag OFF (player_units suma igual).

Revision ID: b8f1c2a4e6d0
Revises: 5d27e1bf7a19
Create Date: 2026-06-30 17:30:00.000000
"""
from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8f1c2a4e6d0'
down_revision: str | None = '5d27e1bf7a19'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Asignar las unidades globales (base_id NULL) a la base natal del jugador (la de menor id).
    op.execute(
        """
        UPDATE unit_stocks
           SET base_id = (
               SELECT MIN(b.id) FROM bases b WHERE b.player_id = unit_stocks.player_id
           )
         WHERE base_id IS NULL
           AND EXISTS (SELECT 1 FROM bases b WHERE b.player_id = unit_stocks.player_id)
        """
    )


def downgrade() -> None:
    # No se puede saber qué filas eran NULL antes; no-op (el backfill no es reversible con seguridad).
    pass
