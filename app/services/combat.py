"""PvP combat with fleet travel time.

`resolve_combat()` is pure/deterministic (testable without a DB). `start_attack()`
dispatches a fleet: it charges energy, LOCKS the committed units (removed from the
attacker's stock while away) and enqueues an AttackMission with an arrival time based
on distance. `process_missions()` resolves battles on arrival and returns survivors +
loot home — driven by the tick and by lazy `state.advance`.
"""
import json
import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import AttackMission, Base_, Building, CombatLog, Player, ResearchOrder
from app.services.economy import (
    collect_mines,
    finalize_due_builds,
    get_or_create_stock,
)
from app.services.energy import spend_energy
from app.services.notifications import notify
from app.services.physics import effective_energy_max, effective_energy_regen
from app.services.training import (
    finalize_due_training,
    get_or_create_unit_stock,
    natal_base_id,
    player_units,
    units_at_base,
)


class CombatError(Exception):
    pass


async def _npc_taunt(session: AsyncSession, attacker: Player, defender: Player, kind: str) -> None:
    """In-character chatter: an NPC taunts the HUMAN it fights (attack/win/lose).
    No-op for human attackers or NPC-vs-NPC, so it's invisible to the rest of the game."""
    if not attacker.is_npc or defender.is_npc:
        return
    race = get_content().races.get(attacker.race_key, {})
    lines = (race.get("taunts") or {}).get(kind) or []
    if not lines:
        return
    await notify(
        session,
        defender.id,
        "npc_taunt",
        f"{race.get('name', attacker.username)}: «{random.choice(lines)}»",
        {"from": attacker.username, "race": attacker.race_key, "kind": kind},
    )


@dataclass
class CombatResult:
    outcome: str  # "attacker" | "defender" | "draw"
    attack_score: float
    defense_score: float
    attacker_losses: dict[str, int] = field(default_factory=dict)
    defender_losses: dict[str, int] = field(default_factory=dict)


def _force_power(force: dict[str, int], stat: str) -> float:
    content = get_content()
    total = 0.0
    for unit_key, qty in force.items():
        spec = content.units.get(unit_key)
        if spec:
            total += qty * spec.get("stats", {}).get(stat, 0)
    return total


def resolve_combat(
    attacker_force: dict[str, int],
    defender_force: dict[str, int],
    attacker_atk_mult: float = 1.0,
    defender_def_mult: float = 1.0,
    defender_flat_defense: float = 0.0,
) -> CombatResult:
    """Pure resolution. Losses scale with the opposing side's share of total power.

    `defender_flat_defense` is the base's static defense (turrets) added to the
    defenders' unit defense before applying the defender multiplier."""
    attack_score = _force_power(attacker_force, "attack") * attacker_atk_mult
    defense_score = (
        _force_power(defender_force, "defense") + defender_flat_defense
    ) * defender_def_mult
    total = attack_score + defense_score

    if total <= 0:
        return CombatResult("draw", attack_score, defense_score)

    attacker_loss_ratio = defense_score / total
    defender_loss_ratio = attack_score / total

    attacker_losses = {
        k: min(qty, round(qty * attacker_loss_ratio))
        for k, qty in attacker_force.items()
        if round(qty * attacker_loss_ratio) > 0
    }
    defender_losses = {
        k: min(qty, round(qty * defender_loss_ratio))
        for k, qty in defender_force.items()
        if round(qty * defender_loss_ratio) > 0
    }

    outcome = "attacker" if attack_score > defense_score else "defender"
    return CombatResult(outcome, attack_score, defense_score, attacker_losses, defender_losses)


async def _advance_economy(session: AsyncSession, player: Player, now: datetime) -> None:
    await finalize_due_builds(session, player, now)
    await collect_mines(session, player, now)
    await finalize_due_training(session, player, now)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def travel_seconds(planet_a: str | None, planet_b: str | None) -> int:
    s = get_settings()
    return s.travel_seconds_same_planet if planet_a == planet_b else s.travel_seconds_cross_planet


