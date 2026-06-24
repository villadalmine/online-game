"""SDD 29 — inteligencia estratégica de NPCs: scoreboard-aware posture + fallback."""
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.config import Settings
from app.models import Player, ResourceStock
from app.services import npc as npc_mod
from app.services.npc import decide_strategy, npc_scoreboard
from app.services.onboarding import onboard_player


def _settings(**kw) -> Settings:
    base = dict(_env_file=None, npc_strategy_enabled=True, npc_strategy_interval_seconds=1800)
    base.update(kw)
    return Settings(**base)


async def _player(session, name, *, is_npc=False, galaxy="milky_way") -> Player:
    p = Player(username=name, password_hash="x", is_npc=is_npc)
    session.add(p)
    await session.flush()
    await onboard_player(session, p, galaxy, "mars", "martian")
    await session.commit()
    return p


async def _boost(session, player, amount: float) -> None:
    rows = (
        await session.execute(select(ResourceStock).where(ResourceStock.player_id == player.id))
    ).scalars().all()
    rows[0].amount += amount  # sube el score (minerales/50)
    await session.commit()


async def test_npc_scoreboard_galaxy_scoped_with_leader(session, monkeypatch):
    monkeypatch.setattr(npc_mod, "get_settings", _settings)
    npc = await _player(session, "npc_martian", is_npc=True)
    leader = await _player(session, "leader")
    await _player(session, "weak")
    await _boost(session, leader, 500_000)  # +10000 score → líder
    # uno en otra galaxia: debe quedar EXCLUIDO
    other = Player(username="faraway", password_hash="x")
    other.galaxy_key = "andromeda"
    session.add(other)
    await session.commit()

    board = await npc_scoreboard(session, npc)
    names = [b["name"] for b in board]
    assert "leader" in names and "weak" in names
    assert "faraway" not in names and "npc_martian" not in names  # otra galaxia + self fuera
    assert board[0]["name"] == "leader" and board[0]["is_leader"] is True
    assert all(b["is_human"] for b in board)


async def test_decide_strategy_sets_posture_and_target(session, monkeypatch):
    monkeypatch.setattr(npc_mod, "get_settings", _settings)
    npc = await _player(session, "npc_martian", is_npc=True)
    leader = await _player(session, "leader")
    await _boost(session, leader, 500_000)

    captured = {}

    async def fake_strategist(state):
        captured["board"] = state["scoreboard"]
        return {"posture": "aggressive", "target": "leader", "why": "el lider me supera"}

    posture = await decide_strategy(session, npc, strategize=fake_strategist)
    assert posture == "aggressive"
    fresh = await session.get(Player, npc.id)
    assert fresh.npc_posture == "aggressive"
    assert fresh.npc_target_id == leader.id
    assert fresh.npc_strategy_updated_at is not None
    assert "leader" in fresh.npc_strategy  # snapshot de scores guardado


async def test_invalid_posture_is_ignored(session, monkeypatch):
    monkeypatch.setattr(npc_mod, "get_settings", _settings)
    npc = await _player(session, "npc_martian", is_npc=True)

    async def bad(state):
        return {"posture": "destruir-todo"}  # no está en POSTURES

    posture = await decide_strategy(session, npc, strategize=bad)
    assert posture == "opportunist"  # mantiene el default


async def test_no_llm_keeps_previous_posture(session, monkeypatch):
    # sin llm_key, la estrategia LLM no corre → mantiene la postura previa (no rompe el tick)
    monkeypatch.setattr(npc_mod, "get_settings", lambda: _settings(llm_api_key=""))
    npc = await _player(session, "npc_martian", is_npc=True)
    posture = await decide_strategy(session, npc)  # strategize por defecto = _llm_strategy
    assert posture == "opportunist"
    fresh = await session.get(Player, npc.id)
    assert fresh.npc_strategy_updated_at is None  # no recalculó


async def test_cadence_skips_when_not_due(session, monkeypatch):
    monkeypatch.setattr(npc_mod, "get_settings", _settings)
    npc = await _player(session, "npc_martian", is_npc=True)
    npc.npc_posture = "defensive"
    npc.npc_strategy_updated_at = datetime.now(UTC)  # recién actualizado → NO toca
    await session.commit()

    called = {"n": 0}

    async def fake(state):
        called["n"] += 1
        return {"posture": "aggressive"}

    posture = await decide_strategy(session, npc, strategize=fake)
    assert posture == "defensive" and called["n"] == 0  # no recalculó por cadencia
