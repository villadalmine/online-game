"""SDD 35 — espionaje: fórmula depth, payload graduado, ciclo de misión + intel persistida."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Base_, IntelReport, Player, SpyMission, UnitStock
from app.services.espionage import (
    graded_payload,
    process_spy_missions,
    resolve_spy,
    start_spy,
)
from app.services.onboarding import onboard_player


async def _player(session, name, *, is_npc=False) -> Player:
    p = Player(username=name, password_hash="x", is_npc=is_npc)
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", "mars", "martian")
    await session.commit()
    return p


async def _give(session, player, unit, qty) -> None:
    session.add(UnitStock(player_id=player.id, unit_key=unit, quantity=qty))
    await session.commit()


async def _base_id(session, player) -> int:
    b = (await session.execute(select(Base_).where(Base_.player_id == player.id))).scalars().first()
    return b.id


def test_resolve_spy_formula():
    assert resolve_spy(100, 0).depth == 1.0           # sin defensa → intel total
    assert resolve_spy(100, 100).depth == 0.5         # parejos → mitad
    assert round(resolve_spy(100, 300).depth, 2) == 0.25   # 3× counter → 0.25
    assert resolve_spy(0, 0).depth == 1.0             # nada vs nada → no rompe


async def test_graded_payload_tiers(session):
    target = await _player(session, "objetivo")
    await _give(session, target, "soldier", 10)
    low = await graded_payload(session, target, 0.1)
    assert set(low.keys()) == {"score"}               # depth muy baja → sólo score
    mid = await graded_payload(session, target, 0.4)
    assert "army_attack" in mid and "units" not in mid  # rangos, sin conteo exacto
    full = await graded_payload(session, target, 0.99)
    assert "units" in full and full["army_attack"] == 80  # exacto (10 soldiers · attack 8)


async def test_spy_cycle_saves_intel_and_returns(session):
    observer = await _player(session, "obs")
    target = await _player(session, "tgt")
    await _give(session, observer, "spy", 5)
    await _give(session, target, "soldier", 4)
    base = await _base_id(session, target)

    m = await start_spy(session, observer, base, {"spy": 5})
    await session.commit()
    # espías salieron del stock
    assert (await session.execute(
        select(UnitStock.quantity)
        .where(UnitStock.player_id == observer.id, UnitStock.unit_key == "spy")
    )).scalar_one() == 0

    # adelantar llegada → resolver (genera intel, sin counter → depth 1.0, sin bajas)
    now = datetime.now(UTC)
    m.arrives_at = now - timedelta(seconds=1)
    await session.commit()
    await process_spy_missions(session, now, observer_id=observer.id)
    report = (await session.execute(
        select(IntelReport).where(IntelReport.observer_id == observer.id)
    )).scalar_one()
    assert report.target_id == target.id and report.depth == 1.0

    # adelantar regreso → vuelven los 5 (no hubo detección)
    m2 = (await session.execute(select(SpyMission).where(SpyMission.id == m.id))).scalar_one()
    m2.returns_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_spy_missions(session, datetime.now(UTC), observer_id=observer.id)
    assert (await session.execute(
        select(UnitStock.quantity)
        .where(UnitStock.player_id == observer.id, UnitStock.unit_key == "spy")
    )).scalar_one() == 5


async def test_counter_intel_lowers_depth_and_detects(session):
    observer = await _player(session, "obs2")
    target = await _player(session, "tgt2")
    await _give(session, observer, "spy", 2)        # spy_power = 2·10 = 20
    await _give(session, target, "spy", 10)         # counter_power = 10·10 = 100 → detect_prob alto
    base = await _base_id(session, target)
    m = await start_spy(session, observer, base, {"spy": 2})
    m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_spy_missions(session, datetime.now(UTC), observer_id=observer.id)
    report = (await session.execute(
        select(IntelReport).where(IntelReport.observer_id == observer.id)
    )).scalar_one()
    assert report.depth < 0.25      # 20/(20+100) ≈ 0.17 → ofuscado
    import json
    assert json.loads(m.details)["detected"] is True   # counter > spy → detectado
