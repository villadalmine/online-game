"""SDD 35 — espionaje: fórmula depth, payload graduado, ciclo de misión + intel persistida."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Base_, IntelReport, Player, PlayerTech, SpyMission, UnitStock
from app.services.alliances import create_alliance, join_alliance
from app.services.espionage import (
    graded_payload,
    player_intel,
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
    # SDD 35: el que espía recibe una notificación de "qué pasó" (intel lista)
    from app.models import Notification
    notis = (await session.execute(
        select(Notification).where(Notification.player_id == observer.id,
                                   Notification.type == "intel_ready")
    )).scalars().all()
    assert notis

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


async def test_espionage_techs_apply_as_multiplier(session):
    """Las techs espionage/counter_espionage entran por el mismo effects.multiplier que usa
    process_spy_missions (espionage sube spy_power; counter_espionage sube counter)."""
    from app.services.effects import multiplier
    p = await _player(session, "techer")
    assert await multiplier(session, p.id, "espionage") == 1.0
    assert await multiplier(session, p.id, "counter_espionage") == 1.0
    session.add(PlayerTech(player_id=p.id, tech_key="espionage"))
    session.add(PlayerTech(player_id=p.id, tech_key="counter_espionage"))
    await session.commit()
    assert round(await multiplier(session, p.id, "espionage"), 2) == 1.40
    assert round(await multiplier(session, p.id, "counter_espionage"), 2) == 1.40


async def test_shared_vision_pools_ally_intel(session):
    """Una alianza con shared_vision comparte la red de espionaje: B ve la intel que consiguió A
    (marcada shared), y A la ve como propia."""
    a = await _player(session, "ally_a")
    b = await _player(session, "ally_b")
    rival = await _player(session, "rival")
    al = await create_alliance(session, a, "Defensores", "DEF", "defensive")  # tiene shared_vision
    await join_alliance(session, b, al.id)
    await session.commit()

    await _give(session, a, "spy", 5)
    base = await _base_id(session, rival)
    m = await start_spy(session, a, base, {"spy": 5})
    m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_spy_missions(session, datetime.now(UTC), observer_id=a.id)

    b_intel = [i for i in await player_intel(session, b) if i["target_id"] == rival.id]
    assert b_intel and b_intel[0]["shared"] is True and b_intel[0]["via"] == "ally_a"
    a_intel = [i for i in await player_intel(session, a) if i["target_id"] == rival.id]
    assert a_intel and a_intel[0]["shared"] is False


async def test_no_shared_vision_keeps_intel_private(session):
    """Sin shared_vision (nonaggression), B NO ve la intel de A."""
    a = await _player(session, "solo_a")
    b = await _player(session, "solo_b")
    rival = await _player(session, "rival2")
    al = await create_alliance(session, a, "Sueltos", "SUE", "nonaggression")  # sin shared_vision
    await join_alliance(session, b, al.id)
    await session.commit()

    await _give(session, a, "spy", 5)
    base = await _base_id(session, rival)
    m = await start_spy(session, a, base, {"spy": 5})
    m.arrives_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await process_spy_missions(session, datetime.now(UTC), observer_id=a.id)

    assert not [i for i in await player_intel(session, b) if i["target_id"] == rival.id]
