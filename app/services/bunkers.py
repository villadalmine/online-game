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
from app.models import Base_, Bunker, BunkerRoom, BunkerStock, Player
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


def grid_side(bunker: Bunker, settings, bonus: int = 0) -> int:
    """SDD 69/75: lado efectivo de la grilla = base + excavaciones (grid_level) + terraformación
    (`bonus`), topeado (el tope también sube con la terraformación para poder seguir excavando)."""
    return min(settings.bunker_grid_max + bonus,
               settings.bunker_grid + int(bunker.grid_level or 0) + bonus)


async def grid_bonus(session: AsyncSession, bunker_id: int, settings) -> int:
    """SDD 75: bonus de lado por salas `terraformer` ACTIVAS (data-driven `grid_bonus` del YAML).
    0 si la terraformación está apagada o no hay terraformador activo."""
    if not settings.terraforming_enabled:
        return 0
    rooms = (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == bunker_id, BunkerRoom.status == "active")
    )).scalars()
    content = get_content()
    return int(sum(content.rooms.get(r.room_key, {}).get("grid_bonus", 0) for r in rooms))


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


async def dig_deeper(session: AsyncSession, player: Player, base_id: int) -> Bunker:
    """SDD 69 Fase 1: excavar para AGRANDAR el búnker (+1 lado de grilla) cuando falta espacio.
    Requiere la tech `underground_construction`; cuesta energía + estructural (escala ×nivel)."""
    settings = get_settings()
    if not settings.bunkers_enabled or not settings.bunker_expansion_enabled:
        raise BunkerError("La expansión de búnkeres está desactivada.")
    if "underground_construction" not in await researched_techs(session, player.id):
        raise BunkerError("Requiere investigar: underground_construction.")
    bunker = await _bunker_for_base(session, base_id)
    if bunker is None or bunker.player_id != player.id:
        raise BunkerError("Primero cavá el búnker en esta base.")
    bonus = await grid_bonus(session, bunker.id, settings)   # SDD 75: terraformación sube el tope
    if grid_side(bunker, settings, bonus) >= settings.bunker_grid_max + bonus:
        raise BunkerError("El búnker ya está en su tamaño máximo.")
    base = await session.get(Base_, base_id)
    now = datetime.now(UTC)
    if not spend_energy(player, settings.bunker_dig_energy_cost, now,
                        effective_energy_regen(player, settings),
                        effective_energy_max(player, settings)):
        raise BunkerError("Energía insuficiente para excavar.")
    # costo estructural escala con el nivel actual (cada vez más profundo = más caro).
    content = get_content()
    struct = content.resolve_role(player.race_key, "structural")
    need = settings.bunker_dig_cost_structural * (int(bunker.grid_level or 0) + 1)
    here = await planet_stocks(session, player.id, base.planet_key)
    if here.get(struct, 0.0) < need:
        raise BunkerError(f"Falta {struct} en {base.planet_key} (necesita {need:g}).")
    (await get_or_create_stock(session, player.id, struct, base.planet_key)).amount -= need
    bunker.grid_level = int(bunker.grid_level or 0) + 1
    from app.services.journal import record
    await record(session, "bunker_dig_deeper", player.id, base_id=base_id,
                 grid_level=bunker.grid_level, side=grid_side(bunker, settings, bonus))
    await session.flush()
    return bunker


async def build_room(
    session: AsyncSession, player: Player, base_id: int, room_key: str, cell: int | None = None
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
    # SDD 69/75: la grilla crece con las excavaciones y con la terraformación (salas terraformer).
    side = grid_side(bunker, settings, await grid_bonus(session, bunker.id, settings))
    occupied = {r.cell for r in (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == bunker.id)
    )).scalars()}
    if cell is None or cell < 0:
        # auto-acomodar: la primera celda libre (evita el error "celda ocupada" y elegir a mano).
        cell = next((c for c in range(side * side) if c not in occupied), None)
        if cell is None:
            raise BunkerError("El búnker está lleno — excavá para agrandarlo antes de construir.")
    elif not (0 <= cell < side * side):
        raise BunkerError("Celda fuera del mapa subterráneo.")
    elif cell in occupied:
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
        # SDD 64 v2: la electrónica se acumula (sin tope), modulada por la salud de la gente (si el
        # búnker está muerto de hambre/gas, produce menos). Es la moneda de repoblación.
        elec = sum(s.get("electronics", 0) for s in active) * (b.people_health / 100.0)
        b.electronics += elec * hours
        b.updated_at = now


