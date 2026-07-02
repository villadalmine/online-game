"""Advance a player's lazy state (energy + production + build timers) and snapshot it."""
import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
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
from app.services.physics import effective_energy_max, effective_energy_regen
from app.services.research import finalize_due_research, in_progress, researched_techs
from app.services.training import finalize_due_training, player_units, units_by_base


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
    from app.services.strike import process_strikes  # SDD 49: salvas de misiles
    await process_strikes(session, now, player_id=player.id)
    from app.services.drones import advance_drones  # SDD 50: drones orbitando (drenan energía)
    await advance_drones(session, player, now)
    from app.services.satellites import advance_satellites  # SDD 61: satélites orbitando
    await advance_satellites(session, player, now)
    from app.services.bunkers import advance_bunker  # SDD 64: búnkeres subterráneos
    await advance_bunker(session, player, now)
    from app.services.espionage import process_spy_missions  # SDD 35
    await process_spy_missions(session, now, observer_id=player.id)
    from app.services.market import process_transport_missions  # SDD 42 Fase 2
    await process_transport_missions(session, now, player_id=player.id)
    from app.services.troops import process_moves  # SDD 62: traslados de tropas entre bases
    await process_moves(session, now, player_id=player.id)
    # Eventos dinámicos (SDD 36): energía ×evento + soldados gratis (una vez por evento).
    from app.services.events import event_multiplier, grant_due_free_units
    regen = effective_energy_regen(player, settings) * await event_multiplier(
        session, "energy_regen", now
    )
    apply_regen(player, now, regen, effective_energy_max(player, settings))
    await grant_due_free_units(session, player, now)
    # SDD 51: muestra del estado para los gráficos in-app (throttleada, lazy, sin cron).
    from app.services.analytics import sample_player
    await sample_player(session, player, now)
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
    units_per_base = await units_by_base(session, player.id)   # SDD 62: guarnición por base (UI)

    res = await session.execute(select(Base_).where(Base_.player_id == player.id))
    bases = list(res.scalars())
    base_ids = [b.id for b in bases]

    bases_out: list[BaseOut] = []
    all_buildings: list[Building] = []   # modelos (SDD 46/47: alojamiento + almacenamiento)
    base_info: dict[int, tuple] = {}
    for base in bases:
        bres = await session.execute(select(Building).where(Building.base_id == base.id))
        models = list(bres.scalars())
        all_buildings.extend(models)
        base_info[base.id] = (base.planet_key, base.base_type)
        buildings = [
            BuildingOut(
                id=b.id,
                building_key=b.building_key,
                level=b.level,
                status=b.status,
                production_mineral=b.production_mineral,
                completes_at=b.completes_at,
            )
            for b in models
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

    # SDD 46/47: alojamiento (housing) + minería (staffing) + almacenamiento (silos), derivados
    # del contenido data-driven para que el cliente y la IA vean el estado real.
    from app.content.registry import get_content
    from app.services.economy import mining_staffing, storage_caps_by_planet
    from app.services.housing import housing_report
    content = get_content()
    active_keys = [b.building_key for b in all_buildings if b.status == "active"]
    queued_units: dict[str, int] = {}
    for o in training_out:
        queued_units[o.unit_key] = queued_units.get(o.unit_key, 0) + o.quantity
    housing_block = housing_report(active_keys, units, queued_units)

    staffing_v, available_w, required_w = await mining_staffing(
        session, player.id, all_buildings, content
    )
    mining_block = {
        "staffing": round(staffing_v, 3),
        "available_workers": available_w,
        "required_workers": required_w,
        "enforced": settings.mining_staffing_enabled,
    }

    # SDD 62: con guarnición ON, minería y alojamiento se desglosan POR PLANETA (obreros/edificios
    # de cada planeta) → la "capacidad por planeta" del front. Con OFF quedan vacíos.
    mining_by_planet: dict[str, dict] = {}
    housing_by_planet: dict[str, dict] = {}
    troop_moves_out: list = []
    if settings.garrison_enabled:
        from app.schemas import TroopMoveOut
        from app.services.troops import active_moves
        troop_moves_out = [
            TroopMoveOut(id=m.id, from_base_id=m.from_base_id, to_base_id=m.to_base_id,
                         units=json.loads(m.units), status=m.status, arrives_at=m.arrives_at)
            for m in await active_moves(session, player.id)
        ]
        from app.services.housing import housing_capacity, housing_occupancy
        from app.services.production import staffing_ratio
        mining_power = content.units.get("worker", {}).get("mining_power", 1)
        planets = {pk for (pk, _bt) in base_info.values()}
        units_pp: dict[str, dict[str, int]] = {}
        for bid, u in units_per_base.items():
            pk = base_info.get(bid, (None,))[0]
            if pk is None:
                continue
            dst = units_pp.setdefault(pk, {})
            for uk, q in u.items():
                dst[uk] = dst.get(uk, 0) + q
        queued_pp: dict[str, dict[str, int]] = {}
        for o in training_out:
            pk = base_info.get(o.base_id, (None,))[0]
            if pk is None:
                continue
            queued_pp.setdefault(pk, {})[o.unit_key] = (
                queued_pp.setdefault(pk, {}).get(o.unit_key, 0) + o.quantity
            )
        for pk in planets:
            blds = [b for b in all_buildings if base_info.get(b.base_id, (None,))[0] == pk]
            akeys = [b.building_key for b in blds if b.status == "active"]
            required = sum(
                content.buildings[b.building_key].get("worker_slots", 0)
                for b in blds
                if b.status == "active"
                and content.buildings.get(b.building_key, {}).get("category") == "mine"
            )
            punits = units_pp.get(pk, {})
            available = punits.get("worker", 0) * mining_power
            ratio = staffing_ratio(available, required)
            floor = settings.mining_staffing_floor if required > 0 else 0.0
            mining_by_planet[pk] = {
                "staffing": round(max(floor, ratio), 3),
                "available_workers": float(available),
                "required_workers": float(required),
            }
            cap = housing_capacity(akeys)
            occ = housing_occupancy(punits, queued_pp.get(pk, {}))
            housing_by_planet[pk] = {
                d: {"capacity": cap.get(d, 0), "occupancy": occ.get(d, 0),
                    "free": cap.get(d, 0) - occ.get(d, 0)}
                for d in sorted(set(cap) | set(occ)) if cap.get(d, 0) or occ.get(d, 0)
            }

    storage_block: dict = {}
    if settings.storage_caps_enabled:
        caps = storage_caps_by_planet(
            content, all_buildings, base_info,
            settings.base_storage_per_mineral, content.minerals.keys(),
        )
        for planet, mineral_caps in caps.items():
            cell: dict[str, dict] = {}
            pstock = by_planet.get(planet, {})
            for mineral, cap in mineral_caps.items():
                st = float(pstock.get(mineral, 0.0))
                if st <= 0:
                    continue   # solo listamos minerales que realmente tenés (menos ruido)
                cell[mineral] = {
                    "cap": round(cap, 1), "stock": round(st, 1),
                    "free": round(cap - st, 1), "overflowing": st >= cap,
                }
            if cell:
                storage_block[planet] = cell

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

    # SDD 55 §3.3: cuántos ataques recibí en las últimas 24 h (misma ventana que el tope de
    # combat.py) para mostrar "ataques recibidos hoy X/Y" en el front.
    day_start = datetime.now(UTC) - timedelta(seconds=86400)
    attacks_received_today = (await session.execute(
        select(func.count(AttackMission.id)).where(
            AttackMission.defender_id == player.id,
            AttackMission.created_at >= day_start,
        )
    )).scalar_one()

    # SDD 49: salvas de misiles propias en vuelo.
    from app.models import StrikeMission
    from app.schemas import IncomingStrikeOut, StrikeMissionOut
    strikes_out = [
        StrikeMissionOut(
            id=m.id, launcher_base_id=m.launcher_base_id, target_base_id=m.target_base_id,
            force=json.loads(m.force), status=m.status, arrives_at=m.arrives_at,
            tribute=json.loads(m.tribute) if m.tribute else None,   # SDD 67
        )
        for m in (await session.execute(
            select(StrikeMission).where(
                StrikeMission.attacker_id == player.id, StrikeMission.status == "outbound"
            )
        )).scalars()
    ]
    # SDD 67: salvas ENTRANTES (para negociar el nuclear). can_offer si tenés gobierno + diplomacia.
    from app.services.research import researched_techs as _rt
    _can_offer = None
    strikes_incoming = []
    for m in (await session.execute(
        select(StrikeMission).where(
            StrikeMission.defender_id == player.id, StrikeMission.status == "outbound"
        )
    )).scalars():
        is_nuke = "nuclear_missile" in json.loads(m.force)
        if is_nuke and _can_offer is None:
            has_gov = (await session.execute(
                select(Building.id).join(Base_, Building.base_id == Base_.id).where(
                    Base_.player_id == player.id, Building.building_key == "government",
                    Building.status == "active"))).first() is not None
            _can_offer = has_gov and "diplomacy" in await _rt(session, player.id)
        strikes_incoming.append(IncomingStrikeOut(
            id=m.id, target_base_id=m.target_base_id, arrives_at=m.arrives_at, is_nuclear=is_nuke,
            tribute=json.loads(m.tribute) if m.tribute else None,
            can_offer=bool(is_nuke and _can_offer)))
    # SDD 50: escuadrones de drones orbitando + intel en vivo.
    from app.schemas import DroneSquadronOut
    from app.services.drones import squadrons_state
    drones_raw, intel_live = await squadrons_state(session, player)
    drones_out = [DroneSquadronOut(**d) for d in drones_raw]
    # SDD 61: satélites propios + mapas de enemigos (% descubierto + bases/unidades).
    from app.services.satellites import satellites_state
    satellites_out, enemy_maps = await satellites_state(session, player)
    from app.services.bunkers import bunker_state  # SDD 64
    bunkers_out = await bunker_state(session, player)

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

    # SDD 42/35: transportes y espías en curso (para el panel de Colas con su ETA).
    import json as _json

    from app.models import SpyMission, TransportMission
    from app.schemas import SpyMissionOut, TransportMissionOut
    transports_out = [
        TransportMissionOut(
            id=m.id, from_planet=m.from_planet, to_planet=m.to_planet,
            cargo=_json.loads(m.cargo), escort=_json.loads(m.escort or "{}"),
            ships=m.ships, status=m.status, arrives_at=m.arrives_at,
        )
        for m in (await session.execute(
            select(TransportMission).where(
                TransportMission.player_id == player.id, TransportMission.status == "outbound"
            )
        )).scalars()
    ]
    spy_out = [
        SpyMissionOut(id=m.id, target_base_id=m.target_base_id, status=m.status,
                      arrives_at=m.arrives_at, returns_at=m.returns_at)
        for m in (await session.execute(
            select(SpyMission).where(
                SpyMission.observer_id == player.id,
                SpyMission.status.in_(("outbound", "returning")),
            )
        )).scalars()
    ]

    # SDD 14: admin por flag en DB O por ADMIN_EMAIL (igual que get_current_admin) → setear el env
    # alcanza para que una cuenta existente vea/use el panel sin tocar la base.
    _admin_email = settings.admin_email.strip().lower()
    is_admin = player.is_admin or (
        bool(_admin_email) and (player.email or "").lower() == _admin_email
    )
    return PlayerStateOut(
        id=player.id,
        username=player.username,
        is_admin=is_admin,
        account_status=player.status,
        galaxy_key=player.galaxy_key,
        planet_key=player.planet_key,
        race_key=player.race_key,
        energy=round(player.energy, 2),
        energy_max=round(effective_energy_max(player, settings), 2),
        stocks={k: round(v, 2) for k, v in stocks.items()},
        stocks_by_planet=by_planet,
        units=units,
        units_by_base={str(k): v for k, v in units_per_base.items()},
        bases=bases_out,
        training=training_out,
        expeditions=expeditions_out,
        boons=boons_out,
        missions_outgoing=outgoing,
        missions_incoming=incoming,
        attacks_received_today=attacks_received_today,
        max_incoming_attacks_per_day=settings.max_incoming_attacks_per_day,
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
        transports=transports_out,
        spy_missions=spy_out,
        mining=mining_block,
        mining_by_planet=mining_by_planet,
        housing_by_planet=housing_by_planet,
        troop_moves=troop_moves_out,
        storage=storage_block,
        housing=housing_block,
        strikes=strikes_out,
        strikes_incoming=strikes_incoming,
        drones=drones_out,
        intel_live=intel_live,
        satellites=satellites_out,
        enemy_maps=enemy_maps,
        bunkers=bunkers_out,
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
