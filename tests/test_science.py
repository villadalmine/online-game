"""SDD 13 — rigor científico: restricciones físicas del planeta al entrenar."""
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Base_, Building, Player
from app.services.onboarding import onboard_player
from app.services.training import TrainingError, start_training


async def _player(session, name, planet, race) -> Player:
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _base_with_factory(session, player) -> Base_:
    base = (
        await session.execute(select(Base_).where(Base_.player_id == player.id))
    ).scalars().first()
    session.add(Building(base_id=base.id, building_key="factory", status="active"))
    await session.commit()
    return base


async def test_ship_requires_liquid_water(session):
    # Tierra tiene agua -> barco OK; Marte no -> bloqueado.
    earthling = await _player(session, "sailor_e", "earth", "terran")
    base_e = await _base_with_factory(session, earthling)
    order = await start_training(session, earthling, base_e, "ship", 1)
    assert order.unit_key == "ship"

    martian = await _player(session, "sailor_m", "mars", "martian")
    base_m = await _base_with_factory(session, martian)
    try:
        await start_training(session, martian, base_m, "ship", 1)
        raise AssertionError("barco sin agua debería fallar")
    except TrainingError as e:
        assert "agua" in str(e).lower()


async def test_aircraft_requires_atmosphere(session):
    # Marte tiene atmósfera (fina) -> avión OK; Mercurio no -> bloqueado.
    martian = await _player(session, "pilot_m", "mars", "martian")
    base_m = await _base_with_factory(session, martian)
    order = await start_training(session, martian, base_m, "aircraft", 1)
    assert order.unit_key == "aircraft"

    mercurian = await _player(session, "pilot_h", "mercury", "terran")
    base_h = await _base_with_factory(session, mercurian)
    try:
        await start_training(session, mercurian, base_h, "aircraft", 1)
        raise AssertionError("avión sin atmósfera debería fallar")
    except TrainingError as e:
        assert "atmósfera" in str(e).lower() or "atmosfera" in str(e).lower()
