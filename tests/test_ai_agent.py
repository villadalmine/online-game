"""SDD 83 — autopiloto AGENTE: el LLM ejecuta acciones (loop de acción-JSON). Verificamos que una
acción `transport` mueve minerales de verdad, que el flag lo gatea, y que un action malo no rompe
(devuelve lo hecho → fallback al determinista)."""
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import Player, TransportMission, UnitStock
from app.services import ai_agent
from app.services.economy import get_or_create_stock, planet_stocks
from app.services.onboarding import onboard_player


async def _player(session, name="agent_dev"):
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    base = await onboard_player(session, p, "milky_way", "mars", "martian")
    p.energy = 100000
    await session.commit()
    return p, base


def _replier(*replies):
    it = iter(replies)

    async def fake_chat(messages, **kw):
        try:
            return next(it)
        except StopIteration:
            return '{"action":"done"}'
    return fake_chat


async def test_agent_executes_transport(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    p, base = await _player(session)
    # una nave de carga + iron en Marte para mandar a Venus
    session.add(UnitStock(player_id=p.id, unit_key="cargo_ship", quantity=1))
    (await get_or_create_stock(session, p.id, "iron", "mars")).amount = 5000
    await session.commit()
    monkeypatch.setattr("app.services.llm.llm_chat", _replier(
        '{"action":"transport","from_planet":"mars","to_planet":"venus","mineral":"iron","amount":500}',
        '{"action":"done"}'))
    n = await ai_agent.run_agent_autopilot(session, p, s)
    await session.commit()
    assert n == 1                                   # ejecutó UNA acción
    miss = (await session.execute(select(TransportMission).where(
        TransportMission.player_id == p.id))).scalars().all()
    assert miss and "iron" in miss[0].cargo         # despachó el convoy con iron
    here = await planet_stocks(session, p.id, "mars")
    assert here.get("iron", 0) == 4500              # el iron salió del origen


async def test_agent_state_includes_active_events(session):
    """SDD 86: el agente ve los eventos del mundo activos (para aprovecharlos)."""
    from app.services.events import start_event
    p, _ = await _player(session, name="agent_ev")
    await start_event(session, "happy_hour_build")   # rebaja de construcción activa
    await session.commit()
    st = await ai_agent._agent_state(session, p)
    assert any(e["effect"] == "build_cost" for e in st["active_events"])


async def test_agent_disabled_is_noop(session, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", False)
    p, _ = await _player(session, name="agent_off")

    async def boom(*a, **k):
        raise AssertionError("no debería llamar al LLM con el flag apagado")
    monkeypatch.setattr("app.services.llm.llm_chat", boom)
    assert await ai_agent.run_agent_autopilot(session, p, s) == 0


async def test_agent_bad_action_does_not_crash(session, monkeypatch):
    # un action inválido → error devuelto al LLM; sin acciones aplicadas, sin romper la sesión.
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    p, _ = await _player(session, name="agent_bad")
    monkeypatch.setattr("app.services.llm.llm_chat", _replier(
        '{"action":"transport","from_planet":"mars","to_planet":"mars","mineral":"iron","amount":9}',
        '{"action":"done"}'))
    assert await ai_agent.run_agent_autopilot(session, p, s) == 0   # mismo planeta → falla


async def test_autopilot_agent_mode_falls_back_to_deterministic(session, monkeypatch):
    # SDD 83: en modo 'agent', si el agente no hizo nada, run_ai_autopilot cae al determinista.
    from app.services import ai_life
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    monkeypatch.setattr(s, "bunker_autonomy_enabled", True)
    monkeypatch.setattr(s, "ai_brain_min_level", 1)
    p, _ = await _player(session, name="agent_fb")
    p.ai_level = 1
    p.ai_brain_mode = "agent"
    await session.commit()

    async def agent_noop(session, player, settings):
        return 0                                    # el agente no hizo nada
    monkeypatch.setattr("app.services.ai_agent.run_agent_autopilot", agent_noop)
    called = {}

    async def det_workers(session, player, settings, q=0.5):
        called["det"] = True
        return 1
    monkeypatch.setattr(ai_life, "_auto_workers", det_workers)
    n = await ai_life.run_ai_autopilot(session, p)
    assert n == 1 and called.get("det")             # cayó al autopiloto determinista
