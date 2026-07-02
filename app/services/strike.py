"""SDD 49 — Lanzadera de misiles: guerra de "golpe" intra-planeta.

Una **salva** = {misil: cantidad} disparada desde una `launcher` activa a una base enemiga del
MISMO planeta. `simulate_strike()` es puro/determinista (testeable sin DB): reparte la capacidad
antimisil del defensor sobre los misiles entrantes (los baratos/fáciles primero); los que sobran
impactan. El daño que impacta DESTRUYE edificios de la base objetivo (defensivos primero; el
nuclear, de área, también los no defensivos) → ablanda una base antes de un ataque de flota
(SDD 13) o de drones (SDD 50). El misil se consume al lanzarse; no vuelve.

Ver docs/sdd-missile-launcher.md.
"""
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, CombatLog, Player, StrikeMission
from app.services.combat import travel_seconds
from app.services.energy import spend_energy
from app.services.notifications import notify
from app.services.physics import effective_energy_max, effective_energy_regen


class StrikeError(Exception):
    pass


async def offer_tribute(
    session: AsyncSession, defender: Player, mission_id: int,
    minerals: dict[str, float], energy: float,
) -> StrikeMission:
    """SDD 67: el DEFENSOR de una salva nuclear entrante ofrece tributo para que el atacante la
    cancele. Requiere `government` activo + `diplomacy` y tener los recursos ofrecidos."""
    mission = await session.get(StrikeMission, mission_id)
    if mission is None or mission.defender_id != defender.id or mission.status != "outbound":
        raise StrikeError("Salva no encontrada.")
    if "nuclear_missile" not in json.loads(mission.force):
        raise StrikeError("Solo se puede negociar un misil nuclear.")
    if not await _has_active(session, None, "government", player_id=defender.id):
        raise StrikeError("Necesitás un Edificio de gobierno activo.")
    from app.services.research import researched_techs
    if "diplomacy" not in await researched_techs(session, defender.id):
        raise StrikeError("Requiere investigar: diplomacy.")
    minerals = {k: float(v) for k, v in (minerals or {}).items() if v and float(v) > 0}
    energy = max(0.0, float(energy or 0))
    if not minerals and energy <= 0:
        raise StrikeError("Ofrecé algo (minerales y/o energía).")
    from app.services.economy import planet_stocks
    here = await planet_stocks(session, defender.id, defender.planet_key)
    for m, v in minerals.items():
        if here.get(m, 0.0) < v:
            raise StrikeError(f"No tenés {v:g} de {m} para ofrecer.")
    mission.tribute = json.dumps({"minerals": minerals, "energy": energy})
    await notify(session, mission.attacker_id, "tribute_offered",
                 f"{defender.username} ofrece tributo para cancelar tu misil nuclear",
                 {"mission_id": mission.id, "minerals": minerals, "energy": energy})
    await session.flush()
    return mission


async def accept_tribute(session: AsyncSession, attacker: Player, mission_id: int) -> dict:
    """SDD 67: el ATACANTE acepta el tributo → transfiere recursos y CANCELA el misil."""
    mission = await session.get(StrikeMission, mission_id)
    if mission is None or mission.attacker_id != attacker.id or mission.status != "outbound":
        raise StrikeError("Salva no encontrada.")
    if not mission.tribute:
        raise StrikeError("No hay tributo ofrecido.")
    offer = json.loads(mission.tribute)
    defender = await session.get(Player, mission.defender_id)
    from app.services.economy import get_or_create_stock, planet_stocks
    here = await planet_stocks(session, defender.id, defender.planet_key)
    minerals = offer.get("minerals", {})
    for m, v in minerals.items():
        if here.get(m, 0.0) < v:
            raise StrikeError("El defensor ya no tiene los recursos ofrecidos.")
    for m, v in minerals.items():   # defensor natal → atacante natal
        (await get_or_create_stock(session, defender.id, m, defender.planet_key)).amount -= v
        (await get_or_create_stock(session, attacker.id, m, attacker.planet_key)).amount += v
    settings = get_settings()
    now = datetime.now(UTC)
    if offer.get("energy"):
        from app.services.combat import _advance_economy
        await _advance_economy(session, attacker, now)
        attacker.energy = min(effective_energy_max(attacker, settings),
                              attacker.energy + float(offer["energy"]))
        attacker.energy_updated_at = now
    mission.status = "cancelled"
    mission.details = json.dumps({"cancelled_by_tribute": offer})
    await notify(session, defender.id, "tribute_accepted",
                 "Tu tributo fue aceptado: el misil nuclear se canceló", offer)
    from app.services.journal import record
    await record(session, "nuclear_cancelled", attacker.id, defender_id=defender.id, tribute=offer)
    await session.flush()
    return {"cancelled": True, "tribute": offer}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class StrikeResult:
    impacted: dict[str, int] = field(default_factory=dict)
    intercepted: dict[str, int] = field(default_factory=dict)
    damage: float = 0.0
    area: bool = False   # True si algún misil de área (nuclear) impactó


