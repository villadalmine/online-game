from datetime import UTC, datetime, timedelta

from app.services.energy import compute_energy, energy_shortfall_msg


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


def test_shortfall_msg_shows_deficit_and_recharge():
    # falta energía y se recarga a 60/h -> faltan 30 -> ~30 min
    msg = energy_shortfall_msg(need=50, have=20, regen_per_hour=60)
    assert "necesitás 50" in msg
    assert "tenés 20" in msg
    assert "faltan 30" in msg
    assert "30 min" in msg


def test_shortfall_msg_hours_when_long():
    msg = energy_shortfall_msg(need=200, have=20, regen_per_hour=60)
    assert "faltan 180" in msg
    assert "h" in msg  # 180/60 = 3.0 h


def test_shortfall_msg_no_recharge_when_no_regen():
    msg = energy_shortfall_msg(need=50, have=20, regen_per_hour=0)
    assert "faltan 30" in msg
    assert "recarga" not in msg