async def _vault_capacity(session: AsyncSession, bunker_id: int) -> float:
    """SDD 69: capacidad total de la bóveda = Σ vault_storage de las salas `vault` ACTIVAS."""
    content = get_content()
    rooms = (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == bunker_id, BunkerRoom.status == "active")
    )).scalars().all()
    return float(sum(content.rooms.get(r.room_key, {}).get("vault_storage", 0) for r in rooms))


async def _vault_stocks(session: AsyncSession, bunker_id: int) -> list[BunkerStock]:
    return list((await session.execute(
        select(BunkerStock).where(BunkerStock.bunker_id == bunker_id)
    )).scalars())


async def stash(
    session: AsyncSession, player: Player, base_id: int, mineral: str, amount: float
) -> dict:
    """SDD 69: mover mineral de la SUPERFICIE (planeta de la base) a la BÓVEDA del búnker (a salvo
    del saqueo). Topeado por la capacidad total de las salas `vault`. amount>0."""
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    amount = float(amount or 0)
    if amount <= 0:
        raise BunkerError("Cantidad inválida.")
    content = get_content()
    if mineral not in content.minerals:
        raise BunkerError(f"Mineral desconocido: {mineral}")
    bunker = await _bunker_for_base(session, base_id)
    if bunker is None or bunker.player_id != player.id:
        raise BunkerError("Primero cavá el búnker en esta base.")
    base = await session.get(Base_, base_id)
    cap = await _vault_capacity(session, bunker.id)
    if cap <= 0:
        raise BunkerError("Construí una Bóveda de materiales primero.")
    stocks = await _vault_stocks(session, bunker.id)
    used = sum(s.amount for s in stocks)
    free = cap - used
    if free <= 0:
        raise BunkerError(f"Bóveda llena ({used:.0f}/{cap:.0f}).")
    move = min(amount, free)
    here = await planet_stocks(session, player.id, base.planet_key)
    move = min(move, here.get(mineral, 0.0))
    if move <= 0:
        raise BunkerError(f"No tenés {mineral} en {base.planet_key}.")
    (await get_or_create_stock(session, player.id, mineral, base.planet_key)).amount -= move
    vs = next((s for s in stocks if s.mineral_key == mineral), None)
    if vs is None:
        vs = BunkerStock(bunker_id=bunker.id, mineral_key=mineral, amount=0.0)
        session.add(vs)
    vs.amount += move
    await session.flush()
    return {"stashed": round(move, 2), "mineral": mineral,
            "vault_used": round(used + move, 2), "vault_cap": round(cap, 2)}


async def withdraw(
    session: AsyncSession, player: Player, base_id: int, mineral: str, amount: float
) -> dict:
    """SDD 69: sacar mineral de la BÓVEDA a la superficie (planeta de la base). amount>0."""
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    amount = float(amount or 0)
    if amount <= 0:
        raise BunkerError("Cantidad inválida.")
    bunker = await _bunker_for_base(session, base_id)
    if bunker is None or bunker.player_id != player.id:
        raise BunkerError("Primero cavá el búnker en esta base.")
    base = await session.get(Base_, base_id)
    vstocks = await _vault_stocks(session, bunker.id)
    vs = next((s for s in vstocks if s.mineral_key == mineral), None)
    if vs is None or vs.amount <= 0:
        raise BunkerError(f"No hay {mineral} en la bóveda.")
    move = min(amount, vs.amount)
    vs.amount -= move
    (await get_or_create_stock(session, player.id, mineral, base.planet_key)).amount += move
    await session.flush()
    return {"withdrawn": round(move, 2), "mineral": mineral, "vault_left": round(vs.amount, 2)}


