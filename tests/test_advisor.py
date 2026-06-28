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


async def test_advisor_ask_is_journaled(session, monkeypatch):
    # SDD 40: cada consulta al asistente queda en el journal (métrica por jugador).
    from app.services.journal import list_events
    p = await _player(session, name="asker_j")

    async def fake(*a, **k):
        return "ok"

    monkeypatch.setattr(adv, "llm_chat", fake)
    await adv.ask(session, p, "hola")
    evs = [e for e in await list_events(session, p.id) if e.type == "advisor_ask"]
    assert evs


async def test_ask_sends_bounded_subgraph_not_full_graph(session, monkeypatch):
    # SDD 9: el prompt lleva solo el SUBGRAFO relevante (≤ advisor_graph_k), no el grafo completo.
    import json

    from app.core.config import get_settings
    from app.services import depgraph
    p = await _player(session, name="subgraph")
    full = len(depgraph.graph_documents(p.race_key, p.planet_key))
    cap = get_settings().advisor_graph_k
    captured = {}

    async def fake_chat(messages, **kw):
        ctx = json.loads(messages[-1]["content"].split("CONTEXTO:\n", 1)[1])
        captured["n"] = len(ctx["knowledge"])
        return "ok"

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    await adv.ask(session, p, "quiero una fábrica para tanques")
    assert captured["n"] <= cap < full   # acotado y menor que el grafo completo


async def test_ask_daily_budget_stops_calling_llm(session, monkeypatch):
    # SDD 9 / patrón shooter: pasado el cupo diario NO se llama al LLM (cero créditos) → fallback.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "advisor_llm_calls_per_day", 2)
    p = await _player(session, name="budget")

    calls = {"n": 0}

    async def fake_chat(messages, **kw):
        calls["n"] += 1
        return "respuesta del modelo"

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    await adv.ask(session, p, "hola 1")
    await adv.ask(session, p, "hola 2")
    assert calls["n"] == 2
    r3 = await adv.ask(session, p, "hola 3")   # pasado el cupo → no llama al LLM
    assert calls["n"] == 2                       # no creció
    assert r3.reply                              # igual responde (determinista)


async def test_ask_cloud_mode_uses_paid_alias(session, monkeypatch):
    # SDD 9: modo 'cloud' → manda el alias pago barato (gemma4-paid), no el local.
    from app.core.config import get_settings
    p = await _player(session, name="cloudmode")
    cap = {}

    async def fake_chat(messages, **kw):
        cap.update(kw)
        return "ok nube"

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    await adv.ask(session, p, "qué construyo", mode="cloud")
    assert cap["model"] == get_settings().assistant_cloud_model
    assert cap.get("api_key") is None   # usa la key del server, no BYOK


async def test_ask_byok_uses_player_key_and_skips_budget(session, monkeypatch):
    # SDD 9: modo 'byok' → usa la key/modelo/base_url del jugador y NO consume el cupo del server.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "advisor_llm_calls_per_day", 0)   # cupo agotado
    p = await _player(session, name="byokmode")
    cap = {}

    async def fake_chat(messages, **kw):
        cap.update(kw)
        return "ok byok"

    monkeypatch.setattr(adv, "llm_chat", fake_chat)
    r = await adv.ask(session, p, "hola", mode="byok",
                      byok_key="sk-or-xxx", byok_model="google/gemma-3-27b-it:free")
    assert r.reply == "ok byok"                       # llamó al LLM aunque el cupo estaba en 0
    assert cap["api_key"] == "sk-or-xxx"
    assert cap["model"] == "google/gemma-3-27b-it:free"
    assert cap["base_url"] == get_settings().assistant_byok_base_url


async def test_ask_byok_requires_key_and_model(session):
    from app.services.advisor import AdvisorError
    p = await _player(session, name="byokbad")
    try:
        await adv.ask(session, p, "hola", mode="byok", byok_key="", byok_model="")
        raise AssertionError("byok sin key/modelo debía fallar")
    except AdvisorError as e:
        assert e.status == 400


async def test_assist_energy_proportional_to_deficit_and_daily_cap(session):
    # SDD 40/41: energía proporcional al déficit vs el promedio; el que está sobre el promedio no
    # recibe nada (sin ventaja); tope diario → 429.
    from app.core.config import get_settings
    from app.services.economy import get_or_create_stock
    s = get_settings()
    players = [await _player(session, name=f"rank{i}") for i in range(4)]
    for i, p in enumerate(players):
        (await get_or_create_stock(session, p.id, "iron", p.planet_key)).amount = i * 100000.0
    await session.commit()
    low, high = players[0], players[3]
    low.energy = 0.0
    high.energy = 0.0
    await session.commit()

    r_low = await adv.grant_assist_energy(session, low)
    assert r_low["granted"] > 0 and r_low["deficit"] > 0   # rezagado → recibe, proporcional

    r_high = await adv.grant_assist_energy(session, high)
    assert r_high["granted"] == 0.0 and r_high["deficit"] == 0.0   # sobre el promedio → nada

    # tope diario del rezagado (high no gastó cupo): low ya usó 1; gastar el resto → 429
    for _ in range(s.assist_energy_per_day - 1):
        low.energy = 0.0
        await session.commit()
        await adv.grant_assist_energy(session, low)
    try:
        low.energy = 0.0
        await session.commit()
        await adv.grant_assist_energy(session, low)
        raise AssertionError("debía agotar el cupo diario")
    except adv.AdvisorError as e:
        assert e.status == 429


async def test_hack_also_builds_the_target(session):
    # SDD 2 (mejora): el hack no solo materializa lo que falta — además CONSTRUYE el target en un
    # click (gratis). Pedimos un edificio sin elección de mineral (barracks) sin recursos.
    from app.models import Building
    from app.services.training import get_or_create_unit_stock  # noqa: F401 (asegura módulo)
    p = await _player(session, name="oneclick")
    await _strip_minerals(session, p.id)
    p.energy = 9999
    await session.commit()

    res = await adv.grant_hack(session, p, "barracks")
    assert res["granted"]                                   # materializó lo que faltaba
    assert "construí" in res["message"]
    built = (await session.execute(select(Building).where(
        Building.building_key == "barracks"))).first()
    assert built is not None                                # y lo construyó (queda en cola/activo)


async def test_ask_command_uses_hack_to_build(session):
    # SDD 2 v2: si das la ORDEN "construime barracks", te falta material y tenés hack → lo usa solo.
    from app.models import Building
    p = await _player(session, name="commander")
    await _strip_minerals(session, p.id)
    p.energy = 9999
    await session.commit()

    r = await adv.ask(session, p, "construime barracks")
    assert r.hacks_left == 2                                   # gastó un hack
    assert "barracks" in r.reply.lower()
    built = (await session.execute(select(Building).where(
        Building.building_key == "barracks"))).first()
    assert built is not None                                   # y lo construyó


async def test_ask_question_does_not_spend_hack(session):
    # una PREGUNTA ("¿qué me conviene construir?") NO gasta hack (no es orden de un objetivo único).
    p = await _player(session, name="asker")
    await _strip_minerals(session, p.id)
    p.energy = 9999
    await session.commit()
    r = await adv.ask(session, p, "¿qué me conviene construir?")
    assert r.hacks_left == 3                                   # intacto
