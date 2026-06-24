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
def _fallback_reply(reports: list[BlockerReport]) -> str:
    blocked = [r for r in reports if not r.buildable]
    if not blocked:
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


async def ask(session: AsyncSession, player: Player, message: str) -> AdvisorReply:
    if not player.race_key:
        raise AdvisorError("Primero hacé el onboarding (elegí planeta y raza).", 400)
    await advance(session, player)
    snap = await build_snapshot(session, player)

    # focus on what the player asked about (RAG), else on the next buildable things
    hits = depgraph.retrieve(player.race_key, player.planet_key, message, k=6)
    targets = [d["id"] for d in hits if d["id"] in set(_all_targets())]
    if not targets:
        targets = [t for t in _all_targets() if t not in snap.active_buildings][:6]
    reports = [depgraph.analyze(snap, t) for t in targets]

    reply_text = await _llm_or_fallback(session, player, message, snap, hits, reports)
    suggestions = _suggestions(reports, snap, message)
    left = hacks_left(player)
    hackable = ("mineral", "not_producible", "energy")
    can_hack = left > 0 and any(
        not r.buildable and any(b.kind in hackable for b in r.blockers)
        for r in reports
    )

    await _save(session, player, "user", message)
    await _save(session, player, "assistant", reply_text)
    await session.commit()

    return AdvisorReply(
        reply=reply_text,
        blockers=[r for r in reports if not r.buildable],
        suggestions=suggestions,
        hack_available=can_hack,
        hacks_left=left,
    )


async def _llm_or_fallback(session, player, message, snap, hits, reports) -> str:
    """Prose from the LLM grounded on retrieved docs + blockers; deterministic fallback."""
    try:
        history = await list_messages(session, player, HISTORY_LEN)
        context = {
            "you_play": {"race": snap.race_key, "planet": snap.planet_key},
            "minerals": {k: round(v, 1) for k, v in snap.minerals.items()},
            "energy": round(snap.energy, 1),
            "active_buildings": sorted(snap.active_buildings),
            "knowledge": [{"id": d["id"], "text": d["text"]} for d in hits],
            "blockers": [r.model_dump() for r in reports if not r.buildable],
        }
        system = (
            "Sos el asistente personal de un jugador en un juego de estrategia espacial por "
            "turnos. Tu conocimiento del juego es SOLO el grafo que te paso en 'knowledge' y los "
            "'blockers' (qué le falta y cuánto). Respondé en español, breve y concreto: explicá "
            "qué le falta y cómo conseguirlo (mina local, expedición, saqueo, comercio). No "
            "inventes recursos ni reglas que no estén en el contexto."
        )
        msgs = [{"role": "system", "content": system}]
        for m in history:
            msgs.append({"role": m.role, "content": m.body})
        msgs.append({"role": "user", "content": f"{message}\n\nCONTEXTO:\n{json.dumps(context)}"})
        reply = await llm_chat(msgs, max_tokens=400, user=f"player:{player.username}")  # SDD 28
        return reply.strip() or _fallback_reply(reports)
    except Exception:
        return _fallback_reply(reports)


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
                (await get_or_create_stock(session, player.id, b.key)).amount += shortfall
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
