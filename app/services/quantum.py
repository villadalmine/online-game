"""SDD 87 — Bomba cuántica: un gusano de IA que infecta una base rival, DRENA sus recursos y baja su
capacidad progresiva (1% → `quantum_max_penalty` en `quantum_decay_days`). Se lanza como munición
intra-planeta (arsenal SDD 49: `quantum_bomb` es `domain: ordnance`). La víctima la desactiva
de tres formas: mandando TROPAS (purga), pagando el RESCATE (recursos al atacante) o, si domina la
tech cuántica, gratis pero dejando una FUGA de info (la base se transmite al atacante) hasta que
orbite un satélite INHIBIDOR (que se degrada y hay que reponer).

La penalización se aplica PLAYER-WIDE vía `effects.multiplier('production')` — el gusano "se
reproduce" y drena todo, no solo la base infectada."""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import Base_, Player, QuantumInfection, SatelliteMission


class QuantumError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def active_infection(
    session: AsyncSession, defender_id: int, base_id: int | None = None
) -> QuantumInfection | None:
    """La infección ACTIVA del jugador (la más vieja = la que más drena). Opcional por base."""
    q = select(QuantumInfection).where(
        QuantumInfection.defender_id == defender_id, QuantumInfection.status == "active"
    )
    if base_id is not None:
        q = q.where(QuantumInfection.base_id == base_id)
    return (await session.execute(q.order_by(QuantumInfection.created_at))).scalars().first()


def _penalty_at(created_at: datetime, now: datetime) -> float:
    """Penalización 1% → tope, lineal en `quantum_decay_days` (derivada del tiempo)."""
    s = get_settings()
    days = max(0.0, (now - _aware(created_at)).total_seconds() / 86400.0)
    frac = min(1.0, days / max(0.1, s.quantum_decay_days))
    return min(s.quantum_max_penalty, max(0.01, frac * s.quantum_max_penalty))


async def infection_penalty(
    session: AsyncSession, player_id: int, now: datetime | None = None
) -> float:
    """Factor (<1) para `effects.multiplier('production')`: 1.0 sin infección, baja en el tiempo."""
    if not get_settings().quantum_bomb_enabled:
        return 1.0
    now = now or datetime.now(UTC)
    inf = await active_infection(session, player_id)
    if inf is None:
        return 1.0
    return round(1.0 - _penalty_at(inf.created_at, now), 4)


async def on_bomb_impact(
    session: AsyncSession, attacker: Player, defender: Player, base_id: int, now: datetime
) -> dict:
    """La bomba impactó (no interceptada, SDD 49): crea la infección (si no hay activa en la base)
    y DRENA — roba una fracción de los minerales del planeta de la base + parte de la energía, al
    atacante. Devuelve lo robado (para el reporte)."""
    settings = get_settings()
    from app.services.economy import get_or_create_stock, planet_stocks
    from app.services.journal import record
    from app.services.notifications import notify
    existing = (await session.execute(select(QuantumInfection).where(
        QuantumInfection.base_id == base_id, QuantumInfection.status == "active"
    ))).scalars().first()
    if existing is None:
        session.add(QuantumInfection(defender_id=defender.id, attacker_id=attacker.id,
                                     base_id=base_id, status="active", created_at=now))
    base = await session.get(Base_, base_id)
    frac = settings.quantum_drain_fraction
    stolen: dict[str, float] = {}
    here = await planet_stocks(session, defender.id, base.planet_key)
    for m, amt in here.items():
        take = amt * frac
        if take > 0:
            (await get_or_create_stock(session, defender.id, m, base.planet_key)).amount -= take
            (await get_or_create_stock(session, attacker.id, m, attacker.planet_key)).amount += take
            stolen[m] = round(take, 1)
    energy_drained = round(defender.energy * frac, 1)
    defender.energy = max(0.0, defender.energy - energy_drained)
    await notify(session, defender.id, "quantum_infected",
                 f"🧬 Bomba cuántica en tu base {base_id}: un gusano de IA la está drenando. "
                 "Desactivala (tropas, rescate o tech) antes de que colapse tu producción.",
                 {"base_id": base_id})
    await record(session, "quantum_infect", attacker.id, defender_id=defender.id,
                 base_id=base_id, stolen=stolen, energy=energy_drained)
    await session.flush()
    return {"stolen": stolen, "energy_drained": energy_drained}


async def _infection_for_defender(
    session: AsyncSession, defender: Player, base_id: int
) -> QuantumInfection:
    inf = await active_infection(session, defender.id, base_id)
    if inf is None:
        raise QuantumError("No hay una infección cuántica activa en esa base.")
    return inf


