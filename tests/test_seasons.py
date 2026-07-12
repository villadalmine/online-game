"""SDD 11 — temporadas + Hall of Fame + newbie protection: tests de servicio."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.models import Base_, Player, Season
from app.services import seasons as svc
from app.services.combat import CombatError, start_attack
from app.services.economy import get_or_create_stock
from app.services.npc import ensure_npcs
from app.services.onboarding import onboard_player
from app.services.training import get_or_create_unit_stock


async def _human(session, name, planet="mars", race="martian") -> Player:
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _base_of(session, player) -> Base_:
    return (
        await session.execute(select(Base_).where(Base_.player_id == player.id))
    ).scalars().first()


# ---- temporadas -------------------------------------------------------------
async def test_ensure_active_season_creates_and_idempotent(session):
    s1 = await svc.ensure_active_season(session)
    await session.commit()
    assert s1.seq == 1 and s1.status == "active"
    s2 = await svc.ensure_active_season(session)
    assert s2.id == s1.id  # no crea otra si ya hay activa


async def test_close_current_snapshots_hof_and_opens_next(session):
    await svc.ensure_active_season(session)
    await _human(session, "weak")
    strong = await _human(session, "strong")
    # subí el score del fuerte sin tocar nada más
    (await get_or_create_stock(session, strong.id, "iron", strong.planet_key)).amount += 1_000_000
    await session.commit()

    closed = await svc.close_current_now(session)
    await session.commit()
    assert closed == 1

    # Hall of Fame: el fuerte quedó #1
    hof = await svc.hall_of_fame(session)
    assert hof and hof[0].rank == 1 and hof[0].username == "strong"
    assert {h.username for h in hof} >= {"weak", "strong"}

    # se abrió la temporada siguiente y el imperio NO se borró
    active = await svc.current_season(session)
    assert active.seq == 2 and active.status == "active"
    assert await _base_of(session, strong) is not None
    closed_seasons = (
        await session.execute(select(Season).where(Season.status == "closed"))
    ).scalars().all()
    assert len(closed_seasons) == 1


async def test_season_ranking_orders_by_score(session):
    await svc.ensure_active_season(session)
    await _human(session, "a")
    b = await _human(session, "b")
    (await get_or_create_stock(session, b.id, "iron", b.planet_key)).amount += 500_000
    await session.commit()
    ranking = await svc.season_ranking(session, 10)
    names = [p.username for _r, p, _s in ranking]
    assert names.index("b") < names.index("a")  # b va antes (más score)
    assert ranking[0][0] == 1  # rank empieza en 1


# ---- newbie protection ------------------------------------------------------
async def test_onboarding_sets_newbie_protection(session):
    p = await _human(session, "newbie")
    assert p.protected_until is not None and svc._aware(p.protected_until) > datetime.now(UTC)


async def test_cannot_attack_protected_player(session):
    attacker = await _human(session, "atk")
    victim = await _human(session, "vic")
    (await get_or_create_unit_stock(session, attacker.id, "tank")).quantity = 5
    attacker.energy = 999
    await session.commit()

    vbase = await _base_of(session, victim)
    try:
        await start_attack(session, attacker, vbase.id, {"tank": 1})
        raise AssertionError("debería bloquear: víctima protegida")
    except CombatError as e:
        assert "protec" in str(e).lower()


async def test_attacking_human_ends_own_protection(session):
    attacker = await _human(session, "atk2")
    victim = await _human(session, "vic2")
    victim.protected_until = datetime.now(UTC) - timedelta(hours=1)  # ya sin protección
    (await get_or_create_unit_stock(session, attacker.id, "tank")).quantity = 5
    attacker.energy = 999
    await session.commit()

    vbase = await _base_of(session, victim)
    await start_attack(session, attacker, vbase.id, {"tank": 1})
    await session.commit()
    attacker = await session.get(Player, attacker.id)
    assert attacker.protected_until is None  # opt-out al atacar a un humano


async def test_attacking_npc_keeps_protection(session):
    await ensure_npcs(session)
    attacker = await _human(session, "atk3")
    (await get_or_create_unit_stock(session, attacker.id, "tank")).quantity = 5
    attacker.energy = 999
    await session.commit()

    npc = (
        await session.execute(select(Player).where(Player.is_npc.is_(True)))
    ).scalars().first()
    npc_base = await _base_of(session, npc)
    await start_attack(session, attacker, npc_base.id, {"tank": 1})
    await session.commit()
    attacker = await session.get(Player, attacker.id)
    assert attacker.protected_until is not None  # atacar NPC no saca la protección


# ---- season capacity --------------------------------------------------------
async def test_season_capacity_blocks_onboarding(session, monkeypatch):
    from app.core.config import get_settings
    from app.services.onboarding import OnboardingError
    from app.models import Player
    from sqlalchemy import select, func
    
    settings = get_settings()
    current_count = (await session.execute(
        select(func.count(Player.id))
        .where(Player.is_npc.is_(False))
        .where(Player.race_key.is_not(None))
    )).scalar() or 0
    monkeypatch.setattr(settings, "season_capacity", current_count + 2)
    
    # 2 players should be allowed
    await _human(session, "cap1")
    await _human(session, "cap2")
    
    # 3rd player should fail
    try:
        await _human(session, "cap3")
        raise AssertionError("debería bloquear: capacidad máxima alcanzada")
    except OnboardingError as e:
        assert "capacidad máxima" in str(e).lower()