def simulate_strike(
    force: dict[str, int], intercept_capacity: float, atk_mult: float = 1.0
) -> StrikeResult:
    """Resolución pura de una salva. La capacidad antimisil se gasta sobre los misiles entrantes
    en orden ascendente de `intercept_cost` (primero los baratos/fáciles). Un misil es interceptado
    si queda capacidad ≥ su `intercept_cost`; si no, impacta. `damage` = Σ power de los que impactan
    × atk_mult. Consecuencia: un enjambre de sónicos satura; el nuclear casi no se frena."""
    content = get_content()
    # expandir a misiles individuales (key, power, intercept_cost, area)
    missiles: list[tuple[str, float, float, bool]] = []
    for key, qty in force.items():
        spec = content.units.get(key, {})
        power = float(spec.get("power", 0))
        ic = float(spec.get("intercept_cost", 1))
        area = bool(spec.get("area", False))
        for _ in range(int(qty)):
            missiles.append((key, power, ic, area))
    missiles.sort(key=lambda m: m[2])  # baratos de interceptar primero

    remaining = float(intercept_capacity)
    impacted: dict[str, int] = {}
    intercepted: dict[str, int] = {}
    damage = 0.0
    area_hit = False
    for key, power, ic, area in missiles:
        if remaining >= ic:
            remaining -= ic
            intercepted[key] = intercepted.get(key, 0) + 1
        else:
            impacted[key] = impacted.get(key, 0) + 1
            damage += power
            area_hit = area_hit or area
    return StrikeResult(impacted, intercepted, round(damage * atk_mult, 2), area_hit)


async def _active_buildings(session: AsyncSession, base_id: int) -> list[Building]:
    res = await session.execute(
        select(Building).where(Building.base_id == base_id, Building.status == "active")
    )
    return list(res.scalars())


def _is_defensive(building_key: str) -> bool:
    b = get_content().buildings.get(building_key, {})
    return bool(b.get("defense_power") or b.get("counter_power") or b.get("intercept_power"))


def _building_hp(building_key: str) -> float:
    b = get_content().buildings.get(building_key, {})
    return float(b.get("hp", get_settings().building_strike_hp))


async def intercept_capacity(session: AsyncSession, defender: Player, base_id: int) -> float:
    """Capacidad antimisil de una base = Σ intercept_power de torretas activas × defense_mult."""
    content = get_content()
    from app.services.effects import multiplier as effect_mult
    cap = sum(
        content.buildings.get(b.building_key, {}).get("intercept_power", 0)
        for b in await _active_buildings(session, base_id)
    )
    return cap * await effect_mult(session, defender.id, "defense")


async def start_strike(
    session: AsyncSession, attacker: Player, launcher_base_id: int,
    target_base_id: int, force: dict[str, int],
) -> StrikeMission:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)
    if not settings.strike_enabled:
        raise StrikeError("Los misiles están deshabilitados en este mundo.")

    launcher_base = await session.get(Base_, launcher_base_id)
    if launcher_base is None or launcher_base.player_id != attacker.id:
        raise StrikeError("Lanzadera no encontrada.")
    if not await _has_active(session, launcher_base_id, "launcher"):
        raise StrikeError("Esa base no tiene una lanzadera activa.")

    target = await session.get(Base_, target_base_id)
    if target is None:
        raise StrikeError("Base objetivo no encontrada.")
    if target.player_id == attacker.id:
        raise StrikeError("No puedes atacar tu propia base.")
    # SDD 49: intra-planeta — el objetivo debe estar en el mismo planeta que la lanzadera.
    if target.planet_key != launcher_base.planet_key:
        raise StrikeError("Los misiles no salen del planeta; usá una flota.")

    defender = await session.get(Player, target.player_id)
    if attacker.alliance_id is not None and attacker.alliance_id == defender.alliance_id:
        raise StrikeError("No puedes atacar a un aliado.")
    if not defender.is_npc and defender.protected_until is not None and \
            _aware(defender.protected_until) > now:
        raise StrikeError("Ese jugador está bajo protección de novato.")

    force = {k: int(q) for k, q in force.items() if q and int(q) > 0}
    if not force:
        raise StrikeError("Debes lanzar al menos un misil.")
    for key in force:
        spec = content.units.get(key)
        if spec is None or spec.get("domain") != "ordnance":
            raise StrikeError(f"No es un misil: {key}")
        rtech = spec.get("requires_tech")
        if rtech:
            from app.services.research import researched_techs
            if rtech not in await researched_techs(session, attacker.id):
                raise StrikeError(f"Requiere investigar: {rtech}")

    # economía al día + chequear stock de misiles
    from app.services.combat import _advance_economy
    await _advance_economy(session, attacker, now)
    from app.services.training import get_or_create_unit_stock, player_units
    have = await player_units(session, attacker.id)
    for key, qty in force.items():
        if have.get(key, 0) < qty:
            raise StrikeError(f"No tenés suficientes {key} (tenés {have.get(key, 0)}).")

    launch_energy = content.buildings["launcher"].get("launch_energy", 0)
    if not spend_energy(
        attacker, launch_energy, now,
        effective_energy_regen(attacker, settings), effective_energy_max(attacker, settings),
    ):
        raise StrikeError("Energía insuficiente para lanzar.")

    for key, qty in force.items():
        (await get_or_create_unit_stock(session, attacker.id, key)).quantity -= qty

    # SDD 67: una salva con NUCLEAR tarda 24 h (ventana de negociación diplomática); no hay recall.
    travel = travel_seconds(launcher_base.planet_key, target.planet_key)
    if "nuclear_missile" in force:
        travel = max(travel, settings.nuclear_travel_seconds)
    mission = StrikeMission(
        attacker_id=attacker.id, defender_id=defender.id,
        launcher_base_id=launcher_base_id, target_base_id=target_base_id,
        force=json.dumps(force), status="outbound",
        arrives_at=now + timedelta(seconds=travel),
    )
    session.add(mission)
    await session.flush()
    await notify(
        session, defender.id, "incoming_strike",
        f"Misiles entrantes a tu base {target_base_id}",
        {"target_base_id": target_base_id, "arrives_at": mission.arrives_at.isoformat()},
    )
    from app.services.journal import record
    await record(session, "strike_launched", attacker.id,
                 defender_id=defender.id, target_base_id=target_base_id, force=force)
    return mission