async def disarm_with_troops(session: AsyncSession, defender: Player, base_id: int) -> dict:
    """Purgar el gusano mandando TROPAS a la base (consume soldados). Desactiva la infección."""
    settings = get_settings()
    inf = await _infection_for_defender(session, defender, base_id)
    need = settings.quantum_disarm_soldiers
    from app.services.training import get_or_create_unit_stock, player_units, units_at_base
    hold = base_id if settings.garrison_enabled else None
    have = (await units_at_base(session, defender.id, base_id)) if settings.garrison_enabled \
        else (await player_units(session, defender.id))
    if have.get("soldier", 0) < need:
        raise QuantumError(f"Necesitás {need} soldados en la base para purgar el gusano "
                           f"(tenés {have.get('soldier', 0)}).")
    (await get_or_create_unit_stock(session, defender.id, "soldier", hold)).quantity -= need
    inf.status, inf.disarm, inf.disarmed_at = "disarmed", "troops", datetime.now(UTC)
    from app.services.journal import record
    await record(session, "quantum_disarm", defender.id, base_id=base_id, how="troops")
    await session.flush()
    return {"disarmed": "troops", "soldiers_spent": need}


async def disarm_with_ransom(session: AsyncSession, defender: Player, base_id: int) -> dict:
    """Pagar el CHANTAJE: transfiere una fracción del stock del planeta al atacante. Desactiva."""
    settings = get_settings()
    inf = await _infection_for_defender(session, defender, base_id)
    attacker = await session.get(Player, inf.attacker_id)
    base = await session.get(Base_, base_id)
    from app.services.economy import get_or_create_stock, planet_stocks
    here = await planet_stocks(session, defender.id, base.planet_key)
    paid: dict[str, float] = {}
    for m, amt in here.items():
        pay = amt * settings.quantum_ransom_fraction
        if pay > 0:
            (await get_or_create_stock(session, defender.id, m, base.planet_key)).amount -= pay
            if attacker is not None:
                (await get_or_create_stock(
                    session, attacker.id, m, attacker.planet_key)).amount += pay
            paid[m] = round(pay, 1)
    inf.status, inf.disarm, inf.disarmed_at = "disarmed", "ransom", datetime.now(UTC)
    from app.services.journal import record
    await record(session, "quantum_disarm", defender.id, base_id=base_id, how="ransom", paid=paid)
    await session.flush()
    return {"disarmed": "ransom", "paid": paid}


async def disarm_with_quantum(session: AsyncSession, defender: Player, base_id: int) -> dict:
    """Con `quantum_warfare` investigada: desactiva GRATIS el drenaje, pero deja `leaking=True` — la
    base se transmite al atacante hasta que orbite un satélite inhibidor."""
    inf = await _infection_for_defender(session, defender, base_id)
    from app.services.research import researched_techs
    if "quantum_warfare" not in await researched_techs(session, defender.id):
        raise QuantumError("Requiere investigar: quantum_warfare.")
    inf.status, inf.disarm, inf.leaking, inf.disarmed_at = \
        "disarmed", "quantum", True, datetime.now(UTC)
    from app.services.journal import record
    await record(session, "quantum_disarm", defender.id, base_id=base_id, how="quantum", leak=True)
    await session.flush()
    return {"disarmed": "quantum", "leaking": True,
            "note": "fuga de info activa hasta poner un satélite inhibidor"}


async def has_active_inhibitor(session: AsyncSession, defender_id: int) -> bool:
    """¿El jugador tiene un satélite INHIBIDOR en órbita (corta la fuga)?"""
    rows = (await session.execute(select(SatelliteMission).where(
        SatelliteMission.owner_id == defender_id, SatelliteMission.kind == "inhibitor",
        SatelliteMission.status == "orbiting"))).scalars().all()
    return len(rows) > 0


async def leaked_base_ids(session: AsyncSession, attacker_id: int) -> list[int]:
    """Bases que le FILTRAN info a `attacker_id` (infección desactivada con tech y sin inhibidor del
    defensor). Se usa para darle al atacante un mapa 100% permanente de esas bases (SDD 61)."""
    if not get_settings().quantum_bomb_enabled:
        return []
    rows = (await session.execute(select(QuantumInfection).where(
        QuantumInfection.attacker_id == attacker_id, QuantumInfection.leaking.is_(True)
    ))).scalars().all()
    out = []
    for inf in rows:
        if not await has_active_inhibitor(session, inf.defender_id):
            out.append(inf.base_id)
    return out


async def infection_state(session: AsyncSession, player: Player) -> dict | None:
    """Estado de la infección para el snapshot /players/me (para que el jugador la vea y actúe)."""
    if not get_settings().quantum_bomb_enabled:
        return None
    inf = await active_infection(session, player.id)
    if inf is None:
        return None
    now = datetime.now(UTC)
    return {
        "base_id": inf.base_id,
        "attacker_id": inf.attacker_id,
        "penalty_pct": round(_penalty_at(inf.created_at, now) * 100, 1),
        "since": _aware(inf.created_at).isoformat(),
        "disarm_soldiers": get_settings().quantum_disarm_soldiers,
    }
