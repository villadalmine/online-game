"""SDD 61: satélites — mapeo del enemigo, inhibidores, flag."""
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Building, Player, SatelliteMission, UnitStock
from app.services.onboarding import onboard_player
from app.services.satellites import SatelliteError, advance_satellites, launch, satellites_state


async def _player(session, name, planet="mars", race="martian"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p, base


async def _give_sat(session, player, unit_key="spy_satellite", qty=1):
    session.add(UnitStock(player_id=player.id, unit_key=unit_key, quantity=qty))
    await session.commit()


async def test_spy_satellite_maps_over_time(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "satellites_enabled", True)
    atk, _ = await _player(session, "sat_atk", planet="mars", race="martian")
    dfn, _ = await _player(session, "sat_def", planet="venus", race="venusian")
    await _give_sat(session, atk)
    sat = await launch(session, atk, "spy_satellite", dfn.id)
    await session.commit()
    assert sat.discovered_pct == 0.0
    # simular 48 h en órbita (1 sat, sin inhibidores → ~50% a las 48 h con R=100/96 %/h)
    past = datetime.now(UTC) - timedelta(hours=48)
    sat.last_tick_at = past
    sat.created_at = past
    await session.commit()
    await advance_satellites(session, atk)
    await session.commit()
    sat = await session.get(SatelliteMission, sat.id)
    assert 40 <= sat.discovered_pct <= 60, sat.discovered_pct
    # el mapa del enemigo aparece en el estado
    _sats, maps = await satellites_state(session, atk)
    assert str(dfn.id) in maps and maps[str(dfn.id)]["pct"] > 0


async def test_inhibitor_caps_discovery(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "satellites_enabled", True)
    atk, _ = await _player(session, "sat_atk2", planet="mars", race="martian")
    dfn, dbase = await _player(session, "sat_def2", planet="venus", race="venusian")
    # muchos inhibidores → coverage alta → techo de descubrimiento bajo
    for _ in range(20):
        session.add(Building(base_id=dbase.id, building_key="signal_inhibitor", status="active"))
    await session.commit()
    await _give_sat(session, atk)
    sat = await launch(session, atk, "spy_satellite", dfn.id)
    long_ago = datetime.now(UTC) - timedelta(hours=500)   # mucho tiempo
    sat.last_tick_at = long_ago
    sat.created_at = long_ago
    await session.commit()
    await advance_satellites(session, atk)
    await session.commit()
    sat = await session.get(SatelliteMission, sat.id)
    # con cobertura de inhibidores, NUNCA llega a 100% (queda topeado)
    assert sat.discovered_pct < 100.0, sat.discovered_pct


async def test_satellites_off_disabled(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "satellites_enabled", False)
    atk, _ = await _player(session, "sat_off", planet="mars", race="martian")
    dfn, _ = await _player(session, "sat_off_def", planet="venus", race="venusian")
    await _give_sat(session, atk)
    try:
        await launch(session, atk, "spy_satellite", dfn.id)
        raise AssertionError("con el flag OFF no se lanzan satélites")
    except SatelliteError:
        pass
