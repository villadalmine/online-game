"""SDD 2 — Personal AI assistant: advises a player using the dependency graph (SDD 1) as its
skill, the same provider-agnostic LLM as the NPCs (with a deterministic fallback), and an
emergency "hack" that grants the minimal missing materials, capped at N/day.

Truth about feasibility is deterministic (depgraph.analyze); the LLM only writes prose. So a
hallucination can never produce an invalid suggestion or an over-grant. See
docs/sdd-ai-assistant.md.
"""
import json
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
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
from app.services.physics import effective_energy_max, effective_energy_regen
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


# Palabras de ORDEN (imperativos) → si pedís explícito "construime X" y te alcanza un hack, el
# asistente lo usa solo (grant + build). NO incluye "qué/conviene" (preguntas).
_BUILD_CMD_WORDS = {
    "construime", "construí", "construir", "construilo", "construirme", "construis", "construís",
    "constrúyelo", "constrúyeme", "constrúime", "podés", "podes", "puedes", "podrías", "podrias",
    "hazme", "haceme", "házmelo", "armame", "armá", "fabricame", "fabricá", "fabrícame", "fabricar",
    "levantame", "ponme", "dame", "consegui", "conseguí", "conseguime", "necesito", "quiero",
    "build", "make", "give",
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
        effective_energy_regen(player, s), effective_energy_max(player, s),
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


def _teleport_intent(message: str) -> bool:
    """SDD 77 v2: ¿el jugador pide teletransportar/mandar electrónica entre búnkeres?"""
    m = message.lower()
    if any(w in m for w in ("teletransport", "teleport", "cuántic", "cuantic")):
        return True
    # stems (los imperativos con tilde mandá/enviá/mové no matchean "manda"/"move" exactos)
    verb = any(w in m for w in ("envi", "mand", "mov", "pas", "traslad"))
    obj = any(w in m for w in ("electrón", "electron", "búnker", "bunker", "reserva"))
    return verb and obj


def _first_amount(message: str) -> float | None:
    """SDD 77 v3: primer número del mensaje (para respetar 'mandá 300 electrónica')."""
    import re
    mt = re.search(r"\d+(?:[.,]\d+)?", message)
    if not mt:
        return None
    try:
        return float(mt.group(0).replace(",", "."))
    except ValueError:
        return None


def _energy_intent(message: str) -> bool:
    """SDD 77 v3: ¿el jugador pide nivelar/pide energía?"""
    m = message.lower()
    return any(w in m for w in ("nivel", "energ", "level up", "level-up"))


def _fortify_intent(message: str) -> bool:
    """SDD 77 v3: ¿el jugador pide defender/fortificar una base?"""
    m = message.lower()
    return any(w in m for w in ("defend", "defens", "fortific", "torret", "proteg", "turret"))


async def _undefended_bases(session, player: Player) -> list:
    """SDD 77 v3: bases del jugador SIN edificio defensivo activo (defense_power>0)."""
    bases = (await session.execute(
        select(Base_).where(Base_.player_id == player.id)
    )).scalars().all()
    if not bases:
        return []
    content = get_content()
    active = (await session.execute(
        select(Building.base_id, Building.building_key).where(
            Building.base_id.in_([b.id for b in bases]), Building.status == "active")
    )).all()
    def_bases = {bid for bid, bk in active
                 if content.buildings.get(bk, {}).get("defense_power", 0) > 0}
    return [b for b in bases if b.id not in def_bases]


async def _fortify_suggestion(session, player: Player, message: str) -> Suggestion | None:
    """SDD 77 v3: si pedís defender/fortificar y hay una base sin defensa, la IA propone una torreta
    EN ESA base (pasa el base_id → no la construye en la base equivocada)."""
    if not _fortify_intent(message):
        return None
    undef = await _undefended_bases(session, player)
    if not undef:
        return None
    b = undef[0]
    return Suggestion(action="build", label=f"🔫 Torreta en #{b.id} ({b.planet_key})",
                      params={"building": "turret", "base_id": b.id})


def _spy_intent(message: str) -> bool:
    """SDD 77 v3: ¿el jugador pide espiar/escanear a un rival? (stems, ojo con las tildes)"""
    m = message.lower()
    return any(w in m for w in ("espi", "spy", "escane", "scout", "reconoc", "intel"))


def _capabilities_intent(message: str) -> bool:
    """SDD 77 v3: ¿el jugador pregunta QUÉ puede hacer la IA? (respuesta determinista, sin LLM)."""
    m = message.lower()
    return any(w in m for w in ("qué podés", "que podes", "qué sabés", "que sabes", "qué acciones",
                                "que acciones", "cuáles tenés", "cuales tenes", "what can you",
                                "qué comandos", "que comandos"))


_CAPABILITIES_TEXT = (
    "Puedo aconsejarte y también EJECUTAR acciones (te dejo un botón para confirmar):\n"
    "• 🏗 construir / entrenar / investigar lo que pidas\n"
    "• 🔓 crear gratis algo (hack, 3/día)\n"
    "• 🔫 fortificar: torreta en una base sin defensa\n"
    "• ⚛ teletransportar electrónica entre búnkeres (con Puerta cuántica)\n"
    "• ⚡ nivelar energía\n"
    "• 🛰🔍 espiar a un rival (con satélite espía)\n"
    "Pedímelo en criollo: «fortificá mi base», «espiá a npc_terran», «mandá 300 "
    "electrónica al otro búnker», «investigá terraformación»."
)


async def _spy_suggestion(session, player: Player, message: str) -> Suggestion | None:
    """SDD 77 v3: si pedís espiar a un rival NOMBRADO y tenés un satélite espía, la IA propone
    lanzarlo a esa base (conocer su defensa antes de atacar). Requiere satélites habilitados."""
    if not get_settings().satellites_enabled or not _spy_intent(message):
        return None
    from app.services.training import player_units
    if (await player_units(session, player.id)).get("spy_satellite", 0) <= 0:
        return None
    m = message.lower()
    candidates = (await session.execute(
        select(Player).where(Player.id != player.id, Player.race_key.is_not(None))
    )).scalars().all()
    for c in candidates:                                   # el primer rival cuyo nombre aparezca
        if c.username and c.username.lower() in m:
            if not c.is_npc and c.galaxy_instance_id != player.galaxy_instance_id:
                continue                                   # humano de otra galaxia: no lo ves
            return Suggestion(action="spy", label=f"🛰🔍 Espiar a {c.username}",
                              params={"unit_key": "spy_satellite", "target_id": c.id})
    return None


async def _teleport_suggestion(session, player: Player, message: str) -> Suggestion | None:
    """SDD 77 v2: si pedís mandar electrónica y tenés la capacidad (2+ búnkeres y una Puerta
    cuántica activa), la IA propone un teletransporte LISTO (defaults sensatos) para confirmar."""
    s = get_settings()
    if not (s.bunkers_enabled and s.quantum_teleport_enabled) or not _teleport_intent(message):
        return None
    from app.models import Bunker
    from app.services.bunkers import _has_teleporter
    bunkers = (await session.execute(
        select(Bunker).where(Bunker.player_id == player.id)
    )).scalars().all()
    if len(bunkers) < 2:
        return None
    gated = [b for b in bunkers if await _has_teleporter(session, b.id)]
    if not gated:
        return None
    src = max(gated, key=lambda b: b.electronics)         # origen: puerta activa + más electrónica
    if src.electronics <= 0:
        return None
    dst = min((b for b in bunkers if b.id != src.id), key=lambda b: b.electronics)  # el más pobre
    asked = _first_amount(message)                        # SDD 77 v3: respetá el número que pediste
    amount = (round(min(asked, src.electronics), 1) if asked and asked > 0
              else round(src.electronics * 0.5, 1))       # default: la mitad de la reserva origen
    if amount <= 0:
        return None
    return Suggestion(
        action="teleport",
        label=f"⚛ Enviar {amount:g} electrónica de #{src.base_id} → #{dst.base_id}",
        params={"from_base_id": src.base_id, "to_base_id": dst.base_id, "amount": amount},
    )


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


async def clear_messages(session: AsyncSession, player: Player) -> int:
    """SDD 77 v4: borra TODO el historial del chat del asistente (el hilo se pone enorme).
    No afecta a la vida artificial (autopiloto): son IAs distintas. Devuelve cuántos borró."""
    res = await session.execute(
        delete(AdvisorMessage).where(AdvisorMessage.player_id == player.id)
    )
    await session.commit()
    return res.rowcount or 0


async def _save(session: AsyncSession, player: Player, role: str, body: str) -> None:
    session.add(AdvisorMessage(player_id=player.id, role=role, body=body[:2000]))


# --------------------------------------------------------------------------- #
# SDD 77: la IA te ESCRIBE sola (mensaje proactivo) ante una situación notable.
# --------------------------------------------------------------------------- #
PROACTIVE_ROLE = "proactive"


async def _last_proactive_at(session: AsyncSession, player_id: int):
    return (await session.execute(
        select(AdvisorMessage.created_at)
        .where(AdvisorMessage.player_id == player_id, AdvisorMessage.role == PROACTIVE_ROLE)
        .order_by(AdvisorMessage.id.desc()).limit(1)
    )).scalar_one_or_none()


async def _proactive_note(session: AsyncSession, player: Player) -> str | None:
    """Situación notable → texto determinista que la IA te 'escribe'. None si no hay urgencias."""
    from app.models import AttackMission, StrikeMission
    atk = (await session.execute(
        select(func.count()).select_from(AttackMission).where(
            AttackMission.defender_id == player.id, AttackMission.status == "outbound")
    )).scalar() or 0
    strike = (await session.execute(
        select(func.count()).select_from(StrikeMission).where(
            StrikeMission.defender_id == player.id, StrikeMission.status == "outbound")
    )).scalar() or 0
    if atk or strike:
        parts = []
        if atk:
            parts.append(f"{atk} flota(s)")
        if strike:
            parts.append(f"{strike} salva(s) de misiles")
        return ("⚠ Ojo: tenés " + " y ".join(parts) + " en camino hacia vos. Reforzá con torretas/"
                "tropas en la base atacada o preparate para el golpe.")
    # 🛡 alguna colonia SIN defensa activa (si tenés más de una base)
    bases_ct = (await session.execute(
        select(func.count()).select_from(Base_).where(Base_.player_id == player.id)
    )).scalar() or 0
    if bases_ct >= 2:
        undef = await _undefended_bases(session, player)
        if undef:
            b = undef[0]
            return (f"🛡 Tu base #{b.id} ({b.planet_key}) no tiene defensa activa. Construí una "
                    "torreta ahí antes de que sea un blanco fácil.")
    s = get_settings()
    emax = effective_energy_max(player, s)
    if emax and player.energy < emax * 0.08:
        return ("⚡ Estás casi sin energía. Antes de gastar en construir/entrenar, dejá regenerar "
                "o sumá una planta de energía; si no, se te traban las colas.")
    return None


async def proactive_check(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> bool:
    """SDD 77: la IA te escribe sola ante una situación notable, con cooldown por jugador. Devuelve
    True si escribió. Barato (2 counts + 1 lookup), gateado por flag + cooldown; no gasta LLM."""
    s = get_settings()
    if not s.advisor_proactive_enabled or not player.race_key:
        return False
    now = now or datetime.now(UTC)
    last = await _last_proactive_at(session, player.id)
    if last is not None:
        last = last if last.tzinfo else last.replace(tzinfo=UTC)
        if (now - last).total_seconds() < s.advisor_proactive_cooldown_hours * 3600:
            return False
    note = await _proactive_note(session, player)
    if not note:
        return False
    await _save(session, player, PROACTIVE_ROLE, note)
    # SDD 77: además del chat, dejá una notificación (🔔) para que se vea con el panel cerrado.
    await notify(session, player.id, "advisor_proactive", note)
    from app.services.journal import record
    await record(session, "advisor_proactive", player.id)
    return True


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

    # SDD 77 v3: "¿qué podés hacer?" → lista determinista de capacidades (sin gastar LLM).
    if _capabilities_intent(message):
        await _save(session, player, "user", message)
        await _save(session, player, "assistant", _CAPABILITIES_TEXT)
        from app.services.journal import record
        await record(session, "advisor_ask", player.id, mode="caps")
        await session.commit()
        return AdvisorReply(reply=_CAPABILITIES_TEXT, blockers=[], suggestions=[],
                            hack_available=False, hacks_left=hacks_left(player))

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

    # SDD 2: si DAS LA ORDEN explícita ("construime X") sobre UN objetivo y te queda hack diario, el
    # asistente lo CREA GRATIS solo (tengas o no materiales). Si el hack no aplica (mina/silo piden
    # mineral), sigue con la respuesta normal.
    qwords = set(message.lower().replace(",", " ").replace(".", " ").split())
    # mina/silo NO se auto-hackean por lenguaje natural: el jugador elige el mineral (se ofrece como
    # sugerencia que lo lleva). El botón directo /hack sí los crea (default estructural).
    _picks_mineral = get_content().buildings.get(
        matched[0] if matched else "", {}).get("category") in ("mine", "storage")
    if (len(matched) == 1 and (qwords & _BUILD_CMD_WORDS) and hacks_left(player) > 0
            and not _picks_mineral):
        _pid = player.id   # capturar ANTES (un rollback expira el objeto → .id haría IO lazy)
        try:
            res = await grant_hack(session, player, matched[0])   # crea gratis (cadena completa)
        except AdvisorError:
            await session.rollback()                  # deshace grants parciales…
            player = await session.get(Player, _pid)  # …y refresca el player (evita expirado)
            res = None
        if res:
            await _save(session, player, "user", message)
            from app.services.journal import record
            await record(session, "advisor_ask", player.id, mode="hack")  # sin LLM (crear gratis)
            await session.commit()
            return AdvisorReply(reply=res["message"], blockers=[], suggestions=[],
                                hack_available=False, hacks_left=res["hacks_left"])

    from app.services.espionage import player_intel  # local: evita ciclo de imports
    intel = await player_intel(session, player)

    reply_text = await _llm_or_fallback(
        session, player, message, snap, hits, reports, intel,
        mode=mode, byok_key=byok_key, byok_model=byok_model, byok_base_url=byok_base_url,
    )
    suggestions = _suggestions(reports, snap, message)
    tp = await _teleport_suggestion(session, player, message)   # SDD 77 v2: acción teletransporte
    if tp:
        suggestions = [tp, *suggestions]
    if _energy_intent(message) and assist_energy_left(player) > 0:   # SDD 77 v3: nivelar energía
        suggestions = [Suggestion(action="assist_energy", label="⚡ Nivelar energía"), *suggestions]
    ft = await _fortify_suggestion(session, player, message)   # SDD 77 v3: torreta en base indef.
    if ft:
        suggestions = [ft, *suggestions]
    sp = await _spy_suggestion(session, player, message)       # SDD 77 v3: espiar rival nombrado
    if sp:
        suggestions = [sp, *suggestions]
    left = hacks_left(player)
    # SDD 2: con hacks disponibles, el jugador puede CREAR GRATIS cualquier cosa que preguntó
    # (tenga o no materiales). Si nombró objetos, esos; si no, los de las sugerencias.
    hack_targets = list(matched) or [
        s.params.get("building") or s.params.get("unit") or s.params.get("tech")
        for s in suggestions
    ]
    hack_targets = [t for t in dict.fromkeys(hack_targets) if t][:6]
    can_hack = left > 0 and bool(hack_targets)

    await _save(session, player, "user", message)
    await _save(session, player, "assistant", reply_text)
    from app.services.journal import record  # SDD 40: uso del asistente por jugador
    await record(session, "advisor_ask", player.id, mode=mode)  # gpu|cloud|byok → gráfico in-app
    await session.commit()

    return AdvisorReply(
        reply=reply_text,
        blockers=[r for r in reports if not r.buildable],
        suggestions=suggestions,
        hack_available=can_hack,
        hacks_left=left,
        hack_targets=hack_targets,
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
            "recomendar tácticas que funcionan, aclarando si la muestra (n) es chica. "
            "PODÉS OFRECER ACCIONES DE UN CLIC (aparecen como botones, el jugador confirma): "
            "construir/entrenar/investigar, 'crear gratis' (hack) lo que falte, nivelar energía, y "
            "teletransportar electrónica entre búnkeres (si tenés Puerta cuántica). Si el jugador "
            "pide una de esas, mencioná que se la dejás lista para confirmar."
        )
        msgs = [{"role": "system", "content": system}]
        for m in history:
            # SDD 77: los mensajes proactivos van como 'assistant' para la API del LLM.
            role = m.role if m.role in ("user", "assistant") else "assistant"
            msgs.append({"role": role, "content": m.body})
        msgs.append({"role": "user", "content": f"{message}\n\nCONTEXTO:\n{json.dumps(context)}"})
        reply = await llm_chat(
            msgs, max_tokens=400, user=f"player:{player.username}", kind="advisor",   # SDD 28
            route=mode,   # SDD 65 obs: gpu|cloud|byok → tokens/heartbeat por ruta
            model=model, timeout=s.assistant_llm_timeout_seconds,
            api_key=api_key, base_url=base_url,   # solo seteados en BYOK
        )
        return reply.strip() or _fallback_reply(reports, hits)
    except Exception:
        return _fallback_reply(reports, hits)


# --------------------------------------------------------------------------- #
# Hack
# --------------------------------------------------------------------------- #
async def grant_hack(
    session: AsyncSession, player: Player, target: str, target_mineral: str | None = None
) -> dict:
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

    # SDD 2: el hack CREA GRATIS — arma toda la cadena (edificios previos que faltan + tecnologías
    # requeridas que falten, materializados y dejados LISTOS al instante) y al final el target,
    # cubriendo el COSTO COMPLETO de cada paso (no solo "lo que falta"). Tengas o no materiales,
    # la creación sale gratis (el build cobra y el hack ya lo regaló → neto 0). Gasta 1 hack diario.
    from app.services.research import researched_techs
    have_techs = await researched_techs(session, player.id)
    chain = [b for b in depgraph.prerequisites(target) if b not in snap.active_buildings]
    chain += [t for t in _tech_chain(target) if t not in have_techs]
    chain.append(target)
    granted: dict[str, float] = {}
    built_items: list[str] = []
    for item in chain:
        cost = depgraph.target_cost(player.race_key, item)   # costo COMPLETO → creación gratis
        for mineral, amt in cost.minerals.items():
            st = await get_or_create_stock(session, player.id, mineral, player.planet_key)
            st.amount += amt
            granted[mineral] = granted.get(mineral, 0.0) + amt
        if cost.energy:
            player.energy += cost.energy
            player.energy_updated_at = now
            granted["energy"] = granted.get("energy", 0.0) + cost.energy
        verb = await _auto_execute(session, player, item, activate=(item != target),
                                   target_mineral=target_mineral if item == target else None)
        if verb:
            built_items.append(f"{verb} {item}")

    if not built_items:
        raise AdvisorError(
            f"No pude crear {target} (quizás necesita elegir un mineral, como una mina/silo).", 400
        )

    _consume_hack(player, now)
    left = hacks_left(player, now)
    done = "; ".join(built_items)
    msg = (f"💀 Hack: creé gratis {done} (sin cobrarte materiales). "
           f"Usé 1 hack diario — te quedan {left}.")
    await notify(session, player.id, "advisor_hack", msg,
                 {"target": target, "granted": granted, "built": built_items})
    await _save(session, player, "assistant", msg)
    await session.commit()
    return {"granted": granted, "message": msg, "hacks_left": left}


def _tech_chain(target: str) -> list[str]:
    """Cadena de tecnologías requeridas por `target` (requires_tech, transitiva), en orden de
    investigación (la raíz primero). Vacía si el target no pide tech."""
    content = get_content()
    spec = (content.units.get(target) or content.buildings.get(target)
            or content.technologies.get(target) or {})
    rt = spec.get("requires_tech")
    out: list[str] = []
    seen: set[str] = set()
    while rt and rt not in seen:
        seen.add(rt)
        out.insert(0, rt)
        rt = content.technologies.get(rt, {}).get("requires_tech")
    return out


async def _auto_execute(
    session: AsyncSession, player: Player, target: str, *, activate: bool = False,
    target_mineral: str | None = None,
) -> str | None:
    """Tras el hack, ejecuta la acción del `target` en la base natal (best-effort). `activate`=True
    (para los edificios PREVIOS de la cadena) lo deja ACTIVO al instante, así el siguiente paso ve
    su requisito cumplido. `target_mineral` (mina/silo) usa el elegido o el estructural de la raza.
    Devuelve el verbo en pasado, o None si pide elección/falló."""
    content = get_content()
    kind = depgraph.target_kind(content, target)
    try:
        if kind == "tech":
            if activate:   # tech previa de la cadena → concedela ya (el hack saltea timer/lab)
                from app.models import PlayerTech
                from app.services.research import researched_techs
                if target not in await researched_techs(session, player.id):
                    session.add(PlayerTech(player_id=player.id, tech_key=target))
                    await session.flush()
                return "investigué"
            from app.services.research import start_research
            await start_research(session, player, target)
            return "investigué"
        base = (await session.execute(
            select(Base_).where(Base_.player_id == player.id).order_by(Base_.id).limit(1)
        )).scalar_one_or_none()
        if base is None:
            return None
        if kind == "unit":
            from app.services.training import start_training
            await start_training(session, player, base, target, 1)
            return "entrené"
        from app.services.build import start_build
        # mina/silo piden un mineral: usá el elegido o el estructural (siempre producible) como
        # default, así el hack también crea minas/silos (antes los saltaba → "no pude crear").
        mineral = None
        if content.buildings.get(target, {}).get("category") in ("mine", "storage"):
            mineral = target_mineral or content.resolve_role(player.race_key, "structural")
            if mineral is None:
                return None
        building = await start_build(session, player, base, target, target_mineral=mineral)
        if activate:   # edificio previo de la cadena → activarlo ya (el hack saltea el timer)
            building.status = "active"
            building.completes_at = datetime.now(UTC)
            await session.flush()
        return "construí"
    except Exception:
        return None


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

    cap = effective_energy_max(player, s)
    headroom = max(0.0, cap - player.energy)
    target = max(s.assist_energy_normal, deficit * cap)   # piso para los que están debajo
    grant = round(min(target, cap, headroom), 1)

    player.energy = min(cap, player.energy + grant)
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
