"""SDD 50 — Drones intra-planeta: espías orbitales (intel en vivo) + ataque.

Un escuadrón ORBITA una base enemiga del mismo planeta. Mientras orbita: drena TU energía
(`energy_per_tick` por dron) y las torretas del rival lo derriban (`antiair_power` por torreta por
tick vs el hp del escuadrón). Mientras quede ≥1 dron espía vivo, recibís intel en vivo; los drones
de ataque castigan la base por tick. Lazy por timestamp (igual que minería/energía): al leer,
`advance_drones()` aplica los ticks transcurridos y mata el escuadrón si se queda sin energía o sin
drones. `simulate_drones()` es puro (calculadora + tests).

Ver docs/sdd-drones-intraplanet.md.
"""
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, DroneSquadron, Player
from app.services.notifications import notify
from app.services.physics import effective_energy_regen


class DroneError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _drone(key: str) -> dict:
    return get_content().units.get(key, {})


def _alive_hp_list(alive: dict[str, int]) -> list[float]:
    """hp de cada dron vivo (uno por unidad), para repartir el fuego antiaéreo."""
    out: list[float] = []
    for key, qty in alive.items():
        hp = float(_drone(key).get("hp", 1) or 1)
        out.extend([hp] * int(qty))
    return out


def drain_per_tick(alive: dict[str, int]) -> float:
    return sum(float(_drone(k).get("energy_per_tick", 0)) * q for k, q in alive.items())


def attack_per_tick(alive: dict[str, int]) -> float:
    return sum(float(_drone(k).get("attack", 0)) * q for k, q in alive.items())


def intel_quality(alive: dict[str, int]) -> float:
    qs = [float(_drone(k).get("intel_quality", 0)) for k, q in alive.items() if q]
    return max(qs) if qs else 0.0


def _apply_kills(alive: dict[str, int], pool: float) -> tuple[dict[str, int], float]:
    """Gasta `pool` de daño antiaéreo derribando drones (los de menor hp primero). Devuelve el
    estado vivo y el daño sobrante (carry dentro del período)."""
    out = dict(alive)
    for key in sorted(out, key=lambda k: float(_drone(k).get("hp", 1) or 1)):
        hp = float(_drone(key).get("hp", 1) or 1)
        while out.get(key, 0) > 0 and pool >= hp:
            pool -= hp
            out[key] -= 1
    return {k: v for k, v in out.items() if v > 0}, pool


@dataclass
class DroneSim:
    survive_ticks: int = 0
    losses: dict[str, int] = field(default_factory=dict)
    survivors: dict[str, int] = field(default_factory=dict)
    drain_per_tick: float = 0.0
    attack_per_tick: float = 0.0
    intel_quality: float = 0.0
    eta_energy_ticks: float | None = None
    eta_turrets_ticks: float | None = None
    energy_after: float = 0.0
    attack_dealt: float = 0.0
    died_of_energy: bool = False


def _etas(alive, antiair, energy, regen_per_tick):
    """ETAs en forma cerrada (para el panel/calculadora)."""
    drain = drain_per_tick(alive)
    net = regen_per_tick - drain
    eta_energy = None if net >= 0 else (energy / (drain - regen_per_tick))
    total_hp = sum(_alive_hp_list(alive))
    eta_turrets = None if antiair <= 0 else (total_hp / antiair)
    return eta_energy, eta_turrets


def simulate_drones(
    force: dict[str, int], antiair: float, energy: float,
    regen_per_tick: float, max_ticks: int | None = None,
) -> DroneSim:
    """Simulación pura tick a tick. Cada tick: las torretas suman daño (carry) y derriban drones;
    los vivos drenan energía y (de ataque) golpean; si la energía llega a 0 el escuadrón muere."""
    alive = {k: int(v) for k, v in force.items() if v and int(v) > 0}
    start = dict(alive)
    eta_energy, eta_turrets = _etas(alive, antiair, energy, regen_per_tick)
    d0 = drain_per_tick(alive)
    a0 = attack_per_tick(alive)

    cap = max_ticks if max_ticks is not None else 100000  # cota de seguridad para el loop
    aa_pool = 0.0
    ticks = 0
    attack_dealt = 0.0
    died_energy = False
    while alive and ticks < cap:
        # 1) fuego antiaéreo (acumula y derriba)
        aa_pool += antiair
        alive, aa_pool = _apply_kills(alive, aa_pool)
        if not alive:
            ticks += 1
            break
        # 2) drenaje de energía
        energy -= drain_per_tick(alive)
        # 3) daño de ataque mientras vivan
        attack_dealt += attack_per_tick(alive)
        ticks += 1
        # 4) muerte por energía
        if energy <= 0:
            energy = 0.0
            died_energy = True
            alive = {}
            break
        # si no hay torretas ni drenaje neto y no hay tope, se sostiene indefinido → cortar
        if antiair <= 0 and regen_per_tick >= drain_per_tick(alive) and max_ticks is None:
            break

    losses = {k: start.get(k, 0) - alive.get(k, 0)
              for k in start if start.get(k, 0) - alive.get(k, 0) > 0}
    return DroneSim(
        survive_ticks=ticks, losses=losses, survivors=alive,
        drain_per_tick=d0, attack_per_tick=a0, intel_quality=intel_quality(start),
        eta_energy_ticks=eta_energy, eta_turrets_ticks=eta_turrets,
        energy_after=energy, attack_dealt=attack_dealt, died_of_energy=died_energy,
    )


