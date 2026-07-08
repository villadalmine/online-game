"""SDD 61: satélites. `survey` orbita tu planeta (vigilancia propia); `spy` orbita el de un enemigo
y acumula `discovered_pct` (mapa de sus bases + unidades). Lazy by timestamp como los drones:
al leer, `advance_satellites` aplica las órbitas transcurridas (sube el %, drena energía, los bajan
los drones del defensor, deorbita sin energía). Todo detrás de `satellites_enabled`.

Mapeo: 1 satélite sin inhibidores → 100% en `sat_scan_hours_solo` h; N satélites suman (lineal). Los
inhibidores del defensor topean el % (`coverage`). Escudos (sat_shield_mk1..3) bajan la destrucción
por drones pero drenan más energía (vida útil más corta). Ver docs/sdd-satellites-recon.md.
"""
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player, SatelliteMission, UnitStock
from app.services.research import researched_techs
from app.services.training import player_units

SHIELD_RESIST = [1, 2, 4, 8]   # grado 0/1/2/3 → resistencia a disparos de drones


class SatelliteError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


async def _shield_grade(session: AsyncSession, player_id: int) -> int:
    techs = await researched_techs(session, player_id)
    if "sat_shield_mk3" in techs:
        return 3
    if "sat_shield_mk2" in techs:
        return 2
    if "sat_shield_mk1" in techs:
        return 1
    return 0


async def _coverage(session: AsyncSession, target_id: int, content, settings) -> float:
    """Cobertura de inhibidores del defensor: min(1, Σinhibit_power / nº edificios). Con cobertura
    total NO se puede mapear. Más edificios ⇒ necesitás más inhibidores."""
    rows = (await session.execute(
        select(Building.building_key).join(Base_, Building.base_id == Base_.id).where(
            Base_.player_id == target_id, Building.status == "active")
    )).scalars().all()
    n_buildings = len(rows)
    if n_buildings == 0:
        return 0.0
    jam = 0
    for bk in rows:
        if bk == "signal_inhibitor":
            jam += content.buildings.get(bk, {}).get("inhibit_power", settings.sat_inhibitor_jam)
    return min(1.0, jam / n_buildings)


async def _defender_drones(session: AsyncSession, target_id: int) -> int:
    """Drones del defensor (lo que baja satélites al pasar)."""
    content = get_content()
    units = await player_units(session, target_id)
    return sum(q for k, q in units.items() if k in content.drones)


async def launch(
    session: AsyncSession, player: Player, unit_key: str, target_id: int | None = None
) -> SatelliteMission:
    settings = get_settings()
    if not settings.satellites_enabled:
        raise SatelliteError("Los satélites están desactivados.")
    content = get_content()
    spec = content.satellites.get(unit_key)
    if spec is None:
        raise SatelliteError(f"Satélite desconocido: {unit_key}")
    kind = spec.get("kind", "spy")
    if kind in ("survey", "inhibitor"):   # SDD 87: el inhibidor orbita TU planeta (corta la fuga)
        target_id = None
        target_planet = player.planet_key or ""
    else:
        if not target_id:
            raise SatelliteError("Elegí un objetivo para el satélite espía.")
        target = await session.get(Player, target_id)
        if target is None or target.id == player.id:
            raise SatelliteError("Objetivo inválido.")
        target_planet = target.planet_key or ""
    # consumir 1 satélite entrenado del stock (cualquier base / global).
    row = (await session.execute(
        select(UnitStock).where(
            UnitStock.player_id == player.id, UnitStock.unit_key == unit_key,
            UnitStock.quantity > 0,
        ).order_by(UnitStock.base_id)
    )).scalars().first()
    if row is None:
        raise SatelliteError(f"No tenés {unit_key} (entrenalo en el cosmódromo).")
    row.quantity -= 1
    now = datetime.now(UTC)
    sat = SatelliteMission(
        owner_id=player.id, target_id=target_id, unit_key=unit_key, kind=kind,
        target_planet=target_planet, shield_grade=await _shield_grade(session, player.id),
        energy=float(spec.get("sat_energy", 112)), discovered_pct=0.0, status="orbiting",
        last_tick_at=now, created_at=now,
    )
    session.add(sat)
    await session.flush()
    return sat


