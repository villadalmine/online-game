"""SDD 64: búnkeres subterráneos. Cavar abre el búnker bajo una base; construís habitaciones que
regeneran los medidores de salud (comida/agua/gente, 0-100). Lazy by timestamp: `advance_bunker`
finaliza salas y ajusta los medidores por el tiempo transcurrido (regen de las salas − decaimiento).
El sabotaje (gas/ratas/agua) llega en pasos posteriores. Todo detrás de `bunkers_enabled`.
"""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Bunker, BunkerRoom, Player
from app.services.economy import get_or_create_stock, planet_stocks
from app.services.energy import spend_energy
from app.services.physics import effective_energy_max, effective_energy_regen
from app.services.research import researched_techs


class BunkerError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _bunker_for_base(session: AsyncSession, base_id: int) -> Bunker | None:
    return (await session.execute(
        select(Bunker).where(Bunker.base_id == base_id)
    )).scalar_one_or_none()


async def dig(session: AsyncSession, player: Player, base_id: int) -> Bunker:
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    if "bunker_engineering" not in await researched_techs(session, player.id):
        raise BunkerError("Requiere investigar: bunker_engineering.")
    base = await session.get(Base_, base_id)
    if base is None or base.player_id != player.id:
        raise BunkerError("Base inválida.")
    if await _bunker_for_base(session, base_id) is not None:
        raise BunkerError("Esta base ya tiene un búnker.")
    now = datetime.now(UTC)
    b = Bunker(player_id=player.id, base_id=base_id, food_health=100.0, water_health=100.0,
               people_health=100.0, updated_at=now, created_at=now)
    session.add(b)
    await session.flush()
    return b


async def build_room(
    session: AsyncSession, player: Player, base_id: int, room_key: str, cell: int
) -> BunkerRoom:
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    content = get_content()
    spec = content.rooms.get(room_key)
    if spec is None:
        raise BunkerError(f"Habitación desconocida: {room_key}")
    bunker = await _bunker_for_base(session, base_id)
    if bunker is None or bunker.player_id != player.id:
        raise BunkerError("Primero cavá el búnker en esta base.")
    rt = spec.get("requires_tech")
    if rt and rt not in await researched_techs(session, player.id):
        raise BunkerError(f"Requiere investigar: {rt}")
    if not (0 <= cell < settings.bunker_grid * settings.bunker_grid):
        raise BunkerError("Celda fuera del mapa subterráneo.")
    taken = (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == bunker.id, BunkerRoom.cell == cell)
    )).scalar_one_or_none()
    if taken is not None:
        raise BunkerError("Esa celda ya está ocupada.")

    base = await session.get(Base_, base_id)
    now = datetime.now(UTC)
    # energía + minerales (del planeta de la base, SDD 42; costo por rol SDD 53).
    if not spend_energy(player, spec.get("energy_cost", 0), now,
                        effective_energy_regen(player, settings),
                        effective_energy_max(player, settings)):
        raise BunkerError("Energía insuficiente.")
    cost = content.resolve_cost(player.race_key, spec.get("cost", {}))
    here = await planet_stocks(session, player.id, base.planet_key)
    for mineral, amount in cost.items():
        if here.get(mineral, 0.0) < amount:
            raise BunkerError(f"Falta {mineral} en {base.planet_key} (necesita {amount:g}).")
    for mineral, amount in cost.items():
        (await get_or_create_stock(session, player.id, mineral, base.planet_key)).amount -= amount

    room = BunkerRoom(bunker_id=bunker.id, room_key=room_key, cell=cell, status="building",
                      completes_at=now + timedelta(seconds=spec.get("build_seconds", 0)),
                      created_at=now)
    session.add(room)
    await session.flush()
    return room


def _clamp(v: float) -> float:
    return max(0.0, min(100.0, v))


