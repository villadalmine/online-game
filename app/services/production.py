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