async def _active_turret_antiair(session: AsyncSession, defender: Player, base_id: int) -> float:
    content = get_content()
    from app.services.effects import multiplier as effect_mult
    aa = sum(
        content.buildings.get(b.building_key, {}).get("antiair_power", 0)
        for b in (await session.execute(select(Building).where(
            Building.base_id == base_id, Building.status == "active"))).scalars()
    )
    return aa * await effect_mult(session, defender.id, "defense")


async def _has_active(session: AsyncSession, base_id: int, building_key: str) -> bool:
    res = await session.execute(select(Building).where(
        Building.base_id == base_id, Building.building_key == building_key,
        Building.status == "active"))
    return res.first() is not None


def _regen_per_tick(player: Player, settings) -> float:
    return effective_energy_regen(player, settings) / 3600.0 * settings.drone_tick_seconds


async def launch_drones(
    session: AsyncSession, owner: Player, factory_base_id: int,
    target_base_id: int, force: dict[str, int], max_ticks: int | None = None,
) -> DroneSquadron:
    content = get_content()
    settings = get_settings()
    now = datetime.now(UTC)
    if not settings.drones_enabled:
        raise DroneError("Los drones están deshabilitados en este mundo.")

    factory = await session.get(Base_, factory_base_id)
    if factory is None or factory.player_id != owner.id:
        raise DroneError("Fábrica de drones no encontrada.")
    if not await _has_active(session, factory_base_id, "drone_factory"):
        raise DroneError("Esa base no tiene una fábrica de drones activa.")

    target = await session.get(Base_, target_base_id)
    if target is None:
        raise DroneError("Base objetivo no encontrada.")
    if target.player_id == owner.id:
        raise DroneError("No puedes orbitar tu propia base.")
    if target.planet_key != factory.planet_key:
        raise DroneError("Los drones no salen del planeta.")
    defender = await session.get(Player, target.player_id)
    if owner.alliance_id is not None and owner.alliance_id == defender.alliance_id:
        raise DroneError("No puedes atacar a un aliado.")
    if not defender.is_npc and defender.protected_until is not None and \
            _aware(defender.protected_until) > now:
        raise DroneError("Ese jugador está bajo protección de novato.")

    force = {k: int(q) for k, q in force.items() if q and int(q) > 0}
    if not force:
        raise DroneError("Debes lanzar al menos un dron.")
    for key in force:
        spec = content.units.get(key)
        if spec is None or spec.get("domain") != "drone":
            raise DroneError(f"No es un dron: {key}")
        rtech = spec.get("requires_tech")
        if rtech:
            from app.services.research import researched_techs
            if rtech not in await researched_techs(session, owner.id):
                raise DroneError(f"Requiere investigar: {rtech}")

    from app.services.combat import _advance_economy
    await _advance_economy(session, owner, now)
    from app.services.training import get_or_create_unit_stock, player_units
    have = await player_units(session, owner.id)
    for key, qty in force.items():
        if have.get(key, 0) < qty:
            raise DroneError(f"No tenés suficientes {key} (tenés {have.get(key, 0)}).")
    # los drones salen del stock mientras orbitan (vuelven con recall si sobreviven)
    for key, qty in force.items():
        (await get_or_create_unit_stock(session, owner.id, key)).quantity -= qty

    squad = DroneSquadron(
        owner_id=owner.id, target_id=defender.id, factory_base_id=factory_base_id,
        target_base_id=target_base_id, planet_key=factory.planet_key,
        force=json.dumps(force), status="orbiting", max_ticks=max_ticks,
        last_tick_at=now,
    )
    session.add(squad)
    await session.flush()
    await notify(
        session, defender.id, "drones_inbound",
        f"Drones orbitando tu base {target_base_id}", {"target_base_id": target_base_id},
    )
    from app.services.journal import record
    await record(session, "drones_launched", owner.id, defender_id=defender.id,
                 target_base_id=target_base_id, force=force)
    return squad


