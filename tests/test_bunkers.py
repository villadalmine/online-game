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