async def advance_satellites(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> None:
    settings = get_settings()
    if not settings.satellites_enabled:
        return
    now = now or datetime.now(UTC)
    content = get_content()
    sats = (await session.execute(
        select(SatelliteMission).where(
            SatelliteMission.owner_id == player.id, SatelliteMission.status == "orbiting")
    )).scalars().all()
    if not sats:
        return
    orbit_s = max(1, settings.sat_orbit_minutes * 60)
    orbit_h = settings.sat_orbit_minutes / 60.0
    rate = 100.0 / settings.sat_scan_hours_solo            # %/h por satélite (sin inhibidores)
    # cache por objetivo (coverage + drones) para no recomputar por satélite
    cov_cache: dict[int, float] = {}
    drn_cache: dict[int, int] = {}
    for s in sats:
        elapsed = (now - _aware(s.last_tick_at)).total_seconds()
        orbits = int(elapsed // orbit_s)
        if orbits <= 0:
            continue
        s.last_tick_at = datetime.fromtimestamp(
            _aware(s.last_tick_at).timestamp() + orbits * orbit_s, tz=UTC)
        # drenaje de energía (más escudo ⇒ más drenaje ⇒ menos vida útil)
        s.energy -= orbits * (1.0 + settings.sat_drain_per_grade * s.shield_grade)
        if s.energy <= 0:
            s.status = "deorbited"
            continue
        if s.kind == "spy" and s.target_id:
            if s.target_id not in cov_cache:
                cov_cache[s.target_id] = await _coverage(session, s.target_id, content, settings)
                drn_cache[s.target_id] = await _defender_drones(session, s.target_id)
            coverage = cov_cache[s.target_id]
            drones = drn_cache[s.target_id]
            # destrucción acumulada por drones (determinista): hazard total desde el lanzamiento.
            total_orbits = (now - _aware(s.created_at)).total_seconds() / orbit_s
            hazard = settings.sat_base_loss * drones / SHIELD_RESIST[s.shield_grade]
            if hazard * total_orbits >= 1.0:
                s.status = "lost"
                continue
            cap = 100.0 * (1.0 - coverage)
            gain = rate * (1.0 - coverage) * orbits * orbit_h
            s.discovered_pct = min(cap, s.discovered_pct + gain)


async def recall(session: AsyncSession, player: Player, sat_id: int) -> SatelliteMission:
    sat = await session.get(SatelliteMission, sat_id)
    if sat is None or sat.owner_id != player.id:
        raise SatelliteError("Satélite no encontrado.")
    if sat.status != "orbiting":
        raise SatelliteError("Ese satélite ya no está en órbita.")
    # vuelve al stock (se recupera la unidad).
    from app.services.training import get_or_create_unit_stock
    (await get_or_create_unit_stock(session, player.id, sat.unit_key)).quantity += 1
    sat.status = "deorbited"
    await session.flush()
    return sat


async def satellites_state(session: AsyncSession, player: Player) -> tuple[list[dict], dict]:
    """(lista de satélites propios, enemy_maps). enemy_maps[target_id] = {pct, bases:[{base_id,
    planet, units?}]}. El % por enemigo suma los spy sats vivos (lineal, capado por coverage); las
    unidades por base se revelan al llegar a 100%."""
    settings = get_settings()
    if not settings.satellites_enabled:
        return [], {}
    sats = (await session.execute(
        select(SatelliteMission).where(
            SatelliteMission.owner_id == player.id, SatelliteMission.status == "orbiting")
    )).scalars().all()
    out = [
        {"id": s.id, "unit_key": s.unit_key, "kind": s.kind, "target_id": s.target_id,
         "target_planet": s.target_planet, "shield_grade": s.shield_grade,
         "energy": round(s.energy, 1), "discovered_pct": round(s.discovered_pct, 1)}
        for s in sats
    ]
    # agregado por enemigo (suma de los spy sats sobre ese objetivo)
    maps: dict[str, dict] = {}
    by_target: dict[int, float] = {}
    for s in sats:
        if s.kind == "spy" and s.target_id:
            by_target[s.target_id] = by_target.get(s.target_id, 0.0) + s.discovered_pct
    from app.services.training import units_at_base
    for tid, pct_sum in by_target.items():
        pct = round(min(100.0, pct_sum), 1)
        bres = (await session.execute(select(Base_).where(Base_.player_id == tid))).scalars().all()
        bases = []
        for b in bres:
            cell = {"base_id": b.id, "planet": b.planet_key}
            if pct >= 100.0:   # mapa completo → se ven las unidades por base
                cell["units"] = await units_at_base(session, tid, b.id)
            bases.append(cell)
        maps[str(tid)] = {"pct": pct, "bases": bases}
    # SDD 87: bases que le FILTRAN info a este jugador (bomba cuántica desactivada con tech y sin
    # satélite inhibidor del defensor) → mapa 100% permanente de esas bases, sin gastar satélites.
    from app.services.quantum import leaked_base_ids
    for bid in await leaked_base_ids(session, player.id):
        b = await session.get(Base_, bid)
        if b is None:
            continue
        entry = maps.setdefault(str(b.player_id), {"pct": 100.0, "bases": []})
        entry["pct"] = 100.0
        if not any(c["base_id"] == bid for c in entry["bases"]):
            entry["bases"].append({"base_id": bid, "planet": b.planet_key, "leaked": True,
                                   "units": await units_at_base(session, b.player_id, bid)})
    return out, maps
