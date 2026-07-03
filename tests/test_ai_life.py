"""SDD 69 Fase 4 — vida artificial: subir de nivel (evolve_ai) + autopiloto de auto-staffing."""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Base_, Building, Bunker, Player, PlayerTech, TrainingOrder
from app.services.ai_life import AiLifeError, evolve_ai, run_ai_autopilot
from app.services.economy import get_or_create_stock
from app.services.onboarding import onboard_player


async def _player(session, name="ai_dev", planet="mars", race="martian"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", planet, race)
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


async def test_autopilot_paused_by_switch(session, monkeypatch):
    # SDD 69 F4: botón de parada — con ai_autopilot_on=False el autopiloto no actúa pese al déficit.
    from app.content.registry import get_content
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", True)
    p, base = await _player(session)
    p.ai_level = 1
    p.ai_autopilot_on = False
    struct = get_content().resolve_role("martian", "structural")
    session.add(Building(base_id=base.id, building_key="mine", status="active",
                         production_mineral=struct))
    await session.commit()
    assert await run_ai_autopilot(session, p) == 0   # parado por el jugador


async def test_auto_mines_builds_a_missing_role_mine(session, monkeypatch):
    # SDD 69 F4 sub-fase 2: nivel 2 (scope mines) → levanta una mina de un mineral sin minar.
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", True)
    p, base = await _player(session)
    p.ai_level = 2   # scope incluye mines
    for m in ("iron", "sulfur", "magnesium"):   # fondear para poder construir
        (await get_or_create_stock(session, p.id, m, "mars")).amount = 100000
    await session.commit()
    n = await run_ai_autopilot(session, p)
    await session.commit()
    assert n >= 1
    mines = (await session.execute(
        select(Building).where(Building.base_id == base.id, Building.building_key == "mine")
    )).scalars().all()
    assert len(mines) >= 1 and mines[0].production_mineral in ("iron", "sulfur", "magnesium")


async def test_auto_colonize_with_colony_ship(session, monkeypatch):
    # SDD 69 F4 sub-fase 2: nivel 4 (colonize) + colony_ship + techs → coloniza un planeta.
    from app.models import UnitStock
    monkeypatch.setattr(get_settings(), "bunker_autonomy_enabled", True)
    p, base = await _player(session, name="ai_col", planet="earth", race="terran")
    p.ai_level = 4   # scope incluye colonize
    for t in ("antigravity", "thermal_shielding"):   # mars colonizable p/ terran
        session.add(PlayerTech(player_id=p.id, tech_key=t))
    session.add(UnitStock(player_id=p.id, unit_key="colony_ship", quantity=1))
    await session.commit()
    n = await run_ai_autopilot(session, p)
    await session.commit()
    assert n >= 1
    planets = {b.planet_key for b in (await session.execute(
        select(Base_).where(Base_.player_id == p.id))).scalars()}
    assert len(planets) >= 2   # colonizó al menos un planeta nuevo


async def test_auto_attack_hits_a_beatable_enemy(session, monkeypatch):
    # SDD 69 F4 sub-fase 3: nivel 5 (attack) → ataca a un rival que supera claramente.
    from app.models import AttackMission, UnitStock
    s = get_settings()
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    monkeypatch.setattr(s, "garrison_enabled", False)   # usar el ejército global (simple)
    atk, abase = await _player(session, name="ai_atk")
    atk.ai_level = 5
    dfn, dbase = await _player(session, name="ai_vic")
    dfn.protected_until = None                          # sin protección de novato
    session.add(UnitStock(player_id=atk.id, unit_key="soldier", quantity=100))
    await session.commit()
    n = await run_ai_autopilot(session, atk)
    await session.commit()
    assert n >= 1   # el nivel 5 puede hacer varias acciones; nos importa que atacó
    missions = (await session.execute(
        select(AttackMission).where(AttackMission.attacker_id == atk.id))).scalars().all()
    assert missions and missions[0].target_base_id == dbase.id


async def test_npc_effective_epsilon_scales_with_ceiling(monkeypatch):
    # SDD 69 F4: el techo (admin) da más exploración a los NPC. Default 0 → base; sube y se topea.
    from app.services.npc import npc_effective_epsilon
    s = get_settings()
    monkeypatch.setattr(s, "npc_explore_epsilon", 0.2)
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 0)
    assert npc_effective_epsilon() == 0.2
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 2)
    assert abs(npc_effective_epsilon() - 0.36) < 1e-9
    monkeypatch.setattr(s, "artificial_life_npc_ceiling", 100)
    assert npc_effective_epsilon() == 0.6   # topeado
