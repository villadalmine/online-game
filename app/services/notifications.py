"""Notifications: emitted at the server-side moments where state changes (battle
resolved, fleet returned, queue finished, incoming attack...). Read via the API.

`notify()` is called from the deferred processors (combat/economy/training/expedition)
exactly when an event happens, so each event is recorded once. No commit here — the
caller commits as part of its transaction."""
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Notification


async def notify(
    session: AsyncSession, player_id: int, type_: str, message: str, data: dict | None = None
) -> None:
    session.add(
        Notification(
            player_id=player_id,
            type=type_,
            message=message,
            data=json.dumps(data or {}),
        )
    )
    await session.flush()


async def list_notifications(
    session: AsyncSession, player_id: int, unread_only: bool = False, limit: int = 50
) -> list[Notification]:
    stmt = select(Notification).where(Notification.player_id == player_id)
    if unread_only:
        stmt = stmt.where(Notification.is_read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def unread_count(session: AsyncSession, player_id: int) -> int:
    stmt = select(func.count()).select_from(Notification).where(
        Notification.player_id == player_id, Notification.is_read.is_(False)
    )
    return int((await session.execute(stmt)).scalar_one())


def _sse(n: Notification) -> str:
    payload = {
        "id": n.id,
        "type": n.type,
        "message": n.message,
        "data": json.loads(n.data or "{}"),
        "created_at": n.created_at.isoformat(),
    }
    return f"data: {json.dumps(payload)}\n\n"


async def stream_events(
    maker,
    player_id: int,
    is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    interval: float = 2.0,
    once: bool = False,
) -> AsyncIterator[str]:
    """Yield SSE chunks for a player's notifications: catch-up, then live as they appear.
    `once=True` does a single poll (for tests); the endpoint loops until disconnect."""
    seen = 0
    while True:
        async with maker() as session:
            rows = list(
                (
                    await session.execute(
                        select(Notification)
                        .where(Notification.player_id == player_id, Notification.id > seen)
                        .order_by(Notification.id)
                    )
                ).scalars()
            )
        for n in rows:
            seen = n.id
            yield _sse(n)
        if once:
            return
        if is_disconnected is not None and await is_disconnected():
            return
        await asyncio.sleep(interval)


async def mark_read(
    session: AsyncSession, player_id: int, ids: list[int] | None = None
) -> int:
    """Mark some (ids) or all of a player's notifications as read. Returns count affected."""
    stmt = update(Notification).where(
        Notification.player_id == player_id, Notification.is_read.is_(False)
    )
    if ids:
        stmt = stmt.where(Notification.id.in_(ids))
    result = await session.execute(stmt.values(is_read=True))
    return result.rowcount or 0
