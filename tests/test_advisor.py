"""SDD 2 — personal AI assistant: service tests (LLM stubbed; deterministic core)."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.security import hash_password
from app.models import Player, ResourceStock
from app.services import advisor as adv
from app.services.onboarding import onboard_player


async def _player(session, name="advisee", planet="mars", race="martian") -> Player:
    p = Player(username=name, password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _strip_minerals(session, player_id) -> None:
    for st in (
        await session.execute(select(ResourceStock).where(ResourceStock.player_id == player_id))
    ).scalars():
        st.amount = 0.0


async def test_ask_uses_llm_and_returns_blockers_and_suggestions(session, monkeypatch):
    p = await _player(session)
    await _strip_minerals(session, p.id)
    await session.commit()

    async def fake_chat(messages, **kw):
        # the assistant must ground the model on retrieved docs + blockers
        ctx = messages[-1]["content"]
        assert "blockers" in ctx and "knowledge" in ctx
        return "Te falta hierro: construí una mina."

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    reply = await adv.ask(session, p, "quiero una fábrica para tanques")
    assert "mina" in reply.reply.lower()
    assert reply.blockers and any(
        b.kind in ("mineral", "not_producible") for r in reply.blockers for b in r.blockers
    )
    assert reply.suggestions  # at least a "build mine of X" suggestion
    assert reply.hacks_left == 3 and reply.hack_available is True


async def test_ask_named_mineral_suggests_that_mine(session, monkeypatch):
    # "quiero una mina de silicio" must suggest a SILICON mine (right mineral), not a generic
    # one that inherits whatever the UI dropdown had selected.
    p = await _player(session)  # martian on mars; silicon is locally minable on mars

    async def fake_chat(messages, **kw):
        return "Construí una mina de silicio."

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    reply = await adv.ask(session, p, "quiero una mina de silicio")
    mine_sugs = [
        s for s in reply.suggestions
        if s.action == "build" and s.params.get("building") == "mine"
    ]
    assert any(s.params.get("mineral") == "silicon" for s in mine_sugs)


async def test_ask_falls_back_without_llm(session, monkeypatch):
    p = await _player(session, name="nollm")
    await _strip_minerals(session, p.id)
    await session.commit()

    async def boom(messages, **kw):
        raise RuntimeError("no LLM configured")

    monkeypatch.setattr(adv, "llm_chat", boom)
    reply = await adv.ask(session, p, "qué construyo")
    assert reply.reply  # deterministic fallback text
    assert "falta" in reply.reply.lower() or "traba" in reply.reply.lower()
    assert reply.suggestions


async def test_hack_grants_minimal_shortfall(session):
    p = await _player(session, name="hacker")
    await _strip_minerals(session, p.id)
    p.energy = 9999
    await session.commit()

    res = await adv.grant_hack(session, p, "mine")  # martian mine = iron 100, sulfur 40
    assert res["granted"]["iron"] == 100 and res["granted"]["sulfur"] == 40
    assert res["hacks_left"] == 2

    # now it's buildable -> hacking again is rejected (nothing missing)
    p = await session.get(Player, p.id)
    try:
        await adv.grant_hack(session, p, "mine")
        raise AssertionError("debería rechazar: ya no falta nada")
    except adv.AdvisorError as e:
        assert e.status == 400


async def test_hack_daily_budget_exhausts_and_resets(session):
    p = await _player(session, name="budget")
    p.energy = 9999

    async def drain_one(target):
        nonlocal p
        await _strip_minerals(session, p.id)
        await session.commit()
        await adv.grant_hack(session, p, target)
        p = await session.get(Player, p.id)

    await drain_one("mine")       # 1
    await drain_one("barracks")   # 2
    await drain_one("research_lab")  # 3
    assert adv.hacks_left(p) == 0

    await _strip_minerals(session, p.id)
    await session.commit()
    try:
        await adv.grant_hack(session, p, "factory")  # 4th today -> 429
        raise AssertionError("el 4º hack del día debería fallar")
    except adv.AdvisorError as e:
        assert e.status == 429

    # cross midnight (lazy reset): yesterday's counter no longer counts
    p = await session.get(Player, p.id)
    p.assistant_hacks_reset_at = datetime.now(UTC) - timedelta(days=1)
    await session.commit()
    assert adv.hacks_left(p) == 3


async def test_ask_mechanics_question_grounds_on_rules(session, monkeypatch):
    # SDD 38/2: una pregunta de MECÁNICA debe responderse con las reglas (grounded), no desviar
    # a "qué construir". La mecánica de combate (sin capacidad de transporte) llega al contexto.
    p = await _player(session)
    captured = {}

    async def fake_chat(messages, **kw):
        captured["ctx"] = messages[-1]["content"]
        return "En un ataque mandás las unidades que quieras; el shuttle es para expediciones."

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    reply = await adv.ask(session, p, "cuántos militares entran en un transbordador espacial?")
    assert "mech_combat" in captured["ctx"]      # la regla de combate fue al grounding
    assert not reply.blockers                     # no se desvía a "qué te falta construir"


async def test_ask_mechanics_fallback_returns_rule(session, monkeypatch):
    # sin LLM, el fallback determinista responde con la regla recuperada (no "vas bien").
    p = await _player(session)

    async def boom(*a, **k):
        raise RuntimeError("no llm")

    monkeypatch.setattr(adv, "llm_chat", boom)
    reply = await adv.ask(session, p, "cómo funciona el combate y la capacidad de las flotas?")
    low = reply.reply.lower()
    assert "combate" in low and ("capacidad" in low or "transbordador" in low)
