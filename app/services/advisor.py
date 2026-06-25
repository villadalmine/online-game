"""SDD 2 — Personal AI assistant: advises a player using the dependency graph (SDD 1) as its
skill, the same provider-agnostic LLM as the NPCs (with a deterministic fallback), and an
emergency "hack" that grants the minimal missing materials, capped at N/day.

Truth about feasibility is deterministic (depgraph.analyze); the LLM only writes prose. So a
hallucination can never produce an invalid suggestion or an over-grant. See
docs/sdd-ai-assistant.md.
"""
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import AdvisorMessage, Base_, Building, Player
from app.schemas import AdvisorReply, BlockerReport, Suggestion
from app.services import depgraph
from app.services.economy import get_or_create_stock, player_stocks
from app.services.energy import compute_energy
from app.services.llm import llm_chat
from app.services.notifications import notify
from app.services.physics import effective_energy_regen
from app.services.state import advance

HISTORY_LEN = 10

# Palabras que marcan una pregunta de MECÁNICA (cómo/cuánto/capacidad/funciona…), para
# responder la regla aunque el mensaje nombre una unidad/edificio (SDD 38).
_MECH_WORDS = {
    "como", "cómo", "cuanto", "cuánto", "cuantos", "cuántos", "cuanta", "cuánta", "cuantas",
    "cuántas", "capacidad", "funciona", "funcionan", "sirve", "sirven", "caben", "cabe",
    "entran", "entra", "llevar", "llevo", "transporta", "transporte", "regla", "reglas",
    # ayuda/energía (para que "ayudame con energía" explique el nivelado, SDD 41). NO ponemos
    # "necesito"/"dame" acá: son ambiguos y secuestrarían "necesito una fábrica".
    "ayuda", "ayudame", "ayúdame", "ayudar", "energia", "energía", "nivelar", "nivelado",
}


class AdvisorError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


# --------------------------------------------------------------------------- #
# State snapshot (bridge to the pure SDD-1 analyzer)
# --------------------------------------------------------------------------- #
async def build_snapshot(session: AsyncSession, player: Player) -> depgraph.PlayerSnapshot:
    s = get_settings()
    energy = compute_energy(
        player.energy, player.energy_updated_at, datetime.now(UTC),
        effective_energy_regen(player, s), s.energy_max,
    )
    rows = (
        await session.execute(
            select(Building)
            .join(Base_, Building.base_id == Base_.id)
            .where(Base_.player_id == player.id)
        )
    ).scalars()
    active, queued, mines = set(), set(), set()
    for b in rows:
        (active if b.status == "active" else queued).add(b.building_key)
        if b.building_key == "mine" and b.status == "active" and b.production_mineral:
            mines.add(b.production_mineral)
    return depgraph.PlayerSnapshot(
        race_key=player.race_key,
        planet_key=player.planet_key,
        minerals=await player_stocks(session, player.id),
        energy=energy,
        active_buildings=active,
        queued_buildings=queued,
        mines=mines,
    )


# --------------------------------------------------------------------------- #
# Daily hack budget (lazy reset, no cron / no Redis)
# --------------------------------------------------------------------------- #
def _same_day(a: datetime | None, b: datetime) -> bool:
    if a is None:
        return False
    a = a if a.tzinfo else a.replace(tzinfo=UTC)
    return a.date() == b.date()


