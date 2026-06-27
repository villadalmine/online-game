"""Mineral production accrues lazily by timestamp, like energy."""
from datetime import UTC, datetime


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def compute_mine_output(
    last_collected_at: datetime,
    now: datetime,
    base_output_per_hour: float,
    abundance: float,
) -> float:
    """Pure: minerals produced since last collection = elapsed_h * rate * abundance."""
    elapsed_h = max(0.0, (_aware(now) - _aware(last_collected_at)).total_seconds() / 3600.0)
    return elapsed_h * base_output_per_hour * abundance


# --------------------------------------------------------------------------- #
# SDD 47 — trabajadores (staffing) + almacenamiento (silos). Funciones PURAS,
# deterministas y testeables a mano (sin DB). Ver docs/sdd-mining-workers-storage.md.
# --------------------------------------------------------------------------- #
def staffing_ratio(available_work: float, required_slots: float) -> float:
    """Cuánto rinden las minas según la mano de obra disponible, ∈ [0, 1].

    available_work = Σ trabajadores · mining_power ; required_slots = Σ mina.worker_slots.
    - Sin plazas requeridas (no hay minas) ⇒ 1.0 (no penaliza).
    - Más trabajadores ⇒ sube hasta 1.0 (techo: sobre-contratar no rinde más).
    - Más minas con los mismos obreros ⇒ required_slots sube ⇒ baja (cada mina rinde menos)."""
    if required_slots <= 0:
        return 1.0
    return max(0.0, min(1.0, available_work / required_slots))


def apply_overflow(produced: float, free: float | None) -> tuple[float, float]:
    """Reparte lo producido en (almacenado, desperdiciado) según el espacio libre.

    free=None ⇒ sin tope (almacena todo). free<=0 ⇒ todo se desperdicia (almacén lleno).
    Nunca destruye stock existente: solo limita lo NUEVO."""
    if free is None:
        return produced, 0.0
    stored = max(0.0, min(produced, free))
    return stored, max(0.0, produced - stored)
