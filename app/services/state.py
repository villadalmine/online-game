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
from app.services.alliances import has_benefit
from app.services.alliances import members as alliance_members
from app.services.boons import active_boons
from app.services.combat import process_missions
from app.services.economy import collect_mines, finalize_due_builds, player_stocks
from app.services.energy import apply_regen
from app.services.expedition import finalize_due_expeditions
from app.services.notifications import unread_count
from app.services.physics import effective_energy_regen
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
    from app.services.espionage import process_spy_missions  # SDD 35
    await process_spy_missions(session, now, observer_id=player.id)
    # Eventos dinámicos (SDD 36): energía ×evento + soldados gratis (una vez por evento).
    from app.services.events import event_multiplier, grant_due_free_units
    regen = effective_energy_regen(player, settings) * await event_multiplier(
        session, "energy_regen", now
    )
    apply_regen(player, now, regen, settings.energy_max)
    await grant_due_free_units(session, player, now)
    await session.commit()


async def snapshot(session: AsyncSession, player: Player) -> PlayerStateOut:
    settings = get_settings()
    stocks = await player_stocks(session, player.id)
    # SDD 42: stock por planeta (para ver dónde está el material).
    from app.models import ResourceStock
    by_planet: dict[str, dict[str, float]] = {}
    for rs in (await session.execute(
        select(ResourceStock).where(ResourceStock.player_id == player.id)
    )).scalars():
        if rs.amount:
            by_planet.setdefault(rs.planet_key, {})[rs.mineral_key] = round(rs.amount, 2)
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
            BaseOut(id=base.id, name=base.name, planet_key=base.planet_key,
                    base_type=base.base_type, buildings=buildings)
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

    # Alliance: type + shared-vision alerts (attacks inbound on allies).
    alliance = await session.get(Alliance, player.alliance_id) if player.alliance_id else None
    ally_incoming: list[IncomingAttackOut] = []
    if alliance and await has_benefit(session, player.id, "shared_vision"):
        ally_ids = [m.id for m in await alliance_members(session, alliance.id) if m.id != player.id]
        if ally_ids:
            ares = await session.execute(
                select(AttackMission).where(
                    AttackMission.defender_id.in_(ally_ids),
                    AttackMission.status == "outbound",
                )
            )
            ally_incoming = [
                IncomingAttackOut(
                    id=m.id, target_base_id=m.target_base_id, arrives_at=m.arrives_at
                )
                for m in ares.scalars()
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
        stocks_by_planet=by_planet,
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
        alliance_name=alliance.name if alliance else None,
        alliance_type=alliance.type if alliance else None,
        alliance_incoming=ally_incoming,
        unread_notifications=await unread_count(session, player.id),
        protected_until=player.protected_until,
        season=await _current_season_out(session),
        galaxy_instance=await _galaxy_instance_out(session, player),
    )


async def _galaxy_instance_out(session, player):
    from app.schemas import GalaxyInstanceOut
    from app.services.galaxies import ensure_assigned

    inst = await ensure_assigned(session, player)  # backfill perezoso para cuentas legacy
    if inst is None:
        return None
    return GalaxyInstanceOut(
        id=inst.id, template_key=inst.template_key, seq=inst.seq, name=inst.name,
        capacity=inst.capacity, player_count=inst.player_count, status=inst.status,
    )


async def _current_season_out(session):
    from app.schemas import SeasonOut
    from app.services.seasons import current_season

    s = await current_season(session)
    if s is None:
        return None
    return SeasonOut(
        id=s.id, seq=s.seq, name=s.name, starts_at=s.starts_at, ends_at=s.ends_at, status=s.status
    )
