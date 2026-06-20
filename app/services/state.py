"""Advance a player's lazy state (energy + production + build timers) and snapshot it."""
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import (
    Alliance,
    AttackMission,
    Base_,
    Building,
    ExpeditionOrder,
    Player,
    TrainingOrder,
)
from app.schemas import (
    ActiveBoonOut,
    AttackMissionOut,
    BaseOut,
    BuildingOut,
    ExpeditionOrderOut,
    IncomingAttackOut,
    PlayerStateOut,
    ResearchOrderOut,
    TrainingOrderOut,
)
from app.services.boons import active_boons
from app.services.combat import process_missions
from app.services.economy import collect_mines, finalize_due_builds, player_stocks
from app.services.energy import apply_regen
from app.services.expedition import finalize_due_expeditions
from app.services.notifications import unread_count
from app.services.research import finalize_due_research, in_progress, researched_techs
from app.services.training import finalize_due_training, player_units


async def advance(session: AsyncSession, player: Player) -> None:
    """Bring everything up to 'now' — the core 'advance on access' step."""
    settings = get_settings()
    now = datetime.now(UTC)
    await finalize_due_builds(session, player, now)
    # expeditions before mines so a freshly-granted production boon applies immediately
    await finalize_due_expeditions(session, player, now)
    await collect_mines(session, player, now)
    await finalize_due_training(session, player, now)
    await finalize_due_research(session, player, now)
    # resolve fleet arrivals/returns involving this player
    await process_missions(session, now, player_id=player.id)
    apply_regen(player, now, settings.energy_regen_per_hour, settings.energy_max)
    await session.commit()


async def snapshot(session: AsyncSession, player: Player) -> PlayerStateOut:
    settings = get_settings()
    stocks = await player_stocks(session, player.id)
    units = await player_units(session, player.id)

    res = await session.execute(select(Base_).where(Base_.player_id == player.id))
    bases = list(res.scalars())
    base_ids = [b.id for b in bases]

    bases_out: list[BaseOut] = []
    for base in bases:
        bres = await session.execute(select(Building).where(Building.base_id == base.id))
        buildings = [
            BuildingOut(
                id=b.id,
                building_key=b.building_key,
                level=b.level,
                status=b.status,
                production_mineral=b.production_mineral,
                completes_at=b.completes_at,
            )
            for b in bres.scalars()
        ]
        bases_out.append(
            BaseOut(id=base.id, name=base.name, planet_key=base.planet_key, buildings=buildings)
        )

    training_out: list[TrainingOrderOut] = []
    if base_ids:
        tres = await session.execute(
            select(TrainingOrder).where(
                TrainingOrder.base_id.in_(base_ids), TrainingOrder.status == "training"
            )
        )
        training_out = [
            TrainingOrderOut(
                id=o.id,
                base_id=o.base_id,
                unit_key=o.unit_key,
                quantity=o.quantity,
                completes_at=o.completes_at,
            )
            for o in tres.scalars()
        ]

    eres = await session.execute(
        select(ExpeditionOrder).where(
            ExpeditionOrder.player_id == player.id, ExpeditionOrder.status == "traveling"
        )
    )
    expeditions_out = [
        ExpeditionOrderOut(id=o.id, moon_key=o.moon_key, completes_at=o.completes_at)
        for o in eres.scalars()
    ]

    boons_out = [
        ActiveBoonOut(
            source_moon=b.source_moon,
            effect=b.effect,
            magnitude=b.magnitude,
            expires_at=b.expires_at,
        )
        for b in await active_boons(session, player.id)
    ]

    ores = await session.execute(
        select(AttackMission).where(
            AttackMission.attacker_id == player.id,
            AttackMission.status.in_(("outbound", "returning")),
        )
    )
    outgoing = [
        AttackMissionOut(
            id=m.id,
            target_base_id=m.target_base_id,
            force=json.loads(m.force),
            status=m.status,
            arrives_at=m.arrives_at,
            returns_at=m.returns_at,
        )
        for m in ores.scalars()
    ]
    ires = await session.execute(
        select(AttackMission).where(
            AttackMission.defender_id == player.id, AttackMission.status == "outbound"
        )
    )
    incoming = [
        IncomingAttackOut(id=m.id, target_base_id=m.target_base_id, arrives_at=m.arrives_at)
        for m in ires.scalars()
    ]

    return PlayerStateOut(
        id=player.id,
        username=player.username,
        galaxy_key=player.galaxy_key,
        planet_key=player.planet_key,
        race_key=player.race_key,
        energy=round(player.energy, 2),
        energy_max=settings.energy_max,
        stocks={k: round(v, 2) for k, v in stocks.items()},
        units=units,
        bases=bases_out,
        training=training_out,
        expeditions=expeditions_out,
        boons=boons_out,
        missions_outgoing=outgoing,
        missions_incoming=incoming,
        technologies=sorted(await researched_techs(session, player.id)),
        research=[
            ResearchOrderOut(id=o.id, tech_key=o.tech_key, completes_at=o.completes_at)
            for o in await in_progress(session, player.id)
        ],
        alliance_id=player.alliance_id,
        alliance_name=(
            (await session.get(Alliance, player.alliance_id)).name
            if player.alliance_id else None
        ),
        unread_notifications=await unread_count(session, player.id),
    )
