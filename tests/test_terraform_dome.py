"""SDD 89 — Domo de terraformación: con la tech `terraforming` + el SET completo de catalizadores de
las lunas de tu galaxia, fundás un HQ-Domo en un mundo LETAL (Mercurio) que si no era imposible."""

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Player, PlayerTech, UnitStock
from app.services.colonization import (
    ColonizeError,
    compat,
    found_colony,
    galaxy_catalysts,
)
from app.services.economy import get_or_create_stock, planet_stocks
from app.services.onboarding import onboard_player


async def _player(session, name="dome_dev"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "earth", "terran")
    p.energy = 1_000_000
    await session.commit()
    return p, base


def test_galaxy_catalysts_milky_way():
    cats = galaxy_catalysts("milky_way")
    assert set(cats) == {"selenite", "phobite", "deimite", "zoozvine"}   # 1 por luna, único


async def test_mercury_is_lethal_without_dome(session):
    # Mercurio (sin atmósfera) es IMPOSIBLE de colonizar en superficie → el domo es la única vía.
    assert compat("terran", "mercury", ())["can_colonize"] is False


async def _give_dome_kit(session, p, cats):
    session.add(PlayerTech(player_id=p.id, tech_key="terraforming"))
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    for k in cats:
        (await get_or_create_stock(session, p.id, k, "earth")).amount = 5   # el set, en el natal
    await session.commit()


async def test_dome_founds_on_lethal_world_and_consumes_catalysts(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "terraform_dome_enabled", True)
    p, _ = await _player(session)
    cats = galaxy_catalysts("milky_way")
    await _give_dome_kit(session, p, cats)
    base = await found_colony(session, p, "mercury", mode="dome", vehicle="shuttle")
    await session.commit()
    assert base.planet_key == "mercury" and base.base_type == "dome"   # domo en un mundo letal
    left = await planet_stocks(session, p.id, "earth")
    for k in cats:
        assert left.get(k, 0) == 4   # consumió 1 de cada catalizador (arrancaron en 5)


async def test_dome_needs_the_full_catalyst_set(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "terraform_dome_enabled", True)
    p, _ = await _player(session, name="dome_short")
    await _give_dome_kit(session, p, ["selenite", "phobite"])   # set INCOMPLETO (faltan 2)
    try:
        await found_colony(session, p, "mercury", mode="dome", vehicle="shuttle")
        raise AssertionError("no debería fundar el domo sin el set completo")
    except ColonizeError as e:
        assert "catalizadores" in str(e).lower()


async def test_dome_needs_terraforming_tech(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "terraform_dome_enabled", True)
    p, _ = await _player(session, name="dome_notech")
    session.add(UnitStock(player_id=p.id, unit_key="shuttle", quantity=1))
    for k in galaxy_catalysts("milky_way"):
        (await get_or_create_stock(session, p.id, k, "earth")).amount = 5
    await session.commit()   # tiene el set pero NO la tech
    try:
        await found_colony(session, p, "mercury", mode="dome", vehicle="shuttle")
        raise AssertionError("no debería fundar el domo sin Terraformación")
    except ColonizeError as e:
        assert "terraform" in str(e).lower()
