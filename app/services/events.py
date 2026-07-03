"""Eventos dinámicos del mundo (SDD 36, "happy hour").

Se disparan en horas aleatorias desde el tick (`maybe_start_event`, RNG sembrable → testeable),
viven en la DB (`WorldEvent`) y se leen perezosamente: `event_multiplier` apila como un factor más
(producción/ataque/defensa/energía), `build_cost_multiplier` abarata construir, y los `free_units`
se acreditan una vez por jugador en `state.advance` (`grant_due_free_units`).
"""
import json
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import EventGrant, Player, WorldEvent


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def active_events(session: AsyncSession, now: datetime | None = None) -> list[WorldEvent]:
    now = now or datetime.now(UTC)
    res = await session.execute(select(WorldEvent).where(WorldEvent.ends_at > now))
    return [e for e in res.scalars() if _aware(e.starts_at) <= now]


async def event_multiplier(
    session: AsyncSession, effect: str, now: datetime | None = None
) -> float:
    """Producto de los eventos activos para un efecto (production|attack|defense|energy_regen)."""
    mult = 1.0
    for e in await active_events(session, now):
        if e.effect == effect:
            mult *= e.magnitude
    return mult


async def build_cost_multiplier(session: AsyncSession, now: datetime | None = None) -> float:
    """Multiplicador de costo de construcción (eventos build_cost; <1 = más barato)."""
    return await event_multiplier(session, "build_cost", now)


async def solar_storm_active(session: AsyncSession, now: datetime | None = None) -> bool:
    """SDD 72: ¿hay una tormenta solar activa? Si sí: NO se fabrica nada (unidades/drones/misiles/
    satélites) — solo construir edificios — y la energía es infinita (construir no cuesta)."""
    return any(e.effect == "solar_storm" for e in await active_events(session, now))


# --------------------------------------------------------------------------- #
# Scheduling (en el tick): arranca un evento nuevo en horas aleatorias
# --------------------------------------------------------------------------- #
async def maybe_start_event(
    session: AsyncSession, now: datetime | None = None, rng: random.Random | None = None
) -> WorldEvent | None:
    """Con prob. `event_chance_per_tick`, si no hay ninguno activo y pasó el cooldown, arranca un
    evento (elegido por `weight`). Determinista si se pasa `rng` (tests)."""
    settings = get_settings()
    now = now or datetime.now(UTC)
    rng = rng or random.Random()

    if await active_events(session, now):
        return None  # un evento global a la vez (v1)
    # cooldown desde el último evento creado
    last = (
        await session.execute(select(WorldEvent).order_by(WorldEvent.id.desc()).limit(1))
    ).scalar_one_or_none()
    if last is not None:
        age = (now - _aware(last.starts_at)).total_seconds()
        if age < settings.event_cooldown_seconds:
            return None
    if rng.random() > settings.event_chance_per_tick:
        return None

    catalog = [e for e in get_content().events.values() if e.get("weight", 0) > 0]
    if not catalog:
        return None
    chosen = rng.choices(catalog, weights=[e["weight"] for e in catalog], k=1)[0]
    return await start_event(session, chosen["key"], now)


async def start_event(
    session: AsyncSession, key: str, now: datetime | None = None
) -> WorldEvent:
    """Crea un WorldEvent del tipo `key` (usado por el scheduler y por /admin/events)."""
    now = now or datetime.now(UTC)
    spec = get_content().events.get(key)
    if spec is None:
        raise ValueError(f"Evento desconocido: {key}")
    ev = WorldEvent(
        key=key,
        effect=spec["effect"],
        magnitude=float(spec.get("magnitude", 1.0)),
        scope=spec.get("scope", "all"),
        starts_at=now,
        ends_at=now + timedelta(seconds=spec.get("duration_seconds", 600)),
        payload=json.dumps(
            {"grant_unit": spec["grant_unit"]} if spec.get("grant_unit") else {}
        ),
    )
    session.add(ev)
    await session.flush()
    from app.services.journal import record
    await record(session, "world_event_started", None, key=key, effect=ev.effect,
                 magnitude=ev.magnitude)
    return ev


# --------------------------------------------------------------------------- #
# free_units: acreditar una vez por jugador (lazy, en state.advance)
# --------------------------------------------------------------------------- #
async def grant_due_free_units(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> dict[str, int]:
    """Por cada evento free_units activo que el jugador no reclamó, le da las unidades. Una vez."""
    from app.services.training import get_or_create_unit_stock

    granted: dict[str, int] = {}
    for e in await active_events(session, now):
        if e.effect != "free_units":
            continue
        unit = json.loads(e.payload or "{}").get("grant_unit")
        if not unit:
            continue
        exists = (
            await session.execute(
                select(EventGrant).where(
                    EventGrant.player_id == player.id, EventGrant.event_id == e.id
                )
            )
        ).scalar_one_or_none()
        if exists is not None:
            continue
        qty = int(e.magnitude)
        stock = await get_or_create_unit_stock(session, player.id, unit)
        stock.quantity += qty
        session.add(EventGrant(player_id=player.id, event_id=e.id))
        granted[unit] = granted.get(unit, 0) + qty
    return granted


def _event_out(e: WorldEvent) -> dict:
    spec = get_content().events.get(e.key, {})
    return {
        "key": e.key,
        "name": spec.get("name", e.key),
        "description": spec.get("description", ""),
        "icon": spec.get("icon", "📣"),
        "effect": e.effect,
        "magnitude": e.magnitude,
        "ends_at": e.ends_at,
    }


async def active_events_out(session: AsyncSession, now: datetime | None = None) -> list[dict]:
    """Eventos activos para la API/UI (con i18n del catálogo y ends_at para la cuenta regresiva)."""
    return [_event_out(e) for e in await active_events(session, now)]


async def recent_events_out(
    session: AsyncSession, now: datetime | None = None, days: int = 2
) -> list[dict]:
    """Eventos que YA pasaron en los últimos `days` (para 'lo que pasó'). Más nuevos primero."""
    now = now or datetime.now(UTC)
    since = now - timedelta(days=days)
    res = await session.execute(
        select(WorldEvent)
        .where(WorldEvent.ends_at <= now, WorldEvent.ends_at > since)
        .order_by(WorldEvent.ends_at.desc())
        .limit(20)
    )
    return [_event_out(e) for e in res.scalars()]
