"""SDD 37 — colonización: compat() raza×planeta (puro) + grafo de opciones."""
from app.services.colonization import compat, options


def test_home_world_is_great_for_each_race():
    for race, planet in (("terran", "earth"), ("martian", "mars"), ("venusian", "venus")):
        o = compat(race, planet)
        assert o["verdict"] == "great" and o["can_colonize"]
        assert o["habitability"] >= 0.8


def test_no_atmosphere_is_impossible():
    # mercurio no tiene atmósfera → letal/imposible para cualquiera
    o = compat("terran", "mercury")
    assert o["verdict"] == "impossible" and not o["can_colonize"]
    assert any("atmós" in r for r in o["reasons"])


def test_extreme_heat_blocks_terran_on_venus():
    o = compat("terran", "venus")
    assert o["verdict"] == "impossible"
    # pero los venusianos sí aguantan su mundo
    assert compat("venusian", "venus")["verdict"] == "great"


def test_modifiers_scale_with_habitability():
    great = compat("terran", "earth")["modifiers"]
    assert great["production"] >= 0.99 and great["build_cost"] <= 1.01  # mundo ideal: sin penalidad


def test_options_lists_galaxy_and_flags_home():
    opts = options("terran", "milky_way")
    assert opts and all("verdict" in o for o in opts)
    home = [o for o in opts if o["is_home"]]
    assert home and home[0]["planet"] == "earth"
    # ordenado por habitabilidad desc
    habs = [o["habitability"] for o in opts]
    assert habs == sorted(habs, reverse=True)


# --- tech-gating + fundar colonia (SDD 37 estructural) ---
from sqlalchemy import select  # noqa: E402

from app.models import Base_, Player, PlayerTech, UnitStock  # noqa: E402
from app.services.colonization import ColonizeError, found_colony  # noqa: E402
from app.services.onboarding import onboard_player  # noqa: E402


def test_tech_unlocks_hostile_world():
    # Marte es imposible para terrícolas… hasta investigar antigravedad + blindaje térmico.
    assert compat("terran", "mars")["verdict"] == "impossible"
    o = compat("terran", "mars", {"antigravity", "thermal_shielding"})
    assert o["can_colonize"] and o["verdict"] != "impossible"


def test_sealed_domes_overcome_no_atmosphere():
    assert compat("terran", "mercury")["verdict"] == "impossible"
    o = compat("terran", "mercury", {"antigravity", "thermal_shielding", "sealed_domes"})
    assert o["can_colonize"]


async def _terran(session, name):
    p = Player(username=name, password_hash="x")
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "earth", "terran")
    await session.commit()
    return p


async def test_found_colony_needs_tech_then_shuttle_then_creates_base(session):
    p = await _terran(session, "colonist")
    p.energy = 999.0
    await session.commit()

    # sin tech → Marte imposible
    try:
        await found_colony(session, p, "mars")
        raise AssertionError("debía fallar sin tecnología")
    except ColonizeError as e:
        assert "colonizar" in str(e).lower()

    session.add(PlayerTech(player_id=p.id, tech_key="antigravity"))
    session.add(PlayerTech(player_id=p.id, tech_key="thermal_shielding"))
    await session.commit()
    # con tech pero sin transbordador → falla
    try:
        await found_colony(session, p, "mars")
        raise AssertionError("debía fallar sin transbordador")
    except ColonizeError as e:
        assert "transbordador" in str(e).lower()

    # con transbordador → funda la colonia en Marte
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    await session.commit()
    base = await found_colony(session, p, "mars")
    await session.commit()
    assert base.planet_key == "mars"
    bases = (await session.execute(select(Base_).where(Base_.player_id == p.id))).scalars().all()
    assert {b.planet_key for b in bases} == {"earth", "mars"}
    # el transbordador se consumió
    sh = (await session.execute(
        select(UnitStock.quantity).where(
            UnitStock.player_id == p.id, UnitStock.unit_key == "shuttle"
        )
    )).scalar_one()
    assert sh == 0


async def test_orbital_base_needs_robotics_and_opens_lethal_worlds(session):
    # SDD 37 v2: base orbital con robots → coloniza mundos letales (Mercurio, sin atmósfera),
    # pero requiere la tecnología Robótica orbital.
    p = await _terran(session, "orbiter")
    p.energy = 999.0
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=2))
    await session.commit()

    try:
        await found_colony(session, p, "mercury", mode="orbital")
        raise AssertionError("orbital debía requerir Robótica orbital")
    except ColonizeError as e:
        assert "rob" in str(e).lower()

    session.add(PlayerTech(player_id=p.id, tech_key="orbital_robotics"))
    await session.commit()
    base = await found_colony(session, p, "mercury", mode="orbital")
    await session.commit()
    assert base.base_type == "orbital" and base.planet_key == "mercury"
