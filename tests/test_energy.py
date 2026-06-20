from datetime import UTC, datetime, timedelta

from app.services.energy import compute_energy


def test_regen_accumulates():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert compute_energy(0, t0, t0 + timedelta(hours=2), 10, 240) == 20


def test_regen_clamped_to_cap():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert compute_energy(100, t0, t0 + timedelta(hours=100), 10, 240) == 240


def test_no_negative_elapsed():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # clock skew / past now -> no loss
    assert compute_energy(50, t0, t0 - timedelta(hours=5), 10, 240) == 50