def hacks_left(player: Player, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    used = player.assistant_hacks_used if _same_day(player.assistant_hacks_reset_at, now) else 0
    return max(0, get_settings().assistant_hacks_per_day - used)


def _consume_hack(player: Player, now: datetime) -> None:
    if not _same_day(player.assistant_hacks_reset_at, now):
        player.assistant_hacks_used = 0
        player.assistant_hacks_reset_at = now
    player.assistant_hacks_used += 1


# --------------------------------------------------------------------------- #
# Targets + suggestions (deterministic; suggestions are always valid actions)
# --------------------------------------------------------------------------- #
def _all_targets() -> list[str]:
    c = get_content()
    return (
        [k for k in c.buildings if k != "headquarters"]
        + list(c.units)
        + list(c.technologies)
    )


def _suggestion_for_target(target: str) -> Suggestion | None:
    c = get_content()
    if target in c.buildings:
        if target == "mine":
            return None  # needs a mineral choice; offered via the mineral blockers instead
        return Suggestion(action="build", label=f"Construir {c.buildings[target]['name']}",
                          params={"building": target})
    if target in c.units:
        return Suggestion(action="train", label=f"Entrenar {c.units[target]['name']}",
                          params={"unit": target, "quantity": 1})
    if target in c.technologies:
        return Suggestion(action="research", label=f"Investigar {c.technologies[target]['name']}",
                          params={"tech": target})
    return None


def _mentioned_minerals(message: str) -> list[str]:
    """Mineral keys the player named (ES/EN), e.g. 'mina de silicio' -> ['silicon']."""
    toks = set(depgraph._tokens(message))
    return [k for k in get_content().minerals if k in toks]


def _suggestions(
    reports: list[BlockerReport], snap: depgraph.PlayerSnapshot, message: str = ""
) -> list[Suggestion]:
    out: list[Suggestion] = []
    seen: set[str] = set()

    def add(s: Suggestion | None) -> None:
        if s is None:
            return
        key = json.dumps([s.action, s.params], sort_keys=True)
        if key not in seen:
            seen.add(key)
            out.append(s)

    # explicit mineral intent: "quiero una mina de silicio" -> a mine of THAT mineral, so the
    # one-click build carries the right mineral instead of inheriting the UI selector.
    for mineral in _mentioned_minerals(message):
        if mineral in snap.mines or not depgraph.mineral_is_local(snap.planet_key, mineral):
            continue
        add(Suggestion(action="build", label=f"Construir mina de {mineral}",
                       params={"building": "mine", "mineral": mineral}))

    for rep in reports:
        if rep.buildable:
            add(_suggestion_for_target(rep.target))
            continue
        # offer mines for locally-minable minerals you're short on and don't yet mine
        for b in rep.blockers:
            if b.kind == "mineral" and b.key not in snap.mines:
                add(Suggestion(action="build", label=f"Construir mina de {b.key}",
                               params={"building": "mine", "mineral": b.key}))
    return out[:5]


# --------------------------------------------------------------------------- #
# History
# --------------------------------------------------------------------------- #
async def list_messages(
    session: AsyncSession, player: Player, limit: int = 50
) -> list[AdvisorMessage]:
    rows = (
        await session.execute(
            select(AdvisorMessage)
            .where(AdvisorMessage.player_id == player.id)
            .order_by(AdvisorMessage.id.desc())
            .limit(limit)
        )
    ).scalars()
    return list(reversed(list(rows)))


async def _save(session: AsyncSession, player: Player, role: str, body: str) -> None:
    session.add(AdvisorMessage(player_id=player.id, role=role, body=body[:2000]))


# --------------------------------------------------------------------------- #
# Ask
# --------------------------------------------------------------------------- #
def _fallback_reply(reports: list[BlockerReport], hits: list[dict] | None = None) -> str:
    blocked = [r for r in reports if not r.buildable]
    if not blocked:
        # pregunta de mecánica / sin trabas: respondé con la regla recuperada (grounded)
        if hits:
            return "Según las reglas del juego:\n" + "\n".join(f"• {h['text']}" for h in hits[:2])
        return "Vas bien: con lo que tenés podés construir lo que mirabas. ¡Seguí expandiendo!"
    lines = []
    for r in blocked[:3]:
        parts = []
        for b in r.blockers:
            if b.kind in ("mineral", "not_producible"):
                how = b.sources[0].detail if b.sources else ""
                parts.append(f"te faltan {b.need - b.have:g} de {b.key} ({how})")
            elif b.kind == "energy":
                parts.append(f"te falta energía ({b.have:g}/{b.need:g})")
            elif b.kind == "building":
                parts.append(f"necesitás {b.key} activo")
        lines.append(f"• Para {r.target}: " + "; ".join(parts) + ".")
    return "Esto es lo que te traba ahora:\n" + "\n".join(lines)


async def ask(
    session: AsyncSession, player: Player, message: str, *, mode: str = "gpu",
    byok_key: str | None = None, byok_model: str | None = None, byok_base_url: str | None = None,
) -> AdvisorReply:
    if not player.race_key:
        raise AdvisorError("Primero hacé el onboarding (elegí planeta y raza).", 400)
    if mode == "byok" and not (byok_key and byok_model):
        raise AdvisorError("Para 'tu modelo' poné tu API key y el modelo de OpenRouter.", 400)
    await advance(session, player)
    snap = await build_snapshot(session, player)

    # RAG: recupera objetos Y mecánicas relevantes a la pregunta.
    hits = depgraph.retrieve(player.race_key, player.planet_key, message, k=6)
    matched = [d["id"] for d in hits if d["id"] in set(_all_targets())]
    # ¿es una pregunta de MECÁNICA? El mejor match es una regla, o hay una regla entre los top
    # hits y la pregunta es del tipo "cómo/cuántos/capacidad/funciona" (aunque nombre una unidad,
    # p.ej. "cuántos militares entran en un transbordador" → responder la regla, no construir).
    qtokens = set(depgraph._tokens(message))
    mech_top = any(d.get("type") == "mechanic" for d in hits[:3])
    # es mecánica si una regla aparece arriba Y la pregunta usa una palabra de mecánica/ayuda
    # (evita que "qué construyo" caiga acá: ahí no hay palabra de mecánica → va a blockers).
    mechanics_q = bool(hits) and mech_top and bool(qtokens & _MECH_WORDS)
    if mechanics_q:
        targets = []                                  # "cómo funciona X" → responde desde knowledge
    elif matched:
        targets = matched                             # preguntó por objetos puntuales
    else:
        targets = [t for t in _all_targets() if t not in snap.active_buildings][:6]  # "¿qué hago?"
    reports = [depgraph.analyze(snap, t) for t in targets]

    from app.services.espionage import player_intel  # local: evita ciclo de imports
    intel = await player_intel(session, player)

    reply_text = await _llm_or_fallback(
        session, player, message, snap, hits, reports, intel,
        mode=mode, byok_key=byok_key, byok_model=byok_model, byok_base_url=byok_base_url,
    )
    suggestions = _suggestions(reports, snap, message)
    left = hacks_left(player)
    hackable = ("mineral", "not_producible", "energy")
    can_hack = left > 0 and any(
        not r.buildable and any(b.kind in hackable for b in r.blockers)
        for r in reports
    )

    await _save(session, player, "user", message)
    await _save(session, player, "assistant", reply_text)
    from app.services.journal import record  # SDD 40: uso del asistente por jugador
    await record(session, "advisor_ask", player.id)
    await session.commit()

    return AdvisorReply(
        reply=reply_text,
        blockers=[r for r in reports if not r.buildable],
        suggestions=suggestions,
        hack_available=can_hack,
        hacks_left=left,
    )


def _intel_for_context(intel: list[dict], now: datetime) -> list[dict]:
    """Resumen compacto de la intel del jugador para el LLM (top por confianza)."""
    out = []
    for r in sorted(intel, key=lambda x: x["confidence"], reverse=True)[:5]:
        as_of = r["as_of"]
        as_of = as_of if getattr(as_of, "tzinfo", None) else as_of.replace(tzinfo=UTC)
        out.append({
            "target": r["target"],
            "depth": r["depth"],
            "confidence": r["confidence"],
            "age_hours": round((now - as_of).total_seconds() / 3600, 1),
            "shared": r.get("shared", False),
            "data": r["payload"],
        })
    return out


async def _meta_text(session) -> str:
    try:
        from app.services.insights import meta_summary_text
        return await meta_summary_text(session)
    except Exception:
        return ""


async def _llm_calls_today(session: AsyncSession, player_id: int) -> int:
    """Cuántas consultas al asesor hizo el jugador HOY (UTC), desde el journal (sin cron/Redis)."""
    from sqlalchemy import func

    from app.models import GameEvent
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return (await session.execute(
        select(func.count(GameEvent.id)).where(
            GameEvent.player_id == player_id,
            GameEvent.type == "advisor_ask",
            GameEvent.created_at >= midnight,
        )
    )).scalar_one()


async def _llm_or_fallback(
    session, player, message, snap, hits, reports, intel=None, *,
    mode: str = "gpu", byok_key=None, byok_model=None, byok_base_url=None,
) -> str:
    """Prose from the LLM grounded on retrieved docs + blockers + spy intel; det. fallback.

    Modo (SDD 9): 'gpu' (local) | 'cloud' (alias pago barato) | 'byok' (key del jugador). El budget
    diario aplica a los modos que gastan recursos del server (gpu/cloud); 'byok' lo paga el
    jugador → exento."""
    s = get_settings()
    # Resolución del backend según el modo elegido (key/base_url solo se overridean en BYOK).
    model = s.assistant_llm_model or None
    api_key = base_url = None
    budgeted = True
    if mode == "cloud":
        model = s.assistant_cloud_model
    elif mode == "byok":
        model, api_key = byok_model, byok_key
        base_url = byok_base_url or s.assistant_byok_base_url
        budgeted = False   # lo paga el jugador con su key → no consume el cupo del server
    # Presupuesto diario (SDD 9 / patrón shooter): pasado el cupo NO se llama al LLM (cero tokens/
    # créditos) → tips deterministas. El asistente igual responde, solo que sin la prosa del modelo.
    if budgeted and await _llm_calls_today(session, player.id) >= s.advisor_llm_calls_per_day:
        return _fallback_reply(reports, hits)
    try:
        history = await list_messages(session, player, HISTORY_LEN)
        # SDD 9: en vez del grafo COMPLETO (~7k tokens → desborda/trunca la GPU local y cae a la
        # nube free con tope diario), mandamos el SUBGRAFO relevante (top-k del índice) +
        # los blockers (cálculo exacto). Prompt chico → la GPU lo lee entero en ~1-3s, sin truncar.
        docs = depgraph.retrieve(snap.race_key, snap.planet_key, message, k=s.advisor_graph_k)
        if not docs:   # pregunta genérica sin match → un corte acotado del grafo, no todo
            docs = depgraph.graph_documents(snap.race_key, snap.planet_key)[: s.advisor_graph_k]
        context = {
            "you_play": {"race": snap.race_key, "planet": snap.planet_key},
            "minerals": {k: round(v, 1) for k, v in snap.minerals.items()},
            "energy": round(snap.energy, 1),
            "active_buildings": sorted(snap.active_buildings),
            "knowledge": [{"id": d["id"], "type": d["type"], "text": d["text"]} for d in docs],
            "relevant": [d["id"] for d in hits],   # nodos más cercanos a la pregunta (pista)
            "blockers": [r.model_dump() for r in reports if not r.buildable],
            "intel": _intel_for_context(intel or [], datetime.now(UTC)),
            "meta": await _meta_text(session),     # SDD 41: meta aprendido de partidas reales
        }
        system = (
            "Sos el asistente personal de un jugador en un juego de estrategia espacial por "
            "turnos. 'knowledge' es la PARTE DEL GRAFO relevante a la pregunta — objetos "
            "(minerales, edificios, unidades, tecnologías, con costo/requisitos/qué habilita) y "
            "MECÁNICAS/REGLAS (combate, flotas, expediciones, espionaje, energía, investigación). "
            "DEDUCÍ la respuesta cruzando esos datos (prerequisitos, qué edificio habilita qué "
            "unidad, qué mina da qué mineral, etc.). 'relevant' marca los nodos más cercanos a la "
            "pregunta. 'blockers' es el CÁLCULO EXACTO (determinista) de qué falta y cuánto para "
            "construir/entrenar algo puntual: usalo si pregunta eso. RESPONDÉ LA PREGUNTA: si es "
            "'cómo funciona X' explicá la regla; si es 'qué necesito para Y' deducí del grafo + "
            "blockers. Respondé en español, breve y concreto. NO inventes objetos ni reglas fuera "
            "de 'knowledge'; si algo no está, decilo (quizá no esté en esta porción). "
            "'intel' es lo que tus espías saben de rivales (depth/confidence/age_hours): para "
            "ataques usá SOLO esos datos, no inventes la defensa del rival; si la intel es vieja o "
            "poco confiable, recomendá espiar de nuevo. "
            "'meta' es lo aprendido de partidas reales (win-rates por composición): usalo para "
            "recomendar tácticas que funcionan, aclarando si la muestra (n) es chica."
        )
        msgs = [{"role": "system", "content": system}]
        for m in history:
            msgs.append({"role": m.role, "content": m.body})
        msgs.append({"role": "user", "content": f"{message}\n\nCONTEXTO:\n{json.dumps(context)}"})
        reply = await llm_chat(
            msgs, max_tokens=400, user=f"player:{player.username}",   # SDD 28
            model=model, timeout=s.assistant_llm_timeout_seconds,
            api_key=api_key, base_url=base_url,   # solo seteados en BYOK
        )
        return reply.strip() or _fallback_reply(reports, hits)
    except Exception:
        return _fallback_reply(reports, hits)


# --------------------------------------------------------------------------- #
# Hack
# --------------------------------------------------------------------------- #
async def grant_hack(session: AsyncSession, player: Player, target: str) -> dict:
    if not player.race_key:
        raise AdvisorError("Primero hacé el onboarding.", 400)
    try:
        depgraph.target_kind(get_content(), target)
    except KeyError as e:
        raise AdvisorError(f"Objetivo desconocido: {target}", 404) from e

    await advance(session, player)
    now = datetime.now(UTC)
    if hacks_left(player, now) <= 0:
        per_day = get_settings().assistant_hacks_per_day
        raise AdvisorError(f"Sin hacks hoy ({per_day}/{per_day}). Vuelven mañana.", 429)

    snap = await build_snapshot(session, player)
    rep = depgraph.analyze(snap, target)
    if rep.buildable:
        raise AdvisorError(f"No te falta nada para {target}.", 400)

    granted: dict[str, float] = {}
    for b in rep.blockers:
        if b.kind in ("mineral", "not_producible"):
            shortfall = b.need - b.have
            if shortfall > 0:
                st = await get_or_create_stock(session, player.id, b.key, player.planet_key)
                st.amount += shortfall
                granted[b.key] = granted.get(b.key, 0.0) + shortfall
        elif b.kind == "energy":
            player.energy = max(player.energy, b.need)
            player.energy_updated_at = now
            granted["energy"] = b.need - b.have

    if not granted:
        # only a missing prerequisite building blocks it — a hack of materials won't help
        raise AdvisorError(
            f"Para {target} primero necesitás el edificio requerido; el hack solo consigue "
            "materiales/energía.", 400
        )

    _consume_hack(player, now)
    left = hacks_left(player, now)
    detail = ", ".join(f"{v:g} {k}" for k, v in granted.items())
    msg = f"💀 Acceso root concedido… materialicé {detail} para desbloquear {target}."
    await notify(session, player.id, "advisor_hack", msg, {"target": target, "granted": granted})
    await _save(session, player, "assistant", msg)
    await session.commit()
    return {"granted": granted, "message": msg, "hacks_left": left}


# --------------------------------------------------------------------------- #
# Asistencia de energía por ranking (SDD 40): los últimos nivelan rápido; el resto +100, 3/día.
# --------------------------------------------------------------------------- #
def assist_energy_left(player: Player, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    used = player.assist_energy_used if _same_day(player.assist_energy_reset_at, now) else 0
    return max(0, get_settings().assist_energy_per_day - used)


async def grant_assist_energy(session: AsyncSession, player: Player) -> dict:
    """Energía de nivelado proporcional a qué tan lejos estás del promedio del ranking (SDD 40/41).

    Fórmula (determinista, pareja, anti-ventaja):
        deficit = clamp((avg - my) / max(avg, 1), 0, 1)   # 0 si estás en/sobre el promedio
        grant   = clamp(deficit · energy_max, piso, energy_max)   # rezagado→lleno; promedio→nada
        grant   = min(grant, headroom)                            # cap al pool
    Los punteros (deficit 0) no reciben nada y NO gastan cupo → no hay snowball; la energía es
    transitoria (regenera). Hasta N veces/día."""
    from app.services.scoring import player_score

    if not player.race_key:
        raise AdvisorError("Primero hacé el onboarding.", 400)
    s = get_settings()
    now = datetime.now(UTC)
    if assist_energy_left(player, now) <= 0:
        per = s.assist_energy_per_day
        raise AdvisorError(f"Sin nivelado hoy ({per}/{per}). Vuelve mañana.", 429)

    await advance(session, player)   # energía al día antes de calcular

    peers = (
        await session.execute(
            select(Player).where(
                Player.is_npc.is_(False),
                Player.race_key.is_not(None),
                Player.galaxy_instance_id == player.galaxy_instance_id,
            )
        )
    ).scalars().all()
    scores = [await player_score(session, p) for p in peers]
    my_score = await player_score(session, player)
    avg = (sum(scores) / len(scores)) if scores else my_score
    deficit = max(0.0, min(1.0, (avg - my_score) / max(avg, 1.0)))   # qué tan lejos del promedio

    if deficit <= 0:   # estás en o sobre el promedio → no necesitás nivelar (no gasta cupo)
        return {"granted": 0.0, "energy": round(player.energy, 1), "deficit": 0.0,
                "left": assist_energy_left(player, now),
                "message": "Estás en o sobre el promedio: no necesitás nivelar."}

    headroom = max(0.0, s.energy_max - player.energy)
    target = max(s.assist_energy_normal, deficit * s.energy_max)   # piso para los que están debajo
    grant = round(min(target, s.energy_max, headroom), 1)

    player.energy = min(s.energy_max, player.energy + grant)
    player.energy_updated_at = now
    if not _same_day(player.assist_energy_reset_at, now):
        player.assist_energy_used = 0
        player.assist_energy_reset_at = now
    player.assist_energy_used += 1

    from app.services.journal import record
    await record(session, "assist_energy", player.id,
                 granted=grant, deficit=round(deficit, 3))
    await session.commit()
    return {
        "granted": grant,
        "energy": round(player.energy, 1),
        "deficit": round(deficit, 3),
        "left": assist_energy_left(player, now),
        "message": f"Estás {round(deficit * 100)}% por debajo del promedio.",
    }
