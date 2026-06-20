from datetime import UTC, datetime, timedelta

from app.services.production import compute_mine_output


def test_output_scales_with_abundance():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    # 1h at 60/h with abundance 1.5 -> 90
    assert compute_mine_output(t0, t0 + timedelta(hours=1), 60, 1.5) == 90


def test_zero_elapsed_zero_output():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    assert compute_mine_output(t0, t0, 60, 1.0) == 0
