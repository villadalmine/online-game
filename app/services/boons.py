"""Active boons (temporary god buffs), applied lazily while not expired."""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActiveBoon


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def active_boons(
    session: AsyncSession, player_id: int, now: datetime | None = None
) -> list[ActiveBoon]:
    now = now or datetime.now(UTC)
    res = await session.execute(select(ActiveBoon).where(ActiveBoon.player_id == player_id))
    return [b for b in res.scalars() if _aware(b.expires_at) > now]


async def boon_multiplier(
    session: AsyncSession, player_id: int, effect: str, now: datetime | None = None
) -> float:
    """Combined multiplier for an effect (product of all active boons of that effect)."""
    mult = 1.0
    for boon in await active_boons(session, player_id, now):
        if boon.effect == effect:
            mult *= boon.magnitude
    return mult
