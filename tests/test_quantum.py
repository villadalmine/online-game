"""SDD 87 — bomba cuántica: infecta+drena, penaliza progresivo, se desactiva (tropas/rescate/tech),
y la desactivación con tech FILTRA info hasta poner un satélite inhibidor."""
from datetime import UTC, datetime, timedelta

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Player, PlayerTech, QuantumInfection, SatelliteMission, UnitStock
from app.services import quantum
from app.services.economy import get_or_create_stock, planet_stocks
from app.services.onboarding import onboard_player


async def _p(session, name, planet="mars", race="martian"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", planet, race)
    p.energy = 10000
    await session.commit()
    return p, base


async def test_bomb_impact_infects_and_drains(session, monkeypatch):
    monkeypatch.setattr(get_settings(), "quantum_bomb_enabled", True)
    atk, _ = await _p(session, "q_atk", "earth", "terran")
    dfn, dbase = await _p(session, "q_def", "mars", "martian")
    (await get_or_create_stock(session, dfn.id, "iron", "mars")).amount = 1000
    await session.commit()
    r = await quantum.on_bomb_impact(session, atk, dfn, dbase.id, datetime.now(UTC))
    await session.commit()
    inf = await quantum.active_infection(session, dfn.id)
    assert inf is not None and inf.base_id == dbase.id
    assert r["stolen"].get("iron", 0) > 0
    assert (await planet_stocks(session, dfn.id, "mars")).get("iron", 0) < 1000   # drenó
    assert (await planet_stocks(session, atk.id, "earth")).get("iron", 0) > 0     # el atacante robó


async def test_infection_penalty_grows_with_time(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "quantum_bomb_enabled", True)
    monkeypatch.setattr(s, "quantum_decay_days", 7.0)
    monkeypatch.setattr(s, "quantum_max_penalty", 0.8)
    dfn, dbase = await _p(session, "q_def2")
    session.add(QuantumInfection(defender_id=dfn.id, attacker_id=dfn.id, base_id=dbase.id,
                                 status="active", created_at=datetime.now(UTC) - timedelta(days=7)))
    await session.commit()
    pen = await quantum.infection_penalty(session, dfn.id)
    assert 0.19 <= pen <= 0.21   # a los 7 días, tope 80% → factor 0.2


async def test_disarm_with_troops(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "quantum_bomb_enabled", True)
    monkeypatch.setattr(s, "quantum_disarm_soldiers", 5)
    atk, _ = await _p(session, "q_a3", "earth", "terran")
    dfn, dbase = await _p(session, "q_d3")
    session.add(QuantumInfection(defender_id=dfn.id, attacker_id=atk.id, base_id=dbase.id,
                                 status="active"))
    session.add(UnitStock(player_id=dfn.id, unit_key="soldier", quantity=10))
    await session.commit()
    r = await quantum.disarm_with_troops(session, dfn, dbase.id)
    await session.commit()
    assert r["disarmed"] == "troops"
    assert await quantum.active_infection(session, dfn.id) is None


async def test_disarm_with_ransom_pays_attacker(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "quantum_bomb_enabled", True)
    monkeypatch.setattr(s, "quantum_ransom_fraction", 0.5)
    atk, _ = await _p(session, "q_a5", "earth", "terran")
    dfn, dbase = await _p(session, "q_d5")
    (await get_or_create_stock(session, dfn.id, "iron", "mars")).amount = 1000
    session.add(QuantumInfection(defender_id=dfn.id, attacker_id=atk.id, base_id=dbase.id,
                                 status="active"))
    await session.commit()
    r = await quantum.disarm_with_ransom(session, dfn, dbase.id)
    await session.commit()
    assert r["disarmed"] == "ransom" and r["paid"].get("iron", 0) > 0
    assert (await planet_stocks(session, atk.id, "earth")).get("iron", 0) > 0
    assert await quantum.active_infection(session, dfn.id) is None


async def test_disarm_quantum_leaks_until_inhibitor(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "quantum_bomb_enabled", True)
    monkeypatch.setattr(s, "satellites_enabled", True)
    atk, _ = await _p(session, "q_a4", "earth", "terran")
    dfn, dbase = await _p(session, "q_d4")
    session.add(PlayerTech(player_id=dfn.id, tech_key="quantum_warfare"))
    session.add(QuantumInfection(defender_id=dfn.id, attacker_id=atk.id, base_id=dbase.id,
                                 status="active"))
    await session.commit()
    r = await quantum.disarm_with_quantum(session, dfn, dbase.id)
    await session.commit()
    assert r["leaking"] is True
    assert dbase.id in await quantum.leaked_base_ids(session, atk.id)   # filtra sin inhibidor
    session.add(SatelliteMission(owner_id=dfn.id, unit_key="inhibitor_satellite",
                                 kind="inhibitor", status="orbiting", energy=100))
    await session.commit()
    assert dbase.id not in await quantum.leaked_base_ids(session, atk.id)   # inhibidor corta