async def evacuate(
    session: AsyncSession, player: Player, base_id: int, target_planet: str,
    minerals: dict[str, float] | None = None,
) -> dict:
    """SDD 69 Fase 3: EVACUACIÓN — usás una `colony_ship` para fundar una colonia en `target_planet`
    y sembrarla con material de tu BÓVEDA (la reserva que sobrevivió). Es el "volver a salir": tu
    civilización de reserva se muda a un mundo habitable. Reusa la colonización (SDD 37). Topeado
    por la carga de la nave (`cargo`) y por lo que haya en la bóveda."""
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    bunker = await _bunker_for_base(session, base_id)
    if bunker is None or bunker.player_id != player.id:
        raise BunkerError("Primero cavá el búnker en esta base.")
    content = get_content()
    cargo = float(content.units.get("colony_ship", {}).get("stats", {}).get("cargo", 0))
    # 1) fundar la colonia con la colony_ship (valida habitabilidad/energía/tope de colonias).
    from app.services.colonization import ColonizeError, found_colony
    try:
        colony = await found_colony(session, player, target_planet, mode="surface",
                                    vehicle="colony_ship")
    except ColonizeError as exc:
        raise BunkerError(str(exc)) from exc
    # 2) sembrar la colonia con material de la bóveda (topeado por la carga de la nave).
    want = {k: float(v) for k, v in (minerals or {}).items() if v and float(v) > 0}
    vstocks = {s.mineral_key: s for s in await _vault_stocks(session, bunker.id)}
    moved: dict[str, float] = {}
    budget = cargo
    for mineral, amt in want.items():
        vs = vstocks.get(mineral)
        if vs is None or vs.amount <= 0 or budget <= 0:
            continue
        take = min(amt, vs.amount, budget)
        if take <= 0:
            continue
        vs.amount -= take
        (await get_or_create_stock(session, player.id, mineral, target_planet)).amount += take
        moved[mineral] = round(take, 2)
        budget -= take
    from app.services.journal import record
    await record(session, "bunker_evacuate", player.id, base_id=base_id,
                 target_planet=target_planet, colony_base_id=colony.id, seeded=moved)
    await session.flush()
    return {"colony_base_id": colony.id, "planet": target_planet, "seeded": moved,
            "cargo": cargo}


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


async def repopulate(
    session: AsyncSession, player: Player, base_id: int, set_key: str
) -> dict:
    """SDD 64 v2: gastá la electrónica del búnker para reconstruir un SET de edificios (emergencia,
    activos al instante) en una base propia. La electrónica es tu seguro tras un ataque."""
    settings = get_settings()
    if not settings.bunkers_enabled:
        raise BunkerError("Los búnkeres están desactivados.")
    content = get_content()
    spec = content.repop_sets.get(set_key)
    if spec is None:
        raise BunkerError(f"Set desconocido: {set_key}")
    base = await session.get(Base_, base_id)
    if base is None or base.player_id != player.id:
        raise BunkerError("Base inválida.")
    now = datetime.now(UTC)
    await advance_bunker(session, player, now)   # electrónica al día antes de cobrar
    from app.models import Building
    # SDD 78 v5: IDEMPOTENTE — reconstruí solo lo que FALTA para llegar a los conteos del set (no
    # dupliques edificios presentes). Cobra electrónica proporcional a lo que realmente se levanta.
    active = (await session.execute(
        select(Building).where(Building.base_id == base_id, Building.status == "active")
    )).scalars().all()
    set_bks = [bk for bk in spec.get("buildings", []) if bk != "headquarters"]
    want: dict[str, int] = {}
    for bk in set_bks:
        want[bk] = want.get(bk, 0) + 1
    have: dict[str, int] = {}
    for x in active:
        if x.building_key in want:
            have[x.building_key] = have.get(x.building_key, 0) + 1
    to_build: list[str] = []
    for bk, cnt in want.items():
        to_build += [bk] * max(0, cnt - have.get(bk, 0))
    if not to_build:
        raise BunkerError("Esta base ya tiene esos edificios; nada que reconstruir.")
    bunkers = (await session.execute(
        select(Bunker).where(Bunker.player_id == player.id).order_by(Bunker.id)
    )).scalars().all()
    total = sum(b.electronics for b in bunkers)
    need = round(float(spec.get("electronics", 0)) * len(to_build) / max(1, len(set_bks)), 1)
    if total < need:
        raise BunkerError(f"Electrónica insuficiente ({total:.0f}/{need:.0f}). Producila con "
                          "salas de investigación / laboratorio atómico.")
    left = need                                   # descontar de los búnkeres (en orden)
    for b in bunkers:
        take = min(b.electronics, left)
        b.electronics -= take
        left -= take
        if left <= 0:
            break
    built = []
    for bk in to_build:
        mineral = None
        if content.buildings.get(bk, {}).get("category") in ("mine", "storage"):
            mineral = content.resolve_role(player.race_key, "structural")
        session.add(Building(base_id=base_id, building_key=bk, status="active",
                             completes_at=now, production_mineral=mineral))
        built.append(bk)
    from app.services.notifications import notify
    await notify(session, player.id, "repopulated",
                 f"Repoblación ({set_key}): {len(built)} edificios reconstruidos", {"built": built})
    await session.flush()
    return {"set": set_key, "built": built, "electronics_left": round(total - need, 1)}


