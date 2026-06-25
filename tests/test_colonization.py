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
