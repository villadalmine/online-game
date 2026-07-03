"""SDD 64: búnkeres — cavar, construir salas, economía lazy comida/agua/gente."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Bunker, BunkerRoom, Player, PlayerTech
from app.services.bunkers import BunkerError, advance_bunker, build_room, dig
from app.services.onboarding import onboard_player


async def _player(session, name="digger"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    p.energy = 100000
    session.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
    await session.commit()
    return p, base


async def test_dig_requires_flag(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "bunkers_enabled", False)
    p, base = await _player(session)
    try:
        await dig(session, p, base.id)
        raise AssertionError("con el flag OFF no se cava")
    except BunkerError:
        pass


async def test_dig_and_build_room(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session)
    b = await dig(session, p, base.id)
    await session.commit()
    assert b.food_health == 100.0
    # no se puede cavar dos veces la misma base
    try:
        await dig(session, p, base.id)
        raise AssertionError("no se cava dos veces")
    except BunkerError:
        pass
    room = await build_room(session, p, base.id, "farm", 0)
    await session.commit()
    assert room.room_key == "farm" and room.status == "building"
    # la celda queda ocupada
    try:
        await build_room(session, p, base.id, "canteen", 0)
        raise AssertionError("celda ocupada")
    except BunkerError:
        pass
    # SDD 69: sin celda (cell=None) se auto-acomoda en la primera libre (no la 0, ya tomada)
    auto = await build_room(session, p, base.id, "canteen", None)
    await session.commit()
    assert auto.cell != 0 and auto.status == "building"


async def test_terraformer_room_enlarges_bunker(session, monkeypatch):
    # SDD 75: una sala terraformer ACTIVA agranda el lado de la grilla (+grid_bonus) con el flag ON.
    from app.content.registry import get_content
    from app.services.bunkers import grid_bonus, grid_side
    from app.services.economy import get_or_create_stock
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    monkeypatch.setattr(s, "terraforming_enabled", True)
    p, base = await _player(session)
    session.add(PlayerTech(player_id=p.id, tech_key="terraforming"))
    b = await dig(session, p, base.id)
    for role in ("structural", "energetic", "advanced"):   # material para pagar el terraformador
        mineral = get_content().resolve_role(p.race_key, role)
        (await get_or_create_stock(session, p.id, mineral, base.planet_key)).amount = 100000
    await session.commit()
    side0 = grid_side(b, s)
    assert await grid_bonus(session, b.id, s) == 0     # todavía sin terraformador
    room = await build_room(session, p, base.id, "terraformer", 0)
    room.status = "active"                              # simulamos que terminó de construirse
    await session.commit()
    bonus = await grid_bonus(session, b.id, s)
    assert bonus == 3 and grid_side(b, s, bonus) == side0 + 3
    # con el flag OFF, el mismo terraformador no agranda nada
    monkeypatch.setattr(s, "terraforming_enabled", False)
    assert await grid_bonus(session, b.id, s) == 0


async def test_quantum_teleport_moves_electronics(session, monkeypatch):
    # SDD 76: con Puerta cuántica activa en el origen, teletransporta electrónica a otro búnker (−merma).
    from app.services.bunkers import quantum_teleport
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    monkeypatch.setattr(s, "quantum_teleport_enabled", True)
    monkeypatch.setattr(s, "quantum_teleport_fee", 0.1)
    p, base = await _player(session)
    b1 = await dig(session, p, base.id)
    # segundo búnker en otra base del jugador (colonia): creamos una base extra simple
    from app.models import Base_
    b2base = Base_(player_id=p.id, planet_key=base.planet_key, name="col", base_type="surface")
    session.add(b2base)
    await session.flush()
    b2 = await dig(session, p, b2base.id)
    b1.electronics = 1000.0
    # sin puerta activa → falla
    try:
        await quantum_teleport(session, p, base.id, b2base.id, 500)
        raise AssertionError("sin puerta no teletransporta")
    except BunkerError:
        pass
    # puerta cuántica activa en el origen
    session.add(BunkerRoom(bunker_id=b1.id, room_key="quantum_gate", cell=0, status="active",
                           created_at=datetime.now(UTC)))
    await session.commit()
    r = await quantum_teleport(session, p, base.id, b2base.id, 500)
    assert r["sent"] == 500 and r["received"] == 450.0    # merma 10%
    assert round(b1.electronics) == 500 and round(b2.electronics) == 450
    # dos búnkeres iguales → error
    try:
        await quantum_teleport(session, p, base.id, base.id, 10)
        raise AssertionError("mismo búnker")
    except BunkerError:
        pass


async def test_dig_deeper_expands_grid(session, monkeypatch):
    # SDD 69 Fase 1: con underground_construction + flag, excavar agranda la grilla (+1 lado) y
    # habilita celdas que antes estaban fuera del mapa.
    from app.content.registry import get_content
    from app.services.bunkers import dig_deeper, grid_side
    from app.services.economy import get_or_create_stock
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    monkeypatch.setattr(s, "bunker_expansion_enabled", True)
    p, base = await _player(session)
    session.add(PlayerTech(player_id=p.id, tech_key="underground_construction"))
    await dig(session, p, base.id)
    await session.commit()
    b = (await session.execute(select(Bunker).where(Bunker.base_id == base.id))).scalar_one()
    side0 = grid_side(b, s)
    # una celda fuera del mapa base falla…
    try:
        await build_room(session, p, base.id, "farm", side0 * side0)
        raise AssertionError("celda fuera del mapa base")
    except BunkerError:
        pass
    # fondear estructural y excavar
    struct = get_content().resolve_role(p.race_key, "structural")
    (await get_or_create_stock(session, p.id, struct, base.planet_key)).amount = 100000
    await dig_deeper(session, p, base.id)
    await session.commit()
    b = (await session.execute(select(Bunker).where(Bunker.base_id == base.id))).scalar_one()
    assert b.grid_level == 1 and grid_side(b, s) == side0 + 1
    # ahora esa celda entra
    room = await build_room(session, p, base.id, "farm", side0 * side0)
    await session.commit()
    assert room.cell == side0 * side0


async def test_vault_stash_withdraw_safe_from_loot(session, monkeypatch):
    # SDD 69 Fase 1: la bóveda guarda mineral a salvo del saqueo (sale de la superficie → el loot,
    # que solo toca ResourceStock, no lo alcanza). Topeado por la capacidad de las salas `vault`.
    from app.services.bunkers import build_room, bunker_state, dig, stash, withdraw
    from app.services.economy import get_or_create_stock, planet_stocks
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    p, base = await _player(session)
    await dig(session, p, base.id)
    # fondear para construir la bóveda; activarla; RECIÉN AHÍ fijar 100000 (el build cuesta mineral)
    (await get_or_create_stock(session, p.id, "iron", "mars")).amount = 100000
    room = await build_room(session, p, base.id, "vault", 0)
    room.status = "active"
    (await get_or_create_stock(session, p.id, "iron", "mars")).amount = 100000   # neto post-build
    await session.commit()
    # sin bóveda no habría capacidad; con una vault activa hay 5000
    r = await stash(session, p, base.id, "iron", 1000)
    await session.commit()
    assert r["stashed"] == 1000 and r["vault_cap"] == 5000
    surf = await planet_stocks(session, p.id, "mars")
    assert surf.get("iron", 0) == 99000                 # salió de la superficie (a salvo del loot)
    me = await bunker_state(session, p)
    assert me[0]["vault"].get("iron") == 1000
    # tope de capacidad: no entra más de lo que cabe
    r2 = await stash(session, p, base.id, "iron", 999999)
    assert r2["stashed"] == 4000                         # 5000 cap − 1000 ya guardado
    # sacar vuelve a la superficie
    w = await withdraw(session, p, base.id, "iron", 500)
    await session.commit()
    assert w["withdrawn"] == 500
    assert (await planet_stocks(session, p.id, "mars")).get("iron") == 95500


async def test_evacuate_founds_colony_and_seeds_from_vault(session, monkeypatch):
    # SDD 69 Fase 3: evacuar → funda una colonia con colony_ship y la siembra con la bóveda (topeado
    # por la carga de la nave). La reserva a salvo se muda a un mundo habitable.
    from app.models import Base_, UnitStock
    from app.services.bunkers import build_room, dig, evacuate, stash
    from app.services.economy import get_or_create_stock, planet_stocks
    from app.services.training import player_units
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    p = Player(username="evacuee", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "earth", "terran")
    p.energy = 100000
    for t in ("bunker_engineering", "antigravity", "thermal_shielding"):  # mars ok p/terran
        session.add(PlayerTech(player_id=p.id, tech_key=t))
    session.add(UnitStock(player_id=p.id, unit_key="colony_ship", quantity=1))
    await session.commit()
    await dig(session, p, base.id)
    room = await build_room(session, p, base.id, "vault", 0)
    room.status = "active"
    (await get_or_create_stock(session, p.id, "iron", "earth")).amount = 100000
    await session.commit()
    await stash(session, p, base.id, "iron", 3000)
    await session.commit()
    r = await evacuate(session, p, base.id, "mars", {"iron": 3000})
    await session.commit()
    assert r["planet"] == "mars"
    bases = (await session.execute(select(Base_).where(Base_.player_id == p.id))).scalars().all()
    assert "mars" in {b.planet_key for b in bases}
    assert (await planet_stocks(session, p.id, "mars")).get("iron") == 3000   # sembrado
    assert (await player_units(session, p.id)).get("colony_ship", 0) == 0     # nave consumida


async def test_dig_deeper_needs_tech_and_flag(session, monkeypatch):
    from app.services.bunkers import dig_deeper
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    monkeypatch.setattr(s, "bunker_expansion_enabled", True)
    p, base = await _player(session)   # sin underground_construction
    await dig(session, p, base.id)
    await session.commit()
    try:
        await dig_deeper(session, p, base.id)
        raise AssertionError("sin la tech no se excava")
    except BunkerError:
        pass


async def test_meters_decay_without_rooms(session, monkeypatch):
    # SDD 64: sin salas que produzcan, los medidores decaen con el tiempo (base del sabotaje).
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session)
    b = await dig(session, p, base.id)
    b.updated_at = datetime.now(UTC) - timedelta(hours=10)
    await session.commit()
    await advance_bunker(session, p)
    await session.commit()
    b = await session.get(Bunker, b.id)
    assert b.food_health < 100.0 and b.water_health < 100.0


async def test_room_finalizes_and_feeds(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session)
    b = await dig(session, p, base.id)
    r = await build_room(session, p, base.id, "farm", 1)
    # forzar que la sala esté lista y bajar la comida para ver el regen
    r.completes_at = datetime.now(UTC) - timedelta(seconds=1)
    b.food_health = 50.0
    b.updated_at = datetime.now(UTC) - timedelta(hours=2)
    await session.commit()
    await advance_bunker(session, p)
    await session.commit()
    r = (await session.execute(
        select(BunkerRoom).where(BunkerRoom.bunker_id == b.id))).scalar_one()
    b = await session.get(Bunker, b.id)
    assert r.status == "active"
    assert b.food_health > 50.0   # la granja (food 10/h) supera el decaimiento (2/h) → sube


async def _spy_map(session, owner, target, pct=60.0):
    """Arrange: un satélite espía del atacante ya mapeó al objetivo (SDD 61)."""
    from app.models import SatelliteMission
    now = datetime.now(UTC)
    session.add(SatelliteMission(
        owner_id=owner.id, target_id=target.id, unit_key="spy_satellite", kind="spy",
        target_planet=target.planet_key or "", shield_grade=0, energy=100.0,
        discovered_pct=pct, status="orbiting", last_tick_at=now, created_at=now))
    await session.commit()


async def _raid_pair(session, monkeypatch):
    from app.services.bunkers import raid  # noqa: F401 (import check)
    s = get_settings()
    monkeypatch.setattr(s, "bunkers_enabled", True)
    monkeypatch.setattr(s, "satellites_enabled", True)
    atk, _abase = await _player(session, "raider")
    tgt, tbase = await _player(session, "victim")
    tgt.protected_until = None
    bunker = await dig(session, tgt, tbase.id)
    atk.energy = 100000
    await session.commit()
    return atk, tgt, bunker


async def test_raid_requires_satellite_intel(session, monkeypatch):
    from app.services.bunkers import raid
    atk, tgt, _b = await _raid_pair(session, monkeypatch)
    try:
        await raid(session, atk, tgt.id, "gas")
        raise AssertionError("sin intel satelital no se sabotea")
    except BunkerError as e:
        assert "mapear" in str(e).lower()


async def test_raid_gas_vent_lockdown_and_cap(session, monkeypatch):
    from app.services.bunkers import raid
    atk, tgt, bunker = await _raid_pair(session, monkeypatch)
    await _spy_map(session, atk, tgt, pct=80.0)
    # gas sin ventilación: −25 de gente
    res = await raid(session, atk, tgt.id, "gas")
    await session.commit()
    assert abs(res["people"] - 75.0) < 3, res
    # con ventilación activa, el gas pega menos
    session.add(BunkerRoom(bunker_id=bunker.id, room_key="ventilation", cell=1, status="active"))
    await session.commit()
    res2 = await raid(session, atk, tgt.id, "gas")
    await session.commit()
    assert (res["people"] - res2["people"]) < 25.0 * 0.8   # mitigado (−18.75, no −25)
    # cerradura activa → sellado
    session.add(BunkerRoom(bunker_id=bunker.id, room_key="lockdown", cell=2, status="active"))
    await session.commit()
    try:
        await raid(session, atk, tgt.id, "rats")
        raise AssertionError("la cerradura debía sellar el búnker")
    except BunkerError as e:
        assert "sellado" in str(e).lower()


async def test_raid_daily_cap(session, monkeypatch):
    from app.services.bunkers import raid
    atk, tgt, _b = await _raid_pair(session, monkeypatch)
    monkeypatch.setattr(get_settings(), "bunker_raids_per_target_per_day", 1)
    await _spy_map(session, atk, tgt, pct=80.0)
    await raid(session, atk, tgt.id, "rats")
    await session.commit()
    try:
        await raid(session, atk, tgt.id, "water")
        raise AssertionError("tope diario de sabotajes")
    except BunkerError as e:
        assert "hoy" in str(e).lower()


async def test_repopulate_spends_electronics_and_rebuilds(session, monkeypatch):
    """SDD 64 v2: la electrónica del búnker paga un set de repoblación (reconstruye edificios)."""
    from datetime import timedelta

    from app.models import Building, Bunker, BunkerRoom
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session)
    b = await dig(session, p, base.id)
    # una sala de investigación activa que produjo electrónica hace rato
    session.add(BunkerRoom(bunker_id=b.id, room_key="research_room", cell=0, status="active",
                           completes_at=datetime.now(UTC) - timedelta(seconds=1)))
    b.electronics = 500.0
    await session.commit()
    from app.services.bunkers import repopulate
    res = await repopulate(session, p, base.id, "economic")   # cuesta 120
    await session.commit()
    assert res["built"] == ["mine", "mine", "power_plant"]
    b = await session.get(Bunker, b.id)
    assert b.electronics < 500.0    # se descontó
    n = len((await session.execute(
        select(Building).where(Building.base_id == base.id,
                               Building.building_key == "mine"))).scalars().all())
    assert n >= 2


async def test_repopulate_needs_enough_electronics(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "bunkers_enabled", True)
    p, base = await _player(session)
    await dig(session, p, base.id)   # 0 electrónica
    await session.commit()
    from app.services.bunkers import BunkerError, repopulate
    try:
        await repopulate(session, p, base.id, "economic")
        raise AssertionError("sin electrónica no se repuebla")
    except BunkerError as e:
        assert "electrónica" in str(e).lower()
