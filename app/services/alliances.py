"""Alliances: players group up and can't attack each other (non-aggression is always on).
The alliance TYPE (data-driven in content/alliances.yaml) unlocks extra benefits:
shared_bonus, mutual_defense, shared_vision, trade, shared_unit_tech."""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.models import Alliance, AllianceMessage, Player


class AllianceError(Exception):
    pass


async def _alliance_of(session: AsyncSession, player_id: int) -> Alliance | None:
    player = await session.get(Player, player_id)
    if player is None or player.alliance_id is None:
        return None
    return await session.get(Alliance, player.alliance_id)


def _type_spec(alliance: Alliance | None) -> dict:
    if alliance is None:
        return {}
    return get_content().alliance_types.get(alliance.type, {})


async def has_benefit(session: AsyncSession, player_id: int, benefit: str) -> bool:
    alliance = await _alliance_of(session, player_id)
    return benefit in _type_spec(alliance).get("benefits", [])


async def shared_bonus_mult(session: AsyncSession, player_id: int, effect: str) -> float:
    alliance = await _alliance_of(session, player_id)
    spec = _type_spec(alliance)
    if "shared_bonus" not in spec.get("benefits", []):
        return 1.0
    return float(spec.get("shared_bonus", {}).get(effect, 1.0))


async def shared_unit_tech_mult(session: AsyncSession, player_id: int, effect: str) -> float:
    """Each distinct member race contributes its unit_perk for `effect` to all members."""
    alliance = await _alliance_of(session, player_id)
    if "shared_unit_tech" not in _type_spec(alliance).get("benefits", []):
        return 1.0
    content = get_content()
    mult, seen = 1.0, set()
    for m in await members(session, alliance.id):
        if m.race_key in seen:
            continue
        seen.add(m.race_key)
        mult *= float(content.races.get(m.race_key, {}).get("unit_perk", {}).get(effect, 1.0))
    return mult


async def alliance_multiplier(session: AsyncSession, player_id: int, effect: str) -> float:
    """Combined alliance multiplier (shared_bonus × shared_unit_tech) for an effect."""
    return (
        await shared_bonus_mult(session, player_id, effect)
        * await shared_unit_tech_mult(session, player_id, effect)
    )


async def mutual_defense_flat(session: AsyncSession, defender: Player) -> float:
    """Allies lend 25% of their unit defense when a member is attacked (if benefit active)."""
    if not await has_benefit(session, defender.id, "mutual_defense"):
        return 0.0
    from app.services.training import player_units

    content = get_content()
    total = 0.0
    for ally in await members(session, defender.alliance_id):
        if ally.id == defender.id:
            continue
        units = await player_units(session, ally.id)
        total += sum(
            q * content.units.get(k, {}).get("stats", {}).get("defense", 0)
            for k, q in units.items()
        )
    return 0.25 * total


async def transfer(
    session: AsyncSession, sender: Player, to_player_id: int, mineral: str, amount: float
) -> None:
    from app.services.economy import get_or_create_stock, player_stocks

    if not await has_benefit(session, sender.id, "trade"):
        raise AllianceError("Tu tipo de alianza no permite comercio.")
    target = await session.get(Player, to_player_id)
    if target is None or target.alliance_id != sender.alliance_id or target.id == sender.id:
        raise AllianceError("El destinatario no es un aliado.")
    if mineral not in get_content().minerals:
        raise AllianceError(f"Mineral desconocido: {mineral}")
    if amount <= 0:
        raise AllianceError("Cantidad invalida.")
    stocks = await player_stocks(session, sender.id)
    if stocks.get(mineral, 0.0) < amount:
        raise AllianceError(f"No tenes suficiente {mineral}.")
    (await get_or_create_stock(session, sender.id, mineral, sender.planet_key)).amount -= amount
    (await get_or_create_stock(session, target.id, mineral, target.planet_key)).amount += amount


async def member_count(session: AsyncSession, alliance_id: int) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).select_from(Player).where(Player.alliance_id == alliance_id)
            )
        ).scalar_one()
    )


async def create_alliance(
    session: AsyncSession, player: Player, name: str, tag: str, type_: str = "full"
) -> Alliance:
    name, tag = name.strip(), tag.strip()
    if not (3 <= len(name) <= 60) or not (1 <= len(tag) <= 8):
        raise AllianceError("Nombre (3-60) o tag (1-8) invalido.")
    if type_ not in get_content().alliance_types:
        raise AllianceError(f"Tipo de alianza desconocido: {type_}")
    if player.alliance_id is not None:
        raise AllianceError("Ya perteneces a una alianza.")
    exists = await session.execute(select(Alliance).where(Alliance.name == name))
    if exists.scalar_one_or_none() is not None:
        raise AllianceError("Ya existe una alianza con ese nombre.")
    alliance = Alliance(name=name, tag=tag, type=type_, leader_id=player.id)
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
    # Players can't infiltrate the NPC alliance (would grant immunity + benefits).
    if not player.is_npc and any(m.is_npc for m in await members(session, alliance_id)):
        raise AllianceError("No podes unirte a una alianza de NPCs.")
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


async def post_message(session: AsyncSession, player: Player, body: str) -> AllianceMessage:
    """Post a chat message to the player's alliance (members only)."""
    if player.alliance_id is None:
        raise AllianceError("No estas en ninguna alianza.")
    body = body.strip()
    if not (1 <= len(body) <= 500):
        raise AllianceError("Mensaje vacio o demasiado largo (max 500).")
    msg = AllianceMessage(alliance_id=player.alliance_id, sender_id=player.id, body=body)
    session.add(msg)
    await session.flush()
    return msg


async def list_messages(
    session: AsyncSession, player: Player, limit: int = 50
) -> list[AllianceMessage]:
    """The latest messages of the player's alliance, oldest-first (members only)."""
    if player.alliance_id is None:
        raise AllianceError("No estas en ninguna alianza.")
    res = await session.execute(
        select(AllianceMessage)
        .where(AllianceMessage.alliance_id == player.alliance_id)
        .order_by(AllianceMessage.id.desc())
        .limit(limit)
    )
    return list(reversed(res.scalars().all()))
