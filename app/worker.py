"""Periodic tick (run as a k8s CronJob or loop).

Two jobs each tick:
  1. NPC races take one action each (via app.services.npc).
  2. Every player's queues are advanced (builds, expeditions, training, mines).

`run_tick(session)` runs on a given session (so it's drivable over HTTP, e.g. the
admin endpoint and tests); `tick()` wraps it with its own SessionLocal for the CronJob.
"""
import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import SessionLocal, run_migrations
from app.models import Player
from app.services.economy import collect_mines, finalize_due_builds
from app.services.expedition import finalize_due_expeditions
from app.services.training import finalize_due_training


async def run_tick(session: AsyncSession) -> dict:
    settings = get_settings()
    npc_actions = 0
    npcs_count = 0

    if settings.npc_enabled:
        from app.services.npc import ensure_npcs, run_npc_turn

        await ensure_npcs(session)
        res = await session.execute(select(Player.id).where(Player.is_npc.is_(True)))
        npc_ids = list(res.scalars())
        npcs_count = len(npc_ids)
        for nid in npc_ids:
            # Re-fetch fresh each turn so a prior rollback can't leave stale objects.
            npc = await session.get(Player, nid)
            try:
                if await run_npc_turn(session, npc):
                    npc_actions += 1
                await session.commit()
            except Exception:
                await session.rollback()

    # Resolve fleet arrivals/returns across the whole world.
    from app.services.combat import process_missions

    missions = await process_missions(session)

    # Advance everyone's queues (humans included) for offline progress.
    res = await session.execute(select(Player).where(Player.race_key.is_not(None)))
    players = list(res.scalars())
    finalized = trained = expeditions = 0
    from app.services.research import finalize_due_research

    researched = 0
    for player in players:
        finalized += await finalize_due_builds(session, player)
        expeditions += await finalize_due_expeditions(session, player)
        await collect_mines(session, player)
        trained += await finalize_due_training(session, player)
        researched += await finalize_due_research(session, player)
    await session.commit()

    return {
        "players": len(players),
        "npcs": npcs_count,
        "npc_actions": npc_actions,
        "buildings_finalized": finalized,
        "units_trained": trained,
        "expeditions_finished": expeditions,
        "research_done": researched,
        **missions,
    }


async def tick() -> dict:
    async with SessionLocal() as session:
        return await run_tick(session)


async def _main() -> None:
    await asyncio.to_thread(run_migrations)
    result = await tick()
    print(f"tick complete: {result}")


if __name__ == "__main__":
    asyncio.run(_main())