async def advance_bunker(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> None:
    """Finaliza salas vencidas y ajusta los medidores por el tiempo (regen salas − decaimiento)."""
    settings = get_settings()
    if not settings.bunkers_enabled:
        return
    now = now or datetime.now(UTC)
    content = get_content()
    bunkers = (await session.execute(
        select(Bunker).where(Bunker.player_id == player.id)
    )).scalars().all()
    for b in bunkers:
        rooms = (await session.execute(
            select(BunkerRoom).where(BunkerRoom.bunker_id == b.id)
        )).scalars().all()
        for r in rooms:
            if r.status == "building" and _aware(r.completes_at) <= now:
                r.status = "active"
        hours = (now - _aware(b.updated_at)).total_seconds() / 3600.0
        if hours <= 0:
            continue
        active = [content.rooms.get(r.room_key, {}) for r in rooms if r.status == "active"]
        food_rate = sum(s.get("food", 0) for s in active) - settings.bunker_meter_decay_per_hour
        water_rate = sum(s.get("water", 0) for s in active) - settings.bunker_meter_decay_per_hour
        people_rate = sum(s.get("people", 0) for s in active) - settings.bunker_meter_decay_per_hour
        # gente extra-castigada si falta comida o agua (hambre/sed).
        if b.food_health < 20 or b.water_health < 20:
            people_rate -= settings.bunker_meter_decay_per_hour * 2
        b.food_health = _clamp(b.food_health + food_rate * hours)
        b.water_health = _clamp(b.water_health + water_rate * hours)
        b.people_health = _clamp(b.people_health + people_rate * hours)
        b.updated_at = now


async def raid(
    session: AsyncSession, attacker: Player, target_id: int, action: str
) -> dict:
    """SDD 64 §3.6: incursión de SABOTAJE al búnker de un rival. Requiere haberlo MAPEADO con
    satélites (≥ `bunker_raid_min_map_pct`); una `lockdown` ACTIVA del defensor sella la entrada.
    Acciones: gas (baja gente; mitiga la ventilación), rats (pudre comida), water (contamina)."""
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    if action not in ("gas", "rats", "water"):
        raise BunkerError(f"Sabotaje desconocido: {action}")
    target = await session.get(Player, target_id)
    if target is None or target.id == attacker.id:
        raise BunkerError("Objetivo inválido.")
    if attacker.alliance_id is not None and attacker.alliance_id == target.alliance_id:
        raise BunkerError("No podés sabotear a un aliado.")
    now = datetime.now(UTC)
    if not target.is_npc and target.protected_until is not None:
        prot = target.protected_until
        if (prot if prot.tzinfo else prot.replace(tzinfo=UTC)) > now:
            raise BunkerError("Ese jugador está bajo protección de novato.")
    # gate de INTEL (SDD 61): tenés que haber mapeado el búnker con tus satélites espía.
    from app.services.satellites import satellites_state
    _sats, maps = await satellites_state(session, attacker)
    pct = (maps.get(str(target_id)) or {}).get("pct", 0.0)
    if pct < settings.bunker_raid_min_map_pct:
        raise BunkerError(
            f"Necesitás mapear al rival con satélites (≥{settings.bunker_raid_min_map_pct:g}%; "
            f"tenés {pct:g}%)."
        )
    bunker = (await session.execute(
        select(Bunker).where(Bunker.player_id == target_id).order_by(Bunker.id)
    )).scalars().first()
    if bunker is None:
        raise BunkerError("Ese rival no tiene búnker.")
    rooms = (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == bunker.id, BunkerRoom.status == "active")
    )).scalars().all()
    content = get_content()
    if any(content.rooms.get(r.room_key, {}).get("lock") for r in rooms):
        raise BunkerError("El búnker está sellado (cerradura activa).")
    # tope diario por (atacante, objetivo) — cruza SDD 55 (anti-farmeo).
    from datetime import timedelta

    from sqlalchemy import func

    from app.models import BunkerRaid
    day_start = now - timedelta(seconds=86400)
    done = (await session.execute(
        select(func.count(BunkerRaid.id)).where(
            BunkerRaid.attacker_id == attacker.id, BunkerRaid.target_id == target_id,
            BunkerRaid.created_at >= day_start)
    )).scalar_one()
    if done >= settings.bunker_raids_per_target_per_day:
        raise BunkerError("Ya saboteaste a ese rival demasiado hoy (anti-abuso).")
    if not spend_energy(attacker, settings.bunker_raid_energy_cost, now,
                        effective_energy_regen(attacker, settings),
                        effective_energy_max(attacker, settings)):
        raise BunkerError("Energía insuficiente para la incursión.")

    # aplicar el sabotaje sobre el estado ACTUAL (advance primero, no sobre medidores viejos).
    await advance_bunker(session, target, now)
    if action == "gas":
        vents = sum(1 for r in rooms if content.rooms.get(r.room_key, {}).get("vent"))
        mitig = min(0.9, vents * settings.bunker_vent_mitigation)
        dmg = settings.bunker_gas_damage * (1.0 - mitig)
        bunker.people_health = _clamp(bunker.people_health - dmg)
    elif action == "rats":
        dmg = settings.bunker_sabotage_damage
        bunker.food_health = _clamp(bunker.food_health - dmg)
    else:   # water
        dmg = settings.bunker_sabotage_damage
        bunker.water_health = _clamp(bunker.water_health - dmg)
    session.add(BunkerRaid(attacker_id=attacker.id, target_id=target_id,
                           bunker_id=bunker.id, action=action, created_at=now))
    from app.services.notifications import notify
    await notify(session, target_id, "bunker_raided",
                 f"¡Sabotaje en tu búnker ({action})!",
                 {"action": action, "damage": round(dmg, 1), "by": attacker.username})
    from app.services.journal import record
    await record(session, "bunker_raid", attacker.id, target_id=target_id,
                 action=action, damage=round(dmg, 1))
    await session.flush()
    return {"action": action, "damage": round(dmg, 1),
            "food": round(bunker.food_health, 1), "water": round(bunker.water_health, 1),
            "people": round(bunker.people_health, 1)}


async def bunker_state(session: AsyncSession, player: Player) -> list[dict]:
    """Snapshot de los búnkeres propios (medidores + mapa de salas) para el front."""
    if not get_settings().bunkers_enabled:
        return []
    out = []
    bunkers = (await session.execute(
        select(Bunker).where(Bunker.player_id == player.id)
    )).scalars().all()
    for b in bunkers:
        rooms = (await session.execute(
            select(BunkerRoom).where(BunkerRoom.bunker_id == b.id)
        )).scalars().all()
        out.append({
            "id": b.id, "base_id": b.base_id,
            "food_health": round(b.food_health, 1), "water_health": round(b.water_health, 1),
            "people_health": round(b.people_health, 1),
            "rooms": [{"cell": r.cell, "room_key": r.room_key, "status": r.status,
                       "completes_at": r.completes_at.isoformat()} for r in rooms],
        })
    return out