async def _has_active(
    session: AsyncSession, base_id: int | None, building_key: str, player_id: int | None = None
) -> bool:
    q = select(Building).where(
        Building.building_key == building_key, Building.status == "active")
    if player_id is not None:   # SDD 67: ¿el jugador tiene ESTE edificio activo en alguna base?
        q = q.join(Base_, Building.base_id == Base_.id).where(Base_.player_id == player_id)
    else:
        q = q.where(Building.base_id == base_id)
    return (await session.execute(q)).first() is not None


async def _resolve_strike(session: AsyncSession, mission: StrikeMission, now: datetime) -> None:
    content = get_content()
    from app.services.effects import multiplier as effect_mult
    attacker = await session.get(Player, mission.attacker_id)
    defender = await session.get(Player, mission.defender_id)
    force = json.loads(mission.force)

    cap = await intercept_capacity(session, defender, mission.target_base_id)
    atk_mult = content.races[attacker.race_key]["bonuses"].get("military_attack", 1.0)
    atk_mult *= await effect_mult(session, attacker.id, "attack", now)
    result = simulate_strike(force, cap, atk_mult)

    # Aplicar daño: destruir edificios de la base objetivo. Defensivos primero; si hubo impacto de
    # área (nuclear), también se dañan los no defensivos. La HQ nunca se destruye.
    targets = [b for b in await _active_buildings(session, mission.target_base_id)
               if b.building_key != "headquarters"]
    targets.sort(key=lambda b: (0 if _is_defensive(b.building_key) else 1, b.id))
    pool = result.damage
    destroyed: list[str] = []
    for b in targets:
        if not result.area and not _is_defensive(b.building_key):
            break  # sin área solo derriba defensas
        hp = _building_hp(b.building_key)
        if pool >= hp:
            pool -= hp
            destroyed.append(b.building_key)
            await session.delete(b)
        else:
            break

    # Fallout (SDD 49): un nuclear que impacta deja −producción temporal al defensor.
    if result.area and result.impacted:
        from app.models import ActiveBoon
        session.add(ActiveBoon(
            player_id=defender.id, source_moon="fallout", effect="production",
            magnitude=0.8, expires_at=now + timedelta(hours=6),
        ))

    details = {
        "impacted": result.impacted, "intercepted": result.intercepted,
        "damage": result.damage, "destroyed": destroyed,
    }
    session.add(CombatLog(
        attacker_id=attacker.id, defender_id=defender.id,
        target_base_id=mission.target_base_id, outcome="strike",
        details=json.dumps(details),
    ))
    await notify(
        session, attacker.id, "strike_result",
        f"Salva en base {mission.target_base_id}: {len(destroyed)} edificios destruidos",
        details,
    )
    await notify(
        session, defender.id, "struck",
        f"Te lanzaron misiles (base {mission.target_base_id})",
        {"intercepted": result.intercepted, "destroyed": destroyed},
    )
    from app.services.journal import record
    await record(session, "strike_resolved", attacker.id, defender_id=defender.id,
                 target_base_id=mission.target_base_id, **details)
    mission.status = "done"
    mission.details = json.dumps(details)


async def process_strikes(
    session: AsyncSession, now: datetime | None = None, player_id: int | None = None
) -> dict:
    """Resolver salvas que llegaron. Scope a un jugador (advance perezoso) o todos (tick)."""
    now = now or datetime.now(UTC)
    conds = [StrikeMission.status == "outbound"]
    if player_id is not None:
        conds.append(or_(StrikeMission.attacker_id == player_id,
                         StrikeMission.defender_id == player_id))
    res = await session.execute(select(StrikeMission).where(*conds))
    resolved = 0
    for mission in res.scalars():
        if _aware(mission.arrives_at) <= now:
            await _resolve_strike(session, mission, now)
            resolved += 1
    return {"strikes_resolved": resolved}