# --------------------------------------------------------------------------- #
# SDD 57: bombardeo "rompe-bases" — naves con `siege_power` demuelen edificios al ganar.
# --------------------------------------------------------------------------- #
async def _bombard_buildings(
    session: AsyncSession,
    survivors: dict[str, int],
    defender: Player,
    target_base_id: int,
    content,
    settings,
) -> list[str]:
    """Demuele edificios EXCEDENTES de la base atacada según el `siege_power` sobreviviente.

    Invariantes anti-lockout (SDD 57): nunca destruye HQ ni minas (categorías core/mine), ni el
    ÚLTIMO edificio de cada tipo (solo excedentes → "solo si tenés de más"). Destruir un laboratorio
    excedente cancela la investigación EN CURSO (perdés ese progreso; las techs completas quedan).
    """
    total = sum(int(q) * content.units.get(k, {}).get("siege_power", 0)
                for k, q in survivors.items())
    per = max(1, settings.siege_per_building)
    n_destroy = int(total // per)
    if n_destroy <= 0:
        return []
    from collections import Counter
    blds = list((await session.execute(
        select(Building).where(Building.base_id == target_base_id)
    )).scalars())
    counts = Counter(b.building_key for b in blds)
    razed: list[str] = []
    # newest first; nunca HQ/mina; nunca el último de su tipo (solo excedentes)
    for b in sorted(blds, key=lambda x: x.id, reverse=True):
        if n_destroy <= 0:
            break
        cat = content.buildings.get(b.building_key, {}).get("category")
        if cat in ("core", "mine"):
            continue
        if counts[b.building_key] <= 1:
            continue
        counts[b.building_key] -= 1
        await session.delete(b)
        razed.append(b.building_key)
        n_destroy -= 1
    # SDD 57: si voló un laboratorio, se cancela la investigación en curso (perdió la base).
    if "research_lab" in razed:
        for o in (await session.execute(select(ResearchOrder).where(
            ResearchOrder.player_id == defender.id, ResearchOrder.status == "researching"
        ))).scalars():
            o.status = "cancelled"
    return razed


# --------------------------------------------------------------------------- #
# Dispatch: launch a fleet (units leave now, battle resolves on arrival)
# --------------------------------------------------------------------------- #
async def start_attack(
    session: AsyncSession, attacker: Player, target_base_id: int, force: dict[str, int],
    source_base_id: int | None = None,
) -> AttackMission:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)

    base = await session.get(Base_, target_base_id)
    if base is None:
        raise CombatError("Base objetivo no encontrada.")
    if base.player_id == attacker.id:
        raise CombatError("No puedes atacar tu propia base.")
    defender = await session.get(Player, base.player_id)
    if attacker.alliance_id is not None and attacker.alliance_id == defender.alliance_id:
        raise CombatError("No puedes atacar a un aliado.")

    # Newbie protection (SDD 11): no podés atacar a un jugador protegido; atacar a un humano
    # termina TU protección (opt-out). Atacar NPCs no la afecta.
    if not defender.is_npc:
        if defender.protected_until is not None and _aware(defender.protected_until) > now:
            raise CombatError("Ese jugador está bajo protección de novato.")
        if attacker.protected_until is not None and _aware(attacker.protected_until) > now:
            attacker.protected_until = None
        # Galaxy instances (SDD 8): solo peleás dentro de tu galaxia (NPCs son ambientales).
        if not attacker.is_npc and attacker.galaxy_instance_id != defender.galaxy_instance_id:
            raise CombatError("Ese jugador está en otra galaxia.")

    force = {k: int(q) for k, q in force.items() if q and int(q) > 0}
    if not force:
        raise CombatError("Debes enviar al menos una unidad.")
    for unit_key in force:
        if unit_key not in content.units:
            raise CombatError(f"Unidad desconocida: {unit_key}")
        # SDD 49/50: los misiles y drones no van en una flota (tienen su propia vía: /combat/strike,
        # /drones/launch).
        domain = content.units[unit_key].get("domain")
        if domain in ("ordnance", "drone"):
            raise CombatError(f"{unit_key} no se envía en una flota; usá su lanzadera/fábrica.")

    # Límite de ataques por ventana (gameplay, humanos Y NPCs): da tiempo al rival a reagruparse.
    if settings.attacks_per_window > 0:
        from sqlalchemy import func
        window_start = now - timedelta(seconds=settings.attack_window_seconds)
        recent = (await session.execute(
            select(func.count(AttackMission.id)).where(
                AttackMission.attacker_id == attacker.id,
                AttackMission.created_at >= window_start,
            )
        )).scalar_one()
        if recent >= settings.attacks_per_window:
            hrs = settings.attack_window_seconds / 3600
            raise CombatError(
                f"Llegaste al límite de ataques ({settings.attacks_per_window} cada {hrs:g}h). "
                "Esperá para volver a atacar."
            )

    # SDD 55 (anti-farmeo): topes por DÍA (humanos Y NPCs) para que nadie acose a un mismo jugador.
    if settings.attacks_per_target_per_day > 0 or settings.max_incoming_attacks_per_day > 0:
        from sqlalchemy import func
        day_start = now - timedelta(seconds=86400)
        if settings.attacks_per_target_per_day > 0:
            same_target = (await session.execute(
                select(func.count(AttackMission.id)).where(
                    AttackMission.attacker_id == attacker.id,
                    AttackMission.defender_id == defender.id,
                    AttackMission.created_at >= day_start,
                )
            )).scalar_one()
            if same_target >= settings.attacks_per_target_per_day:
                raise CombatError(
                    f"Ya atacaste a ese jugador {settings.attacks_per_target_per_day} veces hoy "
                    "(anti-abuso). Probá con otro objetivo."
                )
        if settings.max_incoming_attacks_per_day > 0:
            incoming = (await session.execute(
                select(func.count(AttackMission.id)).where(
                    AttackMission.defender_id == defender.id,
                    AttackMission.created_at >= day_start,
                )
            )).scalar_one()
            if incoming >= settings.max_incoming_attacks_per_day:
                raise CombatError(
                    "Ese rival ya fue muy golpeado hoy; dejá que se recupere (anti-abuso)."
                )

    await _advance_economy(session, attacker, now)

    # SDD 62 (guarnición): con el flag ON la flota SALE de una base (la elegida o la natal) y se
    # descuenta de SU guarnición; con OFF, del pool global (histórico).
    if settings.garrison_enabled:
        if source_base_id is None:
            source_base_id = await natal_base_id(session, attacker.id)
        src = await session.get(Base_, source_base_id) if source_base_id else None
        if src is None or src.player_id != attacker.id:
            raise CombatError("Base de origen inválida.")
        units = await units_at_base(session, attacker.id, source_base_id)
        where = " en esa base"
    else:
        source_base_id = None
        units = await player_units(session, attacker.id)
        where = ""
    for unit_key, qty in force.items():
        have = units.get(unit_key, 0)
        if have < qty:
            raise CombatError(f"No tienes suficientes {unit_key} (tienes {have}){where}.")

    if not spend_energy(
        attacker,
        settings.attack_energy_cost,
        now,
        effective_energy_regen(attacker, settings),
        effective_energy_max(attacker, settings),
    ):
        raise CombatError("Energia insuficiente para atacar.")

    # Lock the committed units: salen del stock en tránsito (de la base origen si garrison).
    for unit_key, qty in force.items():
        stock = await get_or_create_unit_stock(session, attacker.id, unit_key, source_base_id)
        stock.quantity -= qty

    travel = travel_seconds(attacker.planet_key, defender.planet_key)
    # SDD 57 v2: si la flota lleva naves espaciales y el atacante investigó el hiperespacio, salta
    # más rápido. El retorno hereda la ida (se calcula de arrives-created).
    if settings.hyperspace_travel_factor < 1.0 and any(
        content.units.get(k, {}).get("domain") == "space" for k in force
    ):
        from app.services.research import researched_techs
        if "hyperspace_travel" in await researched_techs(session, attacker.id):
            travel = max(1, int(travel * settings.hyperspace_travel_factor))
    mission = AttackMission(
        attacker_id=attacker.id,
        defender_id=defender.id,
        target_base_id=target_base_id,
        source_base_id=source_base_id,
        force=json.dumps(force),
        status="outbound",
        arrives_at=now + timedelta(seconds=travel),
    )
    session.add(mission)
    await session.flush()

    # Tell the defender something is inbound (fog of war: no force shown).
    await notify(
        session,
        defender.id,
        "incoming_attack",
        f"Ataque entrante a tu base {target_base_id}",
        {"target_base_id": target_base_id, "arrives_at": mission.arrives_at.isoformat()},
    )
    await _npc_taunt(session, attacker, defender, "attack")
    from app.services.stats import bump as _bump
    await _bump(session, attacker.id, attacks_launched=1)
    if attacker.is_npc:   # SDD 29 v2: ¿a quién le pega la IA? (humano vs otro NPC) → métrica
        from app.core import metrics
        metrics.NPC_ATTACK_TARGETS.inc(target="npc" if defender.is_npc else "human")
    from app.services.journal import record
    await record(session, "attack_launched", attacker.id,
                 defender_id=defender.id, target_base_id=target_base_id, force=force)
    return mission


