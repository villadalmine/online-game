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


async def test_agent_stashes_in_vault(session, monkeypatch):
    """SDD 83 v2: la acción `stash` guarda minerales en la bóveda (a salvo del saqueo)."""
    from app.models import BunkerRoom, PlayerTech
    from app.services.bunkers import _vault_stocks, dig
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    monkeypatch.setattr(s, "bunkers_enabled", True)
    p, base = await _player(session, name="agent_stash")
    session.add(PlayerTech(player_id=p.id, tech_key="bunker_engineering"))
    await session.flush()
    bunker = await dig(session, p, base.id)
    session.add(BunkerRoom(bunker_id=bunker.id, room_key="vault", cell=0, status="active"))
    (await get_or_create_stock(session, p.id, "iron", "mars")).amount = 5000
    await session.commit()
    monkeypatch.setattr("app.services.llm.llm_chat", _replier(
        f'{{"action":"stash","base_id":{base.id},"mineral":"iron","amount":800}}',
        '{"action":"done"}'))
    assert await ai_agent.run_agent_autopilot(session, p, s) == 1
    await session.commit()
    vault = await _vault_stocks(session, bunker.id)
    assert vault and vault[0].mineral_key == "iron" and vault[0].amount == 800
    assert (await planet_stocks(session, p.id, "mars")).get("iron") == 4200


async def test_agent_spies_a_rival(session, monkeypatch):
    """SDD 83 v2: la acción `spy` lanza un satélite espía (el estado expone enemy_bases)."""
    from app.models import SatelliteMission
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    monkeypatch.setattr(s, "satellites_enabled", True)
    p, _ = await _player(session, name="agent_spy")
    foe, _ = await _player(session, name="agent_spy_foe")
    foe.galaxy_instance_id = p.galaxy_instance_id
    session.add(UnitStock(player_id=p.id, unit_key="spy_satellite", quantity=1))
    await session.commit()
    st = await ai_agent._agent_state(session, p)
    assert any(e["owner"] == "agent_spy_foe" for e in st.get("enemy_bases", []))
    monkeypatch.setattr("app.services.llm.llm_chat", _replier(
        f'{{"action":"spy","target_player_id":{foe.id}}}', '{"action":"done"}'))
    assert await ai_agent.run_agent_autopilot(session, p, s) == 1
    m = (await session.execute(select(SatelliteMission).where(
        SatelliteMission.owner_id == p.id))).scalars().all()
    assert m and m[0].target_id == foe.id


async def test_agent_fortifies_undefended_bases(session, monkeypatch):
    """SDD 83 v2: la acción `fortify` arma la cadena de defensa (research_lab + torreta)."""
    from app.content.registry import get_content
    from app.models import Building
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    p, base = await _player(session, name="agent_fort")
    from app.models import PlayerTech
    session.add(PlayerTech(player_id=p.id, tech_key="weapons"))
    for mk in get_content().minerals:
        (await get_or_create_stock(session, p.id, mk, "mars")).amount = 100000
    await session.commit()
    monkeypatch.setattr("app.services.llm.llm_chat", _replier(
        '{"action":"fortify"}', '{"action":"done"}'))
    assert await ai_agent.run_agent_autopilot(session, p, s) == 1
    await session.commit()
    turrets = (await session.execute(select(Building).where(
        Building.base_id == base.id, Building.building_key == "turret"))).scalars().all()
    assert turrets


async def test_agent_unknown_bunker_op_is_error(session, monkeypatch):
    # op inválido de búnker → error devuelto al LLM, 0 aplicadas, sin romper (fallback determinista)
    s = get_settings()
    monkeypatch.setattr(s, "ai_agent_enabled", True)
    monkeypatch.setattr(s, "bunkers_enabled", True)
    p, base = await _player(session, name="agent_badop")
    monkeypatch.setattr("app.services.llm.llm_chat", _replier(
        f'{{"action":"bunker","base_id":{base.id},"op":"nuke"}}', '{"action":"done"}'))
    assert await ai_agent.run_agent_autopilot(session, p, s) == 0
