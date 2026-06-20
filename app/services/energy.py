"""Energy regenerates lazily by timestamp — no per-user cron, scales infinitely."""
from datetime import UTC, datetime


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def compute_energy(
    stored: float,
    updated_at: datetime,
    now: datetime,
    regen_per_hour: float,
    cap: float,
) -> float:
    """Pure: current energy = stored + elapsed_hours * regen, clamped to cap."""
    elapsed_h = max(0.0, (_aware(now) - _aware(updated_at)).total_seconds() / 3600.0)
    return min(cap, stored + elapsed_h * regen_per_hour)


def apply_regen(player, now: datetime, regen_per_hour: float, cap: float) -> None:
    """Advance a Player's energy to `now` and reset its timestamp."""
    player.energy = compute_energy(
        player.energy, player.energy_updated_at, now, regen_per_hour, cap
    )
    player.energy_updated_at = now


def spend_energy(player, amount: float, now: datetime, regen_per_hour: float, cap: float) -> bool:
    """Try to spend energy. Returns False (without mutating) if insufficient."""
    apply_regen(player, now, regen_per_hour, cap)
    if player.energy < amount:
        return False
    player.energy -= amount
    return True
