"""SDD 49 — pruebas puras de la intercepción de misiles (simulate_strike, sin DB)."""
from app.services.strike import simulate_strike


def test_swarm_of_sonics_saturates_interception():
    # capacidad 6 frena 3 sónicos (intercept_cost 2 c/u); los 2 que sobran impactan → daño 2×60.
    r = simulate_strike({"sonic_missile": 5}, intercept_capacity=6)
    assert sum(r.intercepted.values()) == 3
    assert r.impacted == {"sonic_missile": 2}
    assert r.damage == 120


def test_nuclear_is_nearly_unstoppable():
    # un nuclear cuesta 30 de capacidad: con capacidad 20 (2 torretas) no se frena → impacta + área.
    r = simulate_strike({"nuclear_missile": 1}, intercept_capacity=20)
    assert r.intercepted == {}
    assert r.impacted == {"nuclear_missile": 1}
    assert r.damage == 600 and r.area is True


def test_cheap_missiles_are_intercepted_first():
    # la capacidad se gasta primero en los baratos (sónico cost 2), luego el crucero (cost 6).
    r = simulate_strike({"sonic_missile": 2, "cruise_missile": 1}, intercept_capacity=4)
    assert r.intercepted == {"sonic_missile": 2}      # los 2 baratos (2+2=4)
    assert r.impacted == {"cruise_missile": 1}        # el caro pasa
    assert r.damage == 160


def test_no_interception_all_impact_with_attack_mult():
    r = simulate_strike({"sonic_missile": 2}, intercept_capacity=0, atk_mult=2.0)
    assert r.impacted == {"sonic_missile": 2}
    assert r.damage == 240   # 2×60×2.0


def test_full_interception_no_damage():
    r = simulate_strike({"sonic_missile": 3}, intercept_capacity=20)
    assert r.impacted == {} and r.damage == 0.0


# ---- SDD 67: diplomacia nuclear (tributo) ----
from datetime import UTC, datetime  # noqa: E402

import pytest  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.models import Building, Player, PlayerTech  # noqa: E402
from app.services.economy import get_or_create_stock, player_stocks  # noqa: E402
from app.services.onboarding import onboard_player  # noqa: E402
from app.services.strike import (  # noqa: E402
    StrikeError,
    accept_tribute,
    offer_tribute,
    start_strike,
)


async def _p(session, name, planet, race):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", planet, race)
    p.energy = 100000
    await session.commit()
    return p, base


async def test_nuclear_travels_24h_and_tribute_cancels(session):
    atk, abase = await _p(session, "nuker", "mars", "martian")
    dfn, dbase = await _p(session, "nuked", "mars", "martian")
    dfn.protected_until = None
    # atacante: lanzadera + tech + un nuclear en stock
    from app.models import UnitStock
    session.add(Building(base_id=abase.id, building_key="launcher", status="active"))
    for t in ("rocketry", "ballistics", "nuclear_fission"):
        session.add(PlayerTech(player_id=atk.id, tech_key=t))
    session.add(UnitStock(player_id=atk.id, unit_key="nuclear_missile", quantity=1))
    # defensor: gobierno activo + diplomacia + recursos para el tributo
    session.add(Building(base_id=dbase.id, building_key="government", status="active"))
    session.add(PlayerTech(player_id=dfn.id, tech_key="diplomacy"))
    (await get_or_create_stock(session, dfn.id, "iron", dfn.planet_key)).amount = 5000
    await session.commit()

    m = await start_strike(session, atk, abase.id, dbase.id, {"nuclear_missile": 1})
    await session.commit()
    # viaja 24 h (ventana de negociación)
    assert (m.arrives_at.replace(tzinfo=UTC) - datetime.now(UTC)).total_seconds() > 80000

    await offer_tribute(session, dfn, m.id, {"iron": 1000}, 0)
    await session.commit()
    res = await accept_tribute(session, atk, m.id)
    await session.commit()
    from app.models import StrikeMission
    m = await session.get(StrikeMission, m.id)
    assert res["cancelled"] and m.status == "cancelled"
    # el mineral se transfirió al atacante
    assert (await player_stocks(session, atk.id)).get("iron", 0) >= 1000


async def test_tribute_requires_government_and_diplomacy(session):
    from app.models import UnitStock
    atk, abase = await _p(session, "nuker2", "mars", "martian")
    dfn, dbase = await _p(session, "nuked2", "mars", "martian")
    dfn.protected_until = None
    session.add(Building(base_id=abase.id, building_key="launcher", status="active"))
    for t in ("rocketry", "ballistics", "nuclear_fission"):
        session.add(PlayerTech(player_id=atk.id, tech_key=t))
    session.add(UnitStock(player_id=atk.id, unit_key="nuclear_missile", quantity=1))
    await session.commit()
    m = await start_strike(session, atk, abase.id, dbase.id, {"nuclear_missile": 1})
    await session.commit()
    with pytest.raises(StrikeError):   # sin gobierno/diplomacia no puede ofrecer
        await offer_tribute(session, dfn, m.id, {"iron": 10}, 0)
