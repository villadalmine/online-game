"""Alliances: players group up and can't attack each other. Same structured pattern
(service holds the rules; router stays thin)."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Alliance, Player


class AllianceError(Exception):
    pass


async def member_count(session: AsyncSession, alliance_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Player).where(Player.alliance_id == alliance_id)
            )
        ).scalar_one()
    )


async def create_alliance(session: AsyncSession, player: Player, name: str, tag: str) -> Alliance:
    name, tag = name.strip(), tag.strip()
    if not (3 <= len(name) <= 60) or not (1 <= len(tag) <= 8):
        raise AllianceError("Nombre (3-60) o tag (1-8) invalido.")
    if player.alliance_id is not None:
        raise AllianceError("Ya perteneces a una alianza.")
    exists = await session.execute(select(Alliance).where(Alliance.name == name))
    if exists.scalar_one_or_none() is not None:
        raise AllianceError("Ya existe una alianza con ese nombre.")
    alliance = Alliance(name=name, tag=tag, leader_id=player.id)
    session.add(alliance)
    await session.flush()
    player.alliance_id = alliance.id
    return alliance


async def join_alliance(session: AsyncSession, player: Player, alliance_id: int) -> Alliance:
    if player.alliance_id is not None:
        raise AllianceError("Ya perteneces a una alianza (salí primero).")
    alliance = await session.get(Alliance, alliance_id)
    if alliance is None:
        raise AllianceError("Alianza no encontrada.")
    player.alliance_id = alliance.id
    return alliance


async def leave_alliance(session: AsyncSession, player: Player) -> None:
    if player.alliance_id is None:
        raise AllianceError("No estas en ninguna alianza.")
    player.alliance_id = None


async def list_alliances(session: AsyncSession) -> list[tuple[Alliance, int]]:
    rows = (await session.execute(select(Alliance))).scalars()
    return [(a, await member_count(session, a.id)) for a in rows]


async def members(session: AsyncSession, alliance_id: int) -> list[Player]:
    res = await session.execute(select(Player).where(Player.alliance_id == alliance_id))
    return list(res.scalars())