# --------------------------------------------------------------------------- #
# Deferred resolution + return trip
# --------------------------------------------------------------------------- #
async def _resolve_arrival(session: AsyncSession, mission: AttackMission, now: datetime) -> None:
    content = get_content()
    settings = get_settings()
    from app.services.effects import multiplier as effect_mult

    attacker = await session.get(Player, mission.attacker_id)
    defender = await session.get(Player, mission.defender_id)
    force = json.loads(mission.force)

    # Defender's army reflects reality at the moment of impact. SDD 62: con guarnición ON, solo
    # defiende la guarnición de la base atacada; con OFF, todo el ejército (histórico).
    await _advance_economy(session, defender, now)
    def_base = mission.target_base_id if settings.garrison_enabled else None
    if settings.garrison_enabled:
        defender_force = await units_at_base(session, defender.id, mission.target_base_id)
    else:
        defender_force = await player_units(session, defender.id)

    atk_mult = content.races[attacker.race_key]["bonuses"].get("military_attack", 1.0)
    def_mult = content.races[defender.race_key]["bonuses"].get("defense", 1.0)
    atk_mult *= await effect_mult(session, attacker.id, "attack", now)
    def_mult *= await effect_mult(session, defender.id, "defense", now)

    # Static base defense: active defensive buildings at the targeted base.
    bres = await session.execute(
        select(Building).where(
            Building.base_id == mission.target_base_id, Building.status == "active"
        )
    )
    flat_defense = sum(
        content.buildings[b.building_key].get("defense_power", 0) for b in bres.scalars()
    )
    # Allies lend defense if the defender's alliance has mutual_defense.
    from app.services.alliances import mutual_defense_flat

    flat_defense += await mutual_defense_flat(session, defender)
    result = resolve_combat(force, defender_force, atk_mult, def_mult, flat_defense)

    # Defender unit losses (de la guarnición de la base atacada si garrison ON).
    for unit_key, lost in result.defender_losses.items():
        stock = await get_or_create_unit_stock(session, defender.id, unit_key, def_base)
        before = stock.quantity
        new_q = max(0, before - lost)
        # SDD 54: nunca dejar al defensor sin trabajadores → siempre puede seguir juntando material
        # y reconstruir. Protege los últimos `min_surviving_workers` (si los tenía).
        if unit_key == "worker" and settings.min_surviving_workers > 0:
            new_q = max(new_q, min(before, settings.min_surviving_workers))
        stock.quantity = new_q

    # Surviving attackers (the rest is destroyed in transit-home? no: lost in battle).
    survivors = {k: max(0, force.get(k, 0) - result.attacker_losses.get(k, 0)) for k in force}
    survivors = {k: v for k, v in survivors.items() if v > 0}

    # Loot on win: se saquea el PLANETA de la base atacada (SDD 42), se lleva a casa al volver.
    loot: dict[str, float] = {}
    if result.outcome == "attacker":
        from app.services.economy import planet_stocks
        target_base = await session.get(Base_, mission.target_base_id)
        loot_planet = target_base.planet_key if target_base else defender.planet_key
        for mineral, amount in (await planet_stocks(session, defender.id, loot_planet)).items():
            taken = round(amount * settings.loot_fraction, 2)
            if taken <= 0:
                continue
            (await get_or_create_stock(session, defender.id, mineral, loot_planet)).amount -= taken
            loot[mineral] = taken

    # SDD 57: bombardeo "rompe-bases" — si la flota ganó y trae naves con `siege_power` (acorazado),
    # demuele EDIFICIOS EXCEDENTES del defensor (nunca HQ ni minas, nunca el último de su tipo).
    razed: list[str] = []
    if result.outcome == "attacker" and settings.siege_enabled:
        razed = await _bombard_buildings(
            session, survivors, defender, mission.target_base_id, content, settings
        )

    # Lifetime stats (SDD 12).
    from app.services.stats import bump as _bump

    if result.outcome == "attacker":
        await _bump(session, attacker.id, battles_won=1, resources_looted=sum(loot.values()))
        await _bump(session, defender.id, battles_lost=1, resources_lost=sum(loot.values()))
    else:
        await _bump(session, attacker.id, battles_lost=1)
        await _bump(session, defender.id, battles_won=1)

    session.add(
        CombatLog(
            attacker_id=attacker.id,
            defender_id=defender.id,
            target_base_id=mission.target_base_id,
            outcome=result.outcome,
            details=json.dumps(
                {
                    "attack_score": round(result.attack_score, 2),
                    "defense_score": round(result.defense_score, 2),
                    "attacker_losses": result.attacker_losses,
                    "defender_losses": result.defender_losses,
                    "loot": loot,
                    "razed": razed,
                }
            ),
        )
    )

    await notify(
        session,
        attacker.id,
        "battle_result",
        f"Batalla en base {mission.target_base_id}: {result.outcome}",
        {"outcome": result.outcome, "loot": loot, "your_losses": result.attacker_losses},
    )
    await notify(
        session,
        defender.id,
        "attacked",
        f"Te atacaron (base {mission.target_base_id}): {result.outcome}"
        + (f" — bombardearon {len(razed)} edificio(s): {', '.join(razed)}" if razed else ""),
        {"outcome": result.outcome, "your_losses": result.defender_losses,
         "looted": loot, "razed": razed},
    )
    # NPC follow-up taunt to the human, by result.
    await _npc_taunt(
        session, attacker, defender, "win" if result.outcome == "attacker" else "lose"
    )

    from app.services.journal import record
    await record(session, "battle_resolved", attacker.id,
                 defender_id=defender.id, target_base_id=mission.target_base_id,
                 outcome=result.outcome, force=force, attacker_losses=result.attacker_losses,
                 defender_losses=result.defender_losses, loot=loot)

    # SDD 29 §3.7: reflexión post-batalla de los NPC involucrados (ajustan postura por resultado).
    from app.services.npc import reflect_on_battle
    atk_won = result.outcome == "attacker"
    if attacker.is_npc:
        await reflect_on_battle(session, attacker, "attacker", atk_won, defender.username)
    if defender.is_npc:
        await reflect_on_battle(session, defender, "defender", not atk_won, attacker.username)

    mission.details = json.dumps({"outcome": result.outcome, "survivors": survivors, "loot": loot})
    if survivors or loot:
        mission.status = "returning"
        # El retorno tarda lo mismo que la ida (incluye la rebaja por hiperespacio, SDD 57 v2).
        one_way = (_aware(mission.arrives_at) - _aware(mission.created_at)).total_seconds()
        mission.returns_at = now + timedelta(seconds=one_way)
    else:
        mission.status = "done"  # fleet wiped out, nothing returns


