"""SDD 12 — métricas de por vida + perfil público: tests de servicio."""
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Player, PlayerStats
from app.services import stats as svc
from app.services.economy import get_or_create_stock
from app.services.onboarding import onboard_player


async def _human(session, name) -> Player:
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "earth", "terran")
    await session.commit()
    return p


async def test_bump_accumulates_counters(session):
    p = await _human(session, "counter")
    await svc.bump(session, p.id, battles_won=1, units_trained=3)
    await svc.bump(session, p.id, battles_won=2, resources_mined=10.5)
    await session.commit()
    st = await session.get(PlayerStats, p.id)
    assert st.battles_won == 3 and st.units_trained == 3 and st.resources_mined == 10.5


async def test_collect_mines_bumps_resources_mined(session):
    from datetime import UTC, datetime, timedelta

    from app.models import Building
    from app.services.economy import collect_mines

    p = await _human(session, "miner")
    base = (
        await session.execute(
            select(Building).where(Building.building_key == "headquarters")
        )
    ).scalars().first()
    # una mina activa de hierro que ya produjo un rato
    session.add(Building(
        base_id=base.base_id, building_key="mine", status="active",
        production_mineral="iron",
        completes_at=datetime.now(UTC) - timedelta(hours=2),
        last_collected_at=datetime.now(UTC) - timedelta(hours=2),
    ))
    await session.commit()
    await collect_mines(session, p)
    await session.commit()
    st = await session.get(PlayerStats, p.id)
    assert st is not None and st.resources_mined > 0


async def test_leaderboard_orders_humans_by_score(session):
    await _human(session, "lb_a")
    b = await _human(session, "lb_b")
    (await get_or_create_stock(session, b.id, "iron", b.planet_key)).amount += 500_000
    await session.commit()
    lb = await svc.leaderboard(session, 10)
    names = [p.username for _r, p, _s in lb]
    assert names.index("lb_b") < names.index("lb_a")  # lb_b tiene más score
    assert lb[0][0] == 1


async def test_profile_has_stats_and_no_secrets(session):
    p = await _human(session, "profiled")
    p.email = "secret@b.com"
    await svc.bump(session, p.id, battles_won=5)
    await session.commit()
    prof = await svc.player_profile(session, "profiled")
    assert prof["username"] == "profiled" and prof["stats"]["battles_won"] == 5
    assert "email" not in prof  # nunca exponer email
    assert await svc.player_profile(session, "ghost") is None  # inexistente


async def test_global_stats_counts_players(session):
    await _human(session, "g_one")
    await _human(session, "g_two")
    g = await svc.global_stats(session)
    assert g["players"] >= 2 and g["empires"] >= 2 and "season" in g
