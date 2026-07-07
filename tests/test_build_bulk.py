"""SDD 82/83b: mejora EN LOTE — mejora SOLO las que podés pagar (para en la que no alcanza), y el
costo/energía se cobra bien pese al fast-path (una sola pasada de economía)."""
from sqlalchemy import select

from app.content.registry import get_content
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Building, Player
from app.services.build import upgrade_buildings_bulk
from app.services.economy import get_or_create_stock, planet_stocks
from app.services.onboarding import onboard_player


async def _player(session, name="bulk_dev"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    p.energy = 1_000_000
    await session.commit()
    return p, base


async def test_bulk_upgrades_only_what_you_can_afford(session):
    s = get_settings()
    content = get_content()
    p, base = await _player(session)
    for _ in range(3):
        session.add(Building(base_id=base.id, building_key="turret", status="active", level=1))
    # costo de UNA mejora de nivel 1 = base_cost × building_upgrade_cost_mult × 1
    cost = content.building_cost_in_minerals("martian", "turret")
    struct = max(cost, key=cost.get)                       # el mineral dominante (structural)
    per = cost[struct] * s.building_upgrade_cost_mult
    (await get_or_create_stock(session, p.id, struct, "mars")).amount = per * 2.2   # alcanza para 2
    await session.commit()
    r = await upgrade_buildings_bulk(session, p, base.id, "turret", "defense")
    await session.commit()
    assert r["total"] == 3 and 0 < r["upgraded"] < 3       # mejoró SOLO las que pudo pagar
    lvls = sorted(b.level for b in (await session.execute(select(Building).where(
        Building.base_id == base.id, Building.building_key == "turret"))).scalars())
    assert lvls.count(2) == r["upgraded"]                  # las pagadas subieron a nivel 2
    left = (await planet_stocks(session, p.id, "mars")).get(struct, 0)
    assert left < per                                      # cobró el material de las mejoradas
