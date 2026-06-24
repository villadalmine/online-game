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
from app.models import AttackMission, Base_, Building, CombatLog, Player
from app.services.economy import (
    collect_mines,
    finalize_due_builds,
    get_or_create_stock,
    player_stocks,
)
from app.services.energy import spend_energy
from app.services.notifications import notify
from app.services.physics import effective_energy_regen
from app.services.training import (
    finalize_due_training,
    get_or_create_unit_stock,
    player_units,
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
# Dispatch: launch a fleet (units leave now, battle resolves on arrival)
# --------------------------------------------------------------------------- #
async def start_attack(
    session: AsyncSession, attacker: Player, target_base_id: int, force: dict[str, int]
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

    await _advance_economy(session, attacker, now)

    units = await player_units(session, attacker.id)
    for unit_key, qty in force.items():
        have = units.get(unit_key, 0)
        if have < qty:
            raise CombatError(f"No tienes suficientes {unit_key} (tienes {have}).")

    if not spend_energy(
        attacker,
        settings.attack_energy_cost,
        now,
        effective_energy_regen(attacker, settings),
        settings.energy_max,
    ):
        raise CombatError("Energia insuficiente para atacar.")

    # Lock the committed units: they leave the stock while in transit.
    for unit_key, qty in force.items():
        stock = await get_or_create_unit_stock(session, attacker.id, unit_key)
        stock.quantity -= qty

    travel = travel_seconds(attacker.planet_key, defender.planet_key)
    mission = AttackMission(
        attacker_id=attacker.id,
        defender_id=defender.id,
        target_base_id=target_base_id,
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

    # Defender's army reflects reality at the moment of impact.
    await _advance_economy(session, defender, now)
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

    # Defender unit losses.
    for unit_key, lost in result.defender_losses.items():
        stock = await get_or_create_unit_stock(session, defender.id, unit_key)
        stock.quantity = max(0, stock.quantity - lost)

    # Surviving attackers (the rest is destroyed in transit-home? no: lost in battle).
    survivors = {k: max(0, force.get(k, 0) - result.attacker_losses.get(k, 0)) for k in force}
    survivors = {k: v for k, v in survivors.items() if v > 0}

    # Loot on win (taken from defender now, carried home on return).
    loot: dict[str, float] = {}
    if result.outcome == "attacker":
        for mineral, amount in (await player_stocks(session, defender.id)).items():
            taken = round(amount * settings.loot_fraction, 2)
            if taken <= 0:
                continue
            (await get_or_create_stock(session, defender.id, mineral)).amount -= taken
            loot[mineral] = taken

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
        f"Te atacaron (base {mission.target_base_id}): {result.outcome}",
        {"outcome": result.outcome, "your_losses": result.defender_losses, "looted": loot},
    )
    # NPC follow-up taunt to the human, by result.
    await _npc_taunt(
        session, attacker, defender, "win" if result.outcome == "attacker" else "lose"
    )

    mission.details = json.dumps({"outcome": result.outcome, "survivors": survivors, "loot": loot})
    if survivors or loot:
        mission.status = "returning"
        mission.returns_at = now + timedelta(
            seconds=travel_seconds(attacker.planet_key, defender.planet_key)
        )
    else:
        mission.status = "done"  # fleet wiped out, nothing returns


async def _process_return(session: AsyncSession, mission: AttackMission) -> None:
    details = json.loads(mission.details or "{}")
    for unit_key, qty in details.get("survivors", {}).items():
        (await get_or_create_unit_stock(session, mission.attacker_id, unit_key)).quantity += qty
    for mineral, amount in details.get("loot", {}).items():
        (await get_or_create_stock(session, mission.attacker_id, mineral)).amount += amount
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
