"""SDD 13 — rigor científico: restricciones físicas + contenido (exosistemas/speculative)."""
from sqlalchemy import select

from app.content.registry import get_content, localize
from app.core.security import hash_password
from app.models import Base_, Building, Player, PlayerTech
from app.services.onboarding import onboard_player
from app.services.training import TrainingError, start_training


def test_exosystems_real_and_speculative_content():
    r = get_content()
    # exosistemas REALES nuevos con system + sources
    for key, system in [("proxima_b", "Proxima Centauri"), ("trappist_1e", "TRAPPIST-1")]:
        p = r.planets[key]
        assert p["canon"] == "real" and p["system"] == system and p.get("sources")
    # planeta speculative: requiere rationale (no sources)
    nt = r.planets["nova_terra"]
    assert nt["canon"] == "speculative" and nt.get("rationale")


def test_every_real_planet_has_sources_and_speculative_has_rationale():
    r = get_content()
    for key, p in r.planets.items():
        canon = p.get("canon")
        if canon == "real":
            assert p.get("sources"), f"{key} real sin sources"
        if canon == "speculative":
            assert p.get("rationale"), f"{key} speculative sin rationale"


def test_system_field_is_localized_to_en():
    r = get_content()
    assert localize(r.planets["earth"], "en")["system"] == "Solar System"
    assert localize(r.planets["nova_terra"], "en")["system"] == "Frontier (hypothetical)"


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
    session.add(PlayerTech(player_id=player.id, tech_key="weapons"))  # SDD 1: aviones piden weapons
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