async def _has_teleporter(session: AsyncSession, bunker_id: int) -> bool:
    """SDD 76: ¿este búnker tiene una Puerta cuántica ACTIVA (sala con `teleporter`)?"""
    content = get_content()
    rooms = (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == bunker_id, BunkerRoom.status == "active")
    )).scalars()
    return any(content.rooms.get(r.room_key, {}).get("teleporter") for r in rooms)


async def quantum_teleport(
    session: AsyncSession, player: Player, from_base_id: int, to_base_id: int, amount: float
) -> dict:
    """SDD 76: teletransporta ELECTRÓNICA de un búnker a otro (instantáneo). El origen necesita una
    Puerta cuántica activa; una merma (`quantum_teleport_fee`) se pierde en el salto. Sirve para
    consolidar la moneda de reserva y recuperarte tras un ataque."""
    settings = get_settings()
    if not settings.bunkers_enabled or not settings.quantum_teleport_enabled:
        raise BunkerError("El teletransporte cuántico está desactivado.")
    if from_base_id == to_base_id:
        raise BunkerError("Elegí dos búnkeres distintos.")
    if amount <= 0:
        raise BunkerError("La cantidad debe ser positiva.")
    await advance_bunker(session, player)   # electrónica al día (lazy) antes de mover
    src = await _bunker_for_base(session, from_base_id)
    dst = await _bunker_for_base(session, to_base_id)
    if src is None or src.player_id != player.id or dst is None or dst.player_id != player.id:
        raise BunkerError("Búnker inválido.")
    if not await _has_teleporter(session, src.id):
        raise BunkerError("El origen necesita una Puerta cuántica activa (tech Salto cuántico).")
    if src.electronics < amount:
        raise BunkerError(f"Electrónica insuficiente ({src.electronics:.0f}/{amount:.0f}).")
    fee = max(0.0, min(0.9, settings.quantum_teleport_fee))
    received = amount * (1.0 - fee)
    src.electronics -= amount
    dst.electronics += received
    from app.services.journal import record
    await record(session, "quantum_teleport", player.id, from_base_id=from_base_id,
                 to_base_id=to_base_id, amount=amount, received=received)
    await session.flush()
    return {"from_base_id": from_base_id, "to_base_id": to_base_id, "sent": amount,
            "received": round(received, 2), "from_electronics": round(src.electronics, 2),
            "to_electronics": round(dst.electronics, 2)}


async def bunker_state(session: AsyncSession, player: Player) -> list[dict]:
    """Snapshot de los búnkeres propios (medidores + mapa de salas) para el front."""
    if not get_settings().bunkers_enabled:
        return []
    out = []
    bunkers = (await session.execute(
        select(Bunker).where(Bunker.player_id == player.id)
    )).scalars().all()
    settings = get_settings()
    content = get_content()
    for b in bunkers:
        rooms = (await session.execute(
            select(BunkerRoom).where(BunkerRoom.bunker_id == b.id)
        )).scalars().all()
        # SDD 75: bonus de terraformación (salas terraformer activas) sumado al lado de la grilla.
        bonus = int(sum(content.rooms.get(r.room_key, {}).get("grid_bonus", 0)
                    for r in rooms if r.status == "active")) if settings.terraforming_enabled else 0
        out.append({
            "id": b.id, "base_id": b.base_id,
            "food_health": round(b.food_health, 1), "water_health": round(b.water_health, 1),
            "people_health": round(b.people_health, 1),
            "electronics": round(b.electronics, 1),   # SDD 64 v2: moneda de repoblación
            "grid_level": int(b.grid_level or 0),     # SDD 69: excavaciones hechas
            "side": grid_side(b, settings, bonus),    # SDD 69/75: lado efectivo (con terraform.)
            "vault_cap": await _vault_capacity(session, b.id),   # SDD 69: bóveda de acopio
            "vault": {s.mineral_key: round(s.amount, 2)
                      for s in await _vault_stocks(session, b.id) if s.amount > 0},
            "rooms": [{"cell": r.cell, "room_key": r.room_key, "status": r.status,
                       "completes_at": r.completes_at.isoformat()} for r in rooms],
        })
    return out