async def advance_drones(
    session: AsyncSession, player: Player, now: datetime | None = None
) -> int:
    """Avanza los escuadrones del jugador por los ticks transcurridos (lazy). Drena su energía,
    aplica derribos por torretas y daño de ataque; mata el escuadrón sin energía o sin drones.
    Debe correr ANTES de apply_regen (el regen del período se suma aparte). Devuelve nº squads."""
    settings = get_settings()
    if not settings.drones_enabled:
        return 0
    now = now or datetime.now(UTC)
    tick_s = settings.drone_tick_seconds
    res = await session.execute(select(DroneSquadron).where(
        DroneSquadron.owner_id == player.id, DroneSquadron.status == "orbiting"))
    squads = list(res.scalars())
    if not squads:
        return 0
    processed = 0
    for squad in squads:
        elapsed = (now - _aware(squad.last_tick_at)).total_seconds()
        n = int(elapsed // tick_s)
        if n <= 0:
            continue
        if squad.max_ticks is not None:
            n = min(n, squad.max_ticks - squad.ticks_done)
            if n <= 0:
                continue
        alive = json.loads(squad.force)
        defender = await session.get(Player, squad.target_id)
        antiair = await _active_turret_antiair(session, defender, squad.target_base_id) \
            if defender else 0.0
        regen_pt = _regen_per_tick(player, settings)
        sim = simulate_drones(alive, antiair, player.energy, regen_pt, max_ticks=n)
        # Drenaje BRUTO del período sobre la energía del jugador (el regen del período lo agrega
        # apply_regen aparte, en state.advance). Se recalcula tick a tick por los drones vivos.
        gross_drain = 0.0
        cur = dict(alive)
        aa_pool = 0.0
        for _t in range(sim.survive_ticks):
            aa_pool += antiair
            cur, aa_pool = _apply_kills(cur, aa_pool)
            if not cur:
                break
            gross_drain += drain_per_tick(cur)
        player.energy = max(0.0, player.energy - gross_drain)
        squad.ticks_done += sim.survive_ticks
        squad.last_tick_at = now
        # daño de ataque a la base objetivo (destruye edificios, como una salva acumulada)
        if sim.attack_dealt > 0:
            from app.services.effects import multiplier as effect_mult
            atk_mult = await effect_mult(session, player.id, "attack", now)
            await _apply_attack_damage(
                session, squad.target_base_id, sim.attack_dealt * atk_mult)
        if sim.died_of_energy or not sim.survivors or player.energy <= 0:
            squad.status = "dead"
            squad.force = json.dumps(sim.survivors)
            await notify(session, player.id, "drones_lost",
                         f"Tu escuadrón en base {squad.target_base_id} cayó", {})
        else:
            squad.force = json.dumps(sim.survivors)
        processed += 1
    return processed


async def _apply_attack_damage(session: AsyncSession, base_id: int, damage: float) -> list[str]:
    """Daño de drones de ataque: destruye edificios de la base (no la HQ), defensivos primero."""
    from app.services.strike import _active_buildings, _building_hp, _is_defensive
    targets = [b for b in await _active_buildings(session, base_id)
               if b.building_key != "headquarters"]
    targets.sort(key=lambda b: (0 if _is_defensive(b.building_key) else 1, b.id))
    pool = damage
    destroyed: list[str] = []
    for b in targets:
        hp = _building_hp(b.building_key)
        if pool >= hp:
            pool -= hp
            destroyed.append(b.building_key)
            await session.delete(b)
        else:
            break
    return destroyed


async def recall_drones(session: AsyncSession, player: Player, squad_id: int) -> DroneSquadron:
    """Trae un escuadrón de vuelta: los drones sobrevivientes vuelven al stock."""
    now = datetime.now(UTC)
    await advance_drones(session, player, now)
    squad = await session.get(DroneSquadron, squad_id)
    if squad is None or squad.owner_id != player.id:
        raise DroneError("Escuadrón no encontrado.")
    if squad.status != "orbiting":
        raise DroneError("Ese escuadrón ya no está orbitando.")
    from app.services.training import get_or_create_unit_stock
    survivors = json.loads(squad.force)
    for key, qty in survivors.items():
        (await get_or_create_unit_stock(session, player.id, key)).quantity += qty
    squad.status = "recalled"
    await session.flush()
    return squad


async def squadrons_state(session: AsyncSession, player: Player) -> tuple[list[dict], dict]:
    """Bloque para /players/me: escuadrones vivos (con ETAs) + intel en vivo por objetivo."""
    settings = get_settings()
    res = await session.execute(select(DroneSquadron).where(
        DroneSquadron.owner_id == player.id, DroneSquadron.status == "orbiting"))
    squads_out: list[dict] = []
    intel_live: dict[str, dict] = {}
    regen_pt = _regen_per_tick(player, settings)
    for squad in res.scalars():
        alive = json.loads(squad.force)
        if not alive:
            continue
        defender = await session.get(Player, squad.target_id)
        antiair = await _active_turret_antiair(session, defender, squad.target_base_id) \
            if defender else 0.0
        eta_e, eta_t = _etas(alive, antiair, player.energy, regen_pt)
        iq = intel_quality(alive)
        squads_out.append({
            "id": squad.id, "target_base_id": squad.target_base_id,
            "planet_key": squad.planet_key, "force": alive, "status": squad.status,
            "drain_per_tick": round(drain_per_tick(alive), 2), "intel_quality": iq,
            "eta_energy_ticks": round(eta_e, 1) if eta_e is not None else None,
            "eta_turrets_ticks": round(eta_t, 1) if eta_t is not None else None,
            "ticks_done": squad.ticks_done,
        })
        if iq > 0:
            intel_live[str(squad.target_base_id)] = {
                "target_id": squad.target_id, "quality": iq,
            }
    return squads_out, intel_live