async def _process_return(session: AsyncSession, mission: AttackMission) -> None:
    details = json.loads(mission.details or "{}")
    # SDD 62: los sobrevivientes vuelven a la base de origen (None = pool global, modo histórico).
    for unit_key, qty in details.get("survivors", {}).items():
        (await get_or_create_unit_stock(
            session, mission.attacker_id, unit_key, mission.source_base_id
        )).quantity += qty
    # El botín se descarga en el mundo natal del atacante (SDD 42).
    attacker = await session.get(Player, mission.attacker_id)
    home = attacker.planet_key if attacker else ""
    for mineral, amount in details.get("loot", {}).items():
        (await get_or_create_stock(session, mission.attacker_id, mineral, home)).amount += amount
    mission.status = "done"
    await notify(
        session,
        mission.attacker_id,
        "fleet_returned",
        "Tu flota regreso a la base",
        {"survivors": details.get("survivors", {}), "loot": details.get("loot", {})},
    )


async def recall_mission(session: AsyncSession, player: Player, mission_id: int) -> AttackMission:
    """Turn an in-flight (outbound) fleet around. It travels back the distance already
    covered and returns the full force (no battle). Only the owner, only while outbound."""
    now = datetime.now(UTC)
    mission = await session.get(AttackMission, mission_id)
    if mission is None or mission.attacker_id != player.id:
        raise CombatError("Mision no encontrada.")
    if mission.status != "outbound":
        raise CombatError("Solo se puede retirar una flota en vuelo de ida.")

    elapsed = (now - _aware(mission.created_at)).total_seconds()
    one_way = (_aware(mission.arrives_at) - _aware(mission.created_at)).total_seconds()
    travel_back = max(0.0, min(elapsed, one_way))
    mission.status = "returning"
    mission.returns_at = now + timedelta(seconds=travel_back)
    mission.details = json.dumps(
        {"outcome": "recalled", "survivors": json.loads(mission.force), "loot": {}}
    )
    await session.flush()
    return mission


async def process_missions(
    session: AsyncSession, now: datetime | None = None, player_id: int | None = None
) -> dict:
    """Resolve arrivals and process returns. Scope to a player (lazy advance) or all (tick)."""
    now = now or datetime.now(UTC)
    conds = [AttackMission.status.in_(("outbound", "returning"))]
    if player_id is not None:
        conds.append(
            or_(AttackMission.attacker_id == player_id, AttackMission.defender_id == player_id)
        )
    res = await session.execute(select(AttackMission).where(*conds))
    resolved = returned = 0
    for mission in res.scalars():
        if mission.status == "outbound" and _aware(mission.arrives_at) <= now:
            await _resolve_arrival(session, mission, now)
            resolved += 1
        elif (
            mission.status == "returning"
            and mission.returns_at
            and _aware(mission.returns_at) <= now
        ):
            await _process_return(session, mission)
            returned += 1
    return {"battles_resolved": resolved, "fleets_returned": returned}
