"""SDD 69 Fase 4 — vida artificial: subir de nivel (evolve_ai) + autopiloto de auto-staffing."""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Base_, Building, Bunker, Player, PlayerTech, TrainingOrder
from app.services.ai_life import AiLifeError, evolve_ai, run_ai_autopilot
from app.services.economy import get_or_create_stock
from app.services.onboarding import onboard_player


async def _player(session, name="ai_dev"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    p.energy = 100000
    await session.commit()
    return p, base


async def test_evolve_ai_needs_flag_tech_electronics_then_levels_up(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "artificial_life_enabled", True)
    monkeypatch.setattr(s, "bunkers_enabled", True)
    p, base = await _player(session)
    # sin tech → falla
    try:
        await evolve_ai(session, p)
        raise AssertionError("sin la tech no evoluciona")
    except AiLifeError:
        pass
    session.add(PlayerTech(player_id=p.id, tech_key="artificial_life"))
    # búnker con electrónica + minerales avanzados del natal
    b = Bunker(player_id=p.id, base_id=base.id, food_health=100, water_health=100,
               people_health=100, electronics=1000)
    session.add(b)
    from app.content.registry import get_content
    adv = get_content().resolve_role("martian", "advanced")
    (await get_or_create_stock(session, p.id, adv, "mars")).amount = 100000
    await session.commit()
    r = await evolve_ai(session, p)
    await session.commit()
    assert r["level"] == 1 and "workers" in r["scope"]
    assert p.ai_level == 1
    # se cobró la electrónica (nivel 1 cuesta 200)
    b = (await session.execute(select(Bunker).where(Bunker.id == b.id))).scalar_one()
    assert b.electronics == 800


async def test_autopilot_staffs_mines_with_workers(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    p, base = await _player(session)
    p.ai_level = 1   # nivel con scope [workers]
    # mina activa con worker_slots pero sin obreros → deficit → el autopiloto entrena obreros
    struct = None
    from app.content.registry import get_content
    struct = get_content().resolve_role("martian", "structural")
    session.add(Building(base_id=base.id, building_key="mine", status="active",
                         production_mineral=struct))
    await session.commit()
    n = await run_ai_autopilot(session, p)
    await session.commit()
    assert n > 0
    orders = (await session.execute(
        select(TrainingOrder).join(Base_, TrainingOrder.base_id == Base_.id).where(
            Base_.player_id == p.id, TrainingOrder.unit_key == "worker")
    )).scalars().all()
    assert sum(o.quantity for o in orders) == n


async def test_autopilot_off_without_flag(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", False)
    p, base = await _player(session)
    p.ai_level = 5
    await session.commit()
    assert await run_ai_autopilot(session, p) == 0
