"""Research: spend minerals + energy to unlock a technology after a timer. Finished
techs grant a permanent effect multiplier (production/attack/defense) applied via
services/effects.py — same lazy-by-timestamp pattern as build/train."""
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Building, PlayerTech, ResearchOrder
from app.services.economy import (
    collect_mines,
    finalize_due_builds,
    get_or_create_stock,
    planet_stocks,
)
from app.services.energy import energy_shortfall_msg, spend_energy
from app.services.physics import effective_energy_max, effective_energy_regen


class ResearchError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def researched_techs(session: AsyncSession, player_id: int) -> set[str]:
    res = await session.execute(
        select(PlayerTech.tech_key).where(PlayerTech.player_id == player_id)
    )
    return set(res.scalars())


async def in_progress(session: AsyncSession, player_id: int) -> list[ResearchOrder]:
    res = await session.execute(
        select(ResearchOrder).where(
            ResearchOrder.player_id == player_id, ResearchOrder.status == "researching"
        )
    )
    return list(res.scalars())


async def finalize_due_research(session, player, now: datetime | None = None) -> int:
    from app.services.notifications import notify

    now = now or datetime.now(UTC)
    done = 0
    for order in await in_progress(session, player.id):
        if _aware(order.completes_at) <= now:
            session.add(PlayerTech(player_id=player.id, tech_key=order.tech_key))
            order.status = "done"
            await notify(
                session, player.id, "research_done",
                f"Investigacion completada: {order.tech_key}", {"tech": order.tech_key},
            )
            done += 1
    if done:
        from app.services.stats import bump
        await bump(session, player.id, research_completed=done)
    return done


async def _building_active(session: AsyncSession, player_id: int, building_key: str) -> bool:
    from app.models import Base_

    res = await session.execute(
        select(Building)
        .join(Base_, Building.base_id == Base_.id)
        .where(
            Base_.player_id == player_id,
            Building.building_key == building_key,
            Building.status == "active",
        )
    )
    return res.first() is not None


async def start_research(session: AsyncSession, player, tech_key: str) -> ResearchOrder:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)

    tech = content.technologies.get(tech_key)
    if tech is None:
        raise ResearchError(f"Tecnologia desconocida: {tech_key}")

    await finalize_due_builds(session, player, now)
    await collect_mines(session, player, now)
    await finalize_due_research(session, player, now)

    if tech_key in await researched_techs(session, player.id):
        raise ResearchError("Ya investigada.")
    if any(o.tech_key == tech_key for o in await in_progress(session, player.id)):
        raise ResearchError("Ya en progreso.")

    required = tech.get("requires")
    if required and not await _building_active(session, player.id, required):
        raise ResearchError(f"Requiere el edificio activo: {required}")
    done_techs = await researched_techs(session, player.id)
    rtech = tech.get("requires_tech")   # SDD 1: cadena de research — pide la tech previa
    if rtech and rtech not in done_techs:
        raise ResearchError(f"Requiere investigar antes: {rtech}")
    # SDD 63: capstones (p.ej. space_jump) piden VARIAS techs a la vez (todo el árbol endgame).
    for req in tech.get("requires_techs", []):
        if req not in done_techs:
            raise ResearchError(f"Requiere investigar antes: {req}")

    regen = effective_energy_regen(player, settings)
    need_e = tech.get("energy_cost", 0)
    if not spend_energy(player, need_e, now, regen, effective_energy_max(player, settings)):
        raise ResearchError(energy_shortfall_msg(need_e, player.energy, regen))

    cost = content.tech_cost_in_minerals(player.race_key, tech_key)
    here = await planet_stocks(session, player.id, player.planet_key)   # se investiga en casa
    for mineral, amount in cost.items():
        if here.get(mineral, 0.0) < amount:
            raise ResearchError(f"Falta {mineral} en {player.planet_key} (necesita {amount:g}).")
    for mineral, amount in cost.items():
        (await get_or_create_stock(session, player.id, mineral, player.planet_key)).amount -= amount

    order = ResearchOrder(
        player_id=player.id,
        tech_key=tech_key,
        status="researching",
        completes_at=now + timedelta(seconds=tech.get("research_seconds", 0)),
    )
    session.add(order)
    await session.flush()
    from app.services.journal import record
    await record(session, "research_started", player.id, tech=tech_key)
    return order
