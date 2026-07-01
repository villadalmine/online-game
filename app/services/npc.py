"""NPC (AI-controlled) races.

Design: a pluggable `NpcBrain` decides ONE action per tick for an NPC, executed
through the SAME services a human uses (build/train/attack). The default
`RuleBasedBrain` is deterministic, cheap and dependency-free. `LlmBrain` is an
optional OpenRouter-backed brain behind the same interface, with a hard fallback
to rules — so the game never depends on the network to take an NPC turn.
"""
import json
import logging
import re
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core import metrics
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import AttackMission, Base_, Building, CombatLog, Player
from app.services.build import start_build
from app.services.combat import CombatError, recall_mission, start_attack
from app.services.drones import launch_drones
from app.services.economy import player_stocks
from app.services.energy import compute_energy
from app.services.expedition import start_expedition
from app.services.llm import llm_chat
from app.services.onboarding import onboard_player
from app.services.physics import effective_energy_max, effective_energy_regen
from app.services.scoring import player_score
from app.services.state import advance
from app.services.strike import start_strike
from app.services.training import player_units, start_training

SOLDIER_BATCH = 3
ATTACK_POWER_MARGIN = 1.2  # only attack if our attack power exceeds defense by this factor


# --------------------------------------------------------------------------- #
# NPC provisioning
# --------------------------------------------------------------------------- #
NPC_ALLIANCE_NAME = "Consorcio Estelar"
NPC_ALLIANCE_TAG = "AI"


async def ensure_npcs(session: AsyncSession) -> int:
    """Create one NPC per race (onboarded to its home planet) if missing. Con
    `npc_shared_alliance` las mantiene en una alianza común (cooperan); si no (default), quedan
    INDEPENDIENTES → también se atacan entre ellas."""
    content = get_content()
    created = 0
    for race_key, race in content.races.items():
        username = f"npc_{race_key}"
        res = await session.execute(select(Player).where(Player.username == username))
        if res.scalar_one_or_none() is not None:
            continue
        npc = Player(
            username=username,
            password_hash=hash_password("!npc-no-login!"),
            is_npc=True,
        )
        session.add(npc)
        await session.flush()
        galaxy = content.planet_galaxy[race["home_planet"]]
        await onboard_player(session, npc, galaxy, race["home_planet"], race_key)
        created += 1
    if get_settings().npc_shared_alliance:
        await _ensure_npc_alliance(session)
    else:
        await _disband_npc_alliance(session)   # independientes → se atacan entre sí
    await session.commit()
    return created


async def _disband_npc_alliance(session: AsyncSession) -> None:
    """Saca a las NPC de cualquier alianza (modo independiente): así `_enemy_bases` las incluye y se
    atacan entre ellas. Idempotente."""
    npcs = list((await session.execute(select(Player).where(Player.is_npc.is_(True)))).scalars())
    for npc in npcs:
        if npc.alliance_id is not None:
            npc.alliance_id = None


async def _ensure_npc_alliance(session: AsyncSession) -> None:
    from app.models import Alliance

    npcs = list((await session.execute(select(Player).where(Player.is_npc.is_(True)))).scalars())
    if not npcs:
        return
    # Identify the NPC alliance by "already has an NPC member" (robust against a human
    # grabbing the name), not by name match.
    existing = next((n.alliance_id for n in npcs if n.alliance_id is not None), None)
    alliance = await session.get(Alliance, existing) if existing else None
    if alliance is None:
        name = NPC_ALLIANCE_NAME
        taken = (
            await session.execute(select(Alliance).where(Alliance.name == name))
        ).scalar_one_or_none()
        if taken is not None:
            name = f"{NPC_ALLIANCE_NAME} (IA)"
        alliance = Alliance(name=name, tag=NPC_ALLIANCE_TAG, type="full", leader_id=npcs[0].id)
        session.add(alliance)
        await session.flush()
    for npc in npcs:
        if npc.alliance_id != alliance.id:
            npc.alliance_id = alliance.id


# --------------------------------------------------------------------------- #
# Feasibility helpers (pure-ish reads; no mutation)
# --------------------------------------------------------------------------- #
def _current_energy(player: Player) -> float:
    s = get_settings()
    now = datetime.now(UTC)
    return compute_energy(
        player.energy,
        player.energy_updated_at,
        now,
        effective_energy_regen(player, s),
        effective_energy_max(player, s),
    )


def _can_afford(
    stocks: dict[str, float], energy: float, cost: dict[str, float], energy_cost: float
) -> bool:
    if energy < energy_cost:
        return False
    return all(stocks.get(m, 0.0) >= amt for m, amt in cost.items())


async def _buildings(session: AsyncSession, player: Player) -> list[Building]:
    res = await session.execute(
        select(Building)
        .join(Base_, Building.base_id == Base_.id)
        .where(Base_.player_id == player.id)
    )
    return list(res.scalars())


async def _enemy_bases(session: AsyncSession, player: Player) -> list[Base_]:
    """Bases the player may actually attack: not own, not an ally's."""
    res = await session.execute(select(Base_).where(Base_.player_id != player.id))
    out = []
    for b in res.scalars():
        owner = await session.get(Player, b.player_id)
        if player.alliance_id is not None and owner.alliance_id == player.alliance_id:
            continue
        out.append(b)
    return out


async def _incoming_attacks(session: AsyncSession, player: Player) -> list[AttackMission]:
    res = await session.execute(
        select(AttackMission).where(
            AttackMission.defender_id == player.id, AttackMission.status == "outbound"
        )
    )
    return list(res.scalars())


async def _my_outbound(session: AsyncSession, player: Player) -> list[AttackMission]:
    res = await session.execute(
        select(AttackMission).where(
            AttackMission.attacker_id == player.id, AttackMission.status == "outbound"
        )
    )
    return list(res.scalars())


async def _npc_reinforce(session: AsyncSession, player: Player, target_base_id: int) -> bool:
    """SDD 62: la NPC mueve tropas de otra base a la base atacada (guarnición). Best-effort."""
    from app.services.training import units_by_base
    from app.services.troops import TroopError, start_move
    content = get_content()
    ubb = await units_by_base(session, player.id)
    mil = {k for k, u in content.units.items() if u.get("domain") in ("infantry", "ground")}
    for bid, units in ubb.items():
        if bid == target_base_id:
            continue
        send = {k: v for k, v in units.items() if k in mil and v > 0}
        if not send:
            continue
        try:
            await start_move(session, player, bid, target_base_id, send)
            return True
        except TroopError:
            return False
    return False


async def _npc_launch_satellite(session: AsyncSession, player: Player, rivals: list) -> bool:
    """SDD 61: si la NPC tiene un satélite espía, lo lanza contra un rival. Best-effort."""
    from app.services.satellites import SatelliteError, launch
    units = await player_units(session, player.id)
    if units.get("spy_satellite", 0) <= 0 or not rivals:
        return False
    try:
        await launch(session, player, "spy_satellite", rivals[0].id)
        return True
    except SatelliteError:
        return False


async def _base_defense_estimate(session: AsyncSession, base: Base_) -> float:
    """Defender unit defense + active turret power at a base (what an attacker faces). SDD 62: con
    guarnición, solo defiende la guarnición de ESA base (no todo el ejército) → estimar por base."""
    content = get_content()
    if get_settings().garrison_enabled:
        from app.services.training import units_at_base
        owner_units = await units_at_base(session, base.player_id, base.id)
    else:
        owner_units = await player_units(session, base.player_id)
    unit_def = sum(
        qty * content.units.get(k, {}).get("stats", {}).get("defense", 0)
        for k, qty in owner_units.items()
    )
    bres = await session.execute(
        select(Building).where(Building.base_id == base.id, Building.status == "active")
    )
    turret_def = sum(
        content.buildings[b.building_key].get("defense_power", 0) for b in bres.scalars()
    )
    return unit_def + turret_def


def _force_attack_power(units: dict[str, int]) -> float:
    content = get_content()
    return sum(
        qty * content.units.get(k, {}).get("stats", {}).get("attack", 0) for k, qty in units.items()
    )


# --------------------------------------------------------------------------- #
# Brains
# --------------------------------------------------------------------------- #
class NpcBrain(Protocol):
    async def act(self, session: AsyncSession, player: Player) -> str | None: ...


async def _meta_for_npc(session: AsyncSession) -> str:
    """Texto del meta para el cerebro LLM (SDD 41). Vacío si no hay datos."""
    try:
        from app.services.insights import meta_summary_text
        return await meta_summary_text(session)
    except Exception:
        return ""


async def _best_meta_unit(session: AsyncSession, min_n: int = 5) -> str | None:
    """Unidad con mejor win-rate (SDD 41), con muestra suficiente y >50%. None si no aplica."""
    try:
        from app.services.insights import get_insights
        by_unit = (await get_insights(session)).get("winrate_by_unit", {}).get("payload", {})
    except Exception:
        return None
    cands = [
        (v["rate"], u) for u, v in by_unit.items()
        if v.get("n", 0) >= min_n and v.get("rate", 0) > 0.5 and u in get_content().units
    ]
    if not cands:
        return None
    cands.sort(reverse=True)
    return cands[0][1]


def _unit_ready(unit: str, active: set, content) -> bool:
    """¿La NPC puede fabricar esta unidad? (su edificio requerido está activo)."""
    req = content.units.get(unit, {}).get("requires")
    return not req or req == "headquarters" or req in active


class RuleBasedBrain:
    """Deterministic, tactical priority heuristic over the existing game systems."""

    async def act(self, session: AsyncSession, player: Player) -> str | None:
        content = get_content()
        roles = content.races[player.race_key]["resource_roles"]
        structural, energetic = roles["structural"], roles["energetic"]

        stocks = await player_stocks(session, player.id)
        units = await player_units(session, player.id)
        energy = _current_energy(player)
        buildings = await _buildings(session, player)
        base = next((b for b in await _bases(session, player)), None)
        if base is None:
            return None

        mines = {b.production_mineral for b in buildings if b.building_key == "mine"}
        keys = {b.building_key for b in buildings}
        active = {b.building_key for b in buildings if b.status == "active"}
        turrets = sum(1 for b in buildings if b.building_key == "turret")
        from app.services.research import researched_techs  # SDD 1: árbol de tech
        techs = await researched_techs(session, player.id)

        def _gated(spec: dict) -> bool:
            """Cumple el árbol: edificio previo activo + investigación requerida."""
            req = spec.get("requires")
            if req and req != "headquarters" and req not in active:
                return False
            rt = spec.get("requires_tech")
            return not (rt and rt not in techs)

        def afford_building(key: str) -> bool:
            spec = content.buildings[key]
            if not _gated(spec):
                return False
            cost = content.building_cost_in_minerals(player.race_key, key)
            return _can_afford(stocks, energy, cost, spec.get("energy_cost", 0))

        # SDD 46: alojamiento — el NPC respeta las plazas (no entrena sin lugar → no rompe el turno
        # con TrainingError) y construye el edificio que aloja cuando hace falta.
        from app.services.housing import (
            can_train,
            housing_capacity,
            housing_occupancy,
            unit_domain,
        )
        _hcap = housing_capacity([b.building_key for b in buildings if b.status == "active"])
        _hocc = housing_occupancy(units)
        _settings = get_settings()

        def house_ok(unit_key: str, qty: int) -> bool:
            if not _settings.housing_enforced:
                return True
            d = unit_domain(unit_key)
            return can_train(unit_key, qty, _hcap.get(d, 0) - _hocc.get(d, 0))

        def afford_units(unit_key: str, qty: int) -> bool:
            spec = content.units[unit_key]
            if not _gated(spec):
                return False
            if not house_ok(unit_key, qty):   # sin plazas libres → no entrenar (no rompe el turno)
                return False
            unit_cost = content.unit_cost_in_minerals(player.race_key, unit_key)
            cost = {m: a * qty for m, a in unit_cost.items()}
            e = spec.get("energy_cost", 0) * qty
            return _can_afford(stocks, energy, cost, e)

        # 0) THREAT RESPONSE: under attack -> recall a roaming fleet, then fortify.
        incoming = await _incoming_attacks(session, player)
        if incoming:
            outbound = await _my_outbound(session, player)
            if outbound:
                await recall_mission(session, player, outbound[0].id)
                return "recall fleet to defend"
            # SDD 62: con guarnición, reforzar la base atacada moviendo tropas de otra base propia.
            if _settings.garrison_enabled and await _npc_reinforce(
                session, player, incoming[0].target_base_id
            ):
                return "move troops to defend"
            if turrets < 3 and afford_building("turret"):
                await start_build(session, player, base, "turret")
                return "build turret (under attack)"

        # SDD 29 v2: el PERFIL vigente sesga las prioridades de este turno (margin de ataque,
        # defensa primero, arsenal, expediciones/colonización). Lo fija pick_posture_rules/LLM.
        prof = _profile(player)
        margin = prof["margin"]

        # 1) Economy: mines for the race's core minerals.
        for mineral in (structural, energetic):
            if mineral not in mines and afford_building("mine"):
                await start_build(session, player, base, "mine", target_mineral=mineral)
                return f"build mine ({mineral})"

        # 1.5) SDD 47: operá las minas con obreros (staffing) y poné silos si rebalsás.
        active_mines = sum(
            1 for b in buildings if b.building_key == "mine" and b.status == "active"
        )
        if active_mines:
            slots = active_mines * content.buildings["mine"].get("worker_slots", 0)
            mp = content.units.get("worker", {}).get("mining_power", 1)
            if units.get("worker", 0) * mp < slots and afford_units("worker", 1):
                await start_training(session, player, base, "worker", 1)
                return "train worker (staffing)"
        if _settings.storage_caps_enabled and afford_building("silo"):
            from app.services.economy import planet_stocks, storage_caps_by_planet
            bres = await session.execute(select(Base_).where(Base_.player_id == player.id))
            base_info = {b.id: (b.planet_key, b.base_type) for b in bres.scalars()}
            caps = storage_caps_by_planet(
                content, buildings, base_info,
                _settings.base_storage_per_mineral, content.minerals.keys(),
            )
            for planet, mins in caps.items():
                ps = await planet_stocks(session, player.id, planet)
                over = next((m for m, cap in mins.items() if ps.get(m, 0.0) >= cap), None)
                if over:
                    await start_build(session, player, base, "silo", target_mineral=over)
                    return f"build silo ({over})"

        # 2) Ciencia + industria (árbol de tech): laboratorio → investigar → fábrica.
        if "research_lab" not in keys and afford_building("research_lab"):
            await start_build(session, player, base, "research_lab")
            return "build research_lab"
        if "research_lab" in active:   # investigar lo que habilita defensa/industria/expansión
            _research_list = ["weapons", "shields", "espionage", "counter_espionage",
                              "antigravity", "mining_efficiency"]
            if _settings.strike_enabled:        # SDD 49: árbol de misiles
                _research_list.append("rocketry")
            if _settings.drones_enabled:        # SDD 50: árbol de drones
                _research_list.append("dronework")
            for tk in _research_list:
                spec = content.technologies.get(tk, {})
                rt = spec.get("requires_tech")
                if tk in techs or (rt and rt not in techs):
                    continue
                if energy < spec.get("energy_cost", 0):
                    continue
                try:
                    from app.services.research import start_research
                    await start_research(session, player, tk)
                    return f"research {tk}"
                except Exception:   # costo/energía: probá otra cosa este turno
                    break
        if "barracks" not in keys and afford_building("barracks"):
            await start_build(session, player, base, "barracks")
            return "build barracks"
        if "factory" not in keys and afford_building("factory"):
            await start_build(session, player, base, "factory")
            return "build factory"

        # 2.5) SDD 49/50: SOLO el perfil 'raid' invierte en arsenal (los demás no se distraen del
        # ejército/economía → así llegan a entrenar flota y atacar). afford_building exige lab+tech.
        if prof.get("arsenal") and _settings.strike_enabled:
            if "launcher" not in keys and afford_building("launcher"):
                await start_build(session, player, base, "launcher")
                return "build launcher"
            if ("launcher" in active and units.get("sonic_missile", 0) < 8
                    and afford_units("sonic_missile", 4)):
                await start_training(session, player, base, "sonic_missile", 4)
                return "build sonic_missile x4"
        if prof.get("arsenal") and _settings.drones_enabled:
            if "drone_factory" not in keys and afford_building("drone_factory"):
                await start_build(session, player, base, "drone_factory")
                return "build drone_factory"
            if ("drone_factory" in active and units.get("recon_drone", 0) < 3
                    and afford_units("recon_drone", 2)):
                await start_training(session, player, base, "recon_drone", 2)
                return "build recon_drone x2"

        # 3) Defensa: mantené al menos `min_defense` torretas (turtle pide más). Gated por
        #    lab+weapons via afford_building.
        if turrets < prof.get("min_defense", 1) and afford_building("turret"):
            await start_build(session, player, base, "turret")
            return "build turret"

        # 4) Train: SDD 41 — jugá el META (la unidad con mejor win-rate, si hay datos y la podés
        #    fabricar); si no, el default tanks (factory) / soldiers (barracks).
        meta_unit = await _best_meta_unit(session)
        if (meta_unit and _unit_ready(meta_unit, active, content)
                and afford_units(meta_unit, 1)):
            await start_training(session, player, base, meta_unit, 1)
            return f"train {meta_unit} (meta)"
        if "factory" in active and afford_units("tank", 1):
            await start_training(session, player, base, "tank", 1)
            return "train tank"
        if "barracks" in active and afford_units("soldier", SOLDIER_BATCH):
            await start_training(session, player, base, "soldier", SOLDIER_BATCH)
            return f"train soldier x{SOLDIER_BATCH}"

        # 4.5) SDD 49/50: ablandá una base enemiga del MISMO planeta antes de la flota — lanzá
        # misiles (destruyen defensas) y/o un escuadrón de drones espía/ataque. Intra-planeta: el
        # objetivo debe estar en tu planeta. Best-effort: si falla, seguís con el turno normal.
        # SDD 61: recon orbital — si tiene satélite espía, mapear a un rival (best-effort).
        if _settings.satellites_enabled and units.get("spy_satellite", 0) > 0:
            _seen: set[int] = set()
            _rivals = []
            for b in await _enemy_bases(session, player):
                if b.player_id not in _seen:
                    _seen.add(b.player_id)
                    _rivals.append(await session.get(Player, b.player_id))
            if await _npc_launch_satellite(session, player, _rivals):
                return "launch spy satellite"

        same_planet = [b for b in await _enemy_bases(session, player)
                       if b.planet_key == player.planet_key]
        if _settings.strike_enabled and units.get("sonic_missile", 0) >= 4 and same_planet:
            try:
                n = min(units["sonic_missile"], 6)
                await start_strike(session, player, base.id, same_planet[0].id,
                                   {"sonic_missile": n})
                return f"strike base {same_planet[0].id} (soften)"
            except Exception:
                pass
        if _settings.drones_enabled and units.get("recon_drone", 0) >= 2 and same_planet:
            try:
                await launch_drones(session, player, base.id, same_planet[0].id,
                                    {"recon_drone": min(units["recon_drone"], 3)}, max_ticks=6)
                return f"drones recon base {same_planet[0].id}"
            except Exception:
                pass

        # 5) Attack: entre las bases que claramente superamos (poder > defensa × margin del PERFIL),
        #    pegale al objetivo estratégico; si no, al RIVAL más fuerte que batas —humano O NPC
        #    (los NPC ya no se cubren entre sí salvo que compartan alianza); si no, a la más débil.
        # SDD 62: con guarnición la flota sale de la base natal → el ejército disponible es el de
        # ESA base (no el global), para que el poder estimado coincida con lo enviable.
        src_base_id = base.id
        atk_pool = units
        if _settings.garrison_enabled:
            from app.services.training import units_at_base
            atk_pool = await units_at_base(session, player.id, base.id)
        army = {k: atk_pool[k] for k in ("soldier", "tank", "aircraft") if atk_pool.get(k)}
        my_power = _force_attack_power(army)
        if my_power > 0 and energy >= get_settings().attack_energy_cost:
            # SDD 55 §3.2: no patear al débil (dejar crecer al humano muy por debajo, anti-snowball)
            # + repartir la presión (no apilar varias flotas sobre el MISMO rival → rotar objetivo).
            my_score = await player_score(session, player)
            ratio = get_settings().npc_weak_protect_ratio
            already = {m.defender_id for m in await _my_outbound(session, player)}
            beatable = []
            for b in await _enemy_bases(session, player):
                if b.player_id in already:           # ya tengo flota yendo a ese rival → roto
                    continue
                defense = await _base_defense_estimate(session, b)
                if my_power > defense * margin:  # don't trade evenly (margin del perfil)
                    owner = await session.get(Player, b.player_id)
                    # no patear al débil: a un HUMANO muy por debajo mío lo dejo crecer.
                    if not owner.is_npc and ratio > 0 \
                            and await player_score(session, owner) < my_score * ratio:
                        continue
                    beatable.append((defense, owner, b))
            if beatable:
                targeted = [b for (_d, o, b) in beatable if o.id == player.npc_target_id]
                if targeted:  # SDD 29: respeta el objetivo de la postura estratégica
                    target = targeted[0]
                else:
                    # rival más fuerte que puedo batir (humano o NPC); empate → preferí humano.
                    scored = [(await player_score(session, o), (0 if o.is_npc else 1), b)
                              for (_d, o, b) in beatable]
                    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
                    target = scored[0][2]
                try:
                    await start_attack(session, player, target.id, army, src_base_id)
                    return f"attack base {target.id}"
                except CombatError:
                    pass   # garrison/topes SDD 55: si no se puede, seguí con el resto del turno

        # 6) Expansión/exploración (perfiles expand/opportunist): construí un transbordador, mandá
        #    expediciones a lunas y fundá colonias. Gated por el perfil para no distraer al resto.
        if prof.get("expedite"):
            if (units.get("shuttle", 0) < 1 and "factory" in active
                    and afford_units("shuttle", 1)):
                await start_training(session, player, base, "shuttle", 1)
                return "train shuttle (expand)"
            if units.get("shuttle", 0) >= 1:
                for moon_key, moon in content.moons.items():
                    if content.moon_galaxy(moon_key) != player.galaxy_key:
                        continue
                    if energy >= moon.get("expedition", {}).get("energy_cost", 0):
                        await start_expedition(session, player, moon_key)
                        return f"expedition to {moon_key}"
        if prof.get("colonize") and units.get("shuttle", 0) >= 1:
            try:                       # best-effort: si el mundo no es colonizable/falta tech, paso
                from app.services.colonization import found_colony
                for pk in content.planets:
                    if any(b.planet_key == pk for b in buildings):
                        continue       # ya tengo base ahí
                    await found_colony(session, player, pk, "surface")
                    return f"colonize {pk}"
            except Exception:
                pass

        # 7) Otherwise grow energy capacity.
        if "power_plant" not in keys and afford_building("power_plant"):
            await start_build(session, player, base, "power_plant")
            return "build power_plant"

        return None


async def _bases(session: AsyncSession, player: Player) -> list[Base_]:
    res = await session.execute(select(Base_).where(Base_.player_id == player.id))
    return list(res.scalars())


# --------------------------------------------------------------------------- #
# Shared action dispatcher (used by the LLM brain; validates then runs services)
# --------------------------------------------------------------------------- #
async def dispatch_action(session: AsyncSession, player: Player, action: dict) -> str | None:
    """Execute one structured action via the same services a human uses.

    Raises the service's domain error if the action is infeasible/invalid, so the
    caller can fall back to rules.
    """
    base = next((b for b in await _bases(session, player)), None)
    if base is None:
        return None
    kind = action.get("action")

    if kind == "build":
        key = action.get("building")
        mineral = action.get("mineral")
        await start_build(session, player, base, key, target_mineral=mineral)
        return f"llm build {key}{f' ({mineral})' if mineral else ''}"
    if kind == "train":
        unit = action.get("unit")
        qty = int(action.get("quantity", 1))
        await start_training(session, player, base, unit, qty)
        return f"llm train {unit} x{qty}"
    if kind == "attack":
        target = int(action["target_base_id"])
        force = {k: int(v) for k, v in (action.get("force") or {}).items() if int(v) > 0}
        await start_attack(session, player, target, force)
        return f"llm attack base {target}"
    if kind == "recall":
        await recall_mission(session, player, int(action["mission_id"]))
        return f"llm recall {action['mission_id']}"
    if kind == "expedition":
        await start_expedition(session, player, action["moon_key"])
        return f"llm expedition {action['moon_key']}"
    return None  # "none" / unknown -> no-op


async def _npc_state(session: AsyncSession, player: Player) -> dict:
    """Compact, model-friendly snapshot for the LLM, with affordable cost hints."""
    content = get_content()
    stocks = await player_stocks(session, player.id)
    units = await player_units(session, player.id)
    buildings = await _buildings(session, player)
    energy_now = _current_energy(player)
    active_bld = {b.building_key for b in buildings if b.status == "active"}

    # `affordable`: ¿se puede pagar AHORA (minerales+energía) y está el edificio requerido?
    # El LLM tiende a elegir lo que no puede pagar (→ fallback); marcarlo sube el ratio de jugadas
    # aplicadas (la afinación). El prompt le pide elegir SOLO opciones con affordable=true.
    # Solo opciones PAGABLES ahora (minerales+energía y edificio requerido). Pasarle al LLM solo lo
    # factible evita que el modelo (sobre todo los chicos) elija lo impagable → menos fallback.
    def _afford(cost, ecost, req):
        return (_can_afford(stocks, energy_now, cost, ecost)
                and (not req or req == "headquarters" or req in active_bld))
    build_options = {
        key: {"minerals": content.building_cost_in_minerals(player.race_key, key),
              "energy": spec.get("energy_cost", 0), "category": spec["category"]}
        for key, spec in content.buildings.items()
        if key != "headquarters" and _afford(
            content.building_cost_in_minerals(player.race_key, key),
            spec.get("energy_cost", 0), spec.get("requires"))
    }
    train_options = {
        key: {"minerals": content.unit_cost_in_minerals(player.race_key, key),
              "energy": spec.get("energy_cost", 0), "requires": spec.get("requires")}
        for key, spec in content.units.items()
        if _afford(content.unit_cost_in_minerals(player.race_key, key),
                   spec.get("energy_cost", 0), spec.get("requires"))
    }
    enemies = []
    for b in await _enemy_bases(session, player):
        owner = await session.get(Player, b.player_id)
        enemies.append(
            {
                "target_base_id": b.id,
                "is_human": not owner.is_npc,
                "is_target": owner.id == player.npc_target_id,  # SDD 29: objetivo estratégico
                "units": await player_units(session, b.player_id),
                "defense_estimate": round(await _base_defense_estimate(session, b), 1),
            }
        )

    incoming = [
        {
            "mission_id": m.id,
            "target_base_id": m.target_base_id,
            "arrives_at": m.arrives_at.isoformat(),
        }
        for m in await _incoming_attacks(session, player)
    ]
    my_missions = [
        {"mission_id": m.id, "target_base_id": m.target_base_id, "status": m.status}
        for m in await _my_outbound(session, player)
    ]
    reachable_moons = [
        k for k in content.moons if content.moon_galaxy(k) == player.galaxy_key
    ]

    return {
        "race": player.race_key,
        "planet": player.planet_key,
        "personality": content.races[player.race_key].get("personality", ""),
        "posture": player.npc_posture,  # SDD 29: estrategia vigente (sesga la decisión táctica)
        "energy": round(energy_now, 1),
        # ¿alcanza la energía para atacar / espiar? (evita elegir un ataque impagable → fallback)
        "can_attack": energy_now >= get_settings().attack_energy_cost,
        "minerals": {k: round(v, 1) for k, v in stocks.items()},
        "units": units,
        "my_buildings": [
            {"key": b.building_key, "status": b.status, "mineral": b.production_mineral}
            for b in buildings
        ],
        "build_options": build_options,
        "train_options": train_options,
        "enemies": enemies,
        "incoming_attacks": incoming,
        "my_missions": my_missions,
        "reachable_moons": reachable_moons,
        "recent_actions": _load_memory(player),
        "recent_battles": await _recent_battles(session, player),
    }


# --------------------------------------------------------------------------- #
# NPC memory (short-term, persisted on the Player row)
# --------------------------------------------------------------------------- #
MEMORY_LEN = 8


def _load_memory(player: Player) -> list[str]:
    try:
        return json.loads(player.npc_memory or "[]")
    except (ValueError, TypeError):
        return []


def _remember(player: Player, entry: str) -> None:
    mem = _load_memory(player)
    mem.append(entry)
    player.npc_memory = json.dumps(mem[-MEMORY_LEN:])


async def reflect_on_battle(
    session: AsyncSession, npc: Player, role: str, won: bool, opponent: str
) -> None:
    """SDD 29 §3.7 — reflexión post-batalla DETERMINISTA (sin GPU por batalla): el NPC anota el
    resultado en su memoria y **ajusta su postura** según cómo le fue. Así "aprende" del resultado:
    si lo atacaron y perdió → se hace defensivo; si ganó atacando → sigue presionando (raid); si
    falló un ataque → se repliega a crecer (expand). Lo llama el resolver de combate por batalla."""
    if not npc.is_npc:
        return
    verbo = ("gané" if won else "perdí")
    como = "defendiendo de" if role == "defender" else "atacando a"
    _remember(npc, f"{verbo} {como} {opponent}")
    if role == "defender" and not won:
        new_posture = "defensive"      # me reventaron en casa → proteger
    elif role == "attacker" and not won:
        new_posture = "expand"         # mi ataque falló → reagrupar economía
    elif role == "attacker" and won:
        new_posture = "raid"           # ganó atacando → seguir presionando
    else:
        new_posture = npc.npc_posture  # ganó defendiendo → mantener
    npc.npc_posture = new_posture
    try:
        strat = json.loads(npc.npc_strategy or "{}")
    except Exception:
        strat = {}
    strat["last_battle"] = {"role": role, "won": won, "opponent": opponent,
                            "posture": new_posture}
    npc.npc_strategy = json.dumps(strat)
    from app.services.journal import record
    await record(session, "npc_reflection", npc.id,
                 role=role, won=won, opponent=opponent, posture=new_posture)


async def _recent_battles(session: AsyncSession, player: Player) -> list[dict]:
    res = await session.execute(
        select(CombatLog)
        .where((CombatLog.attacker_id == player.id) | (CombatLog.defender_id == player.id))
        .order_by(CombatLog.created_at.desc())
        .limit(5)
    )
    out = []
    for log in res.scalars():
        role = "attacker" if log.attacker_id == player.id else "defender"
        won = log.outcome == role
        out.append({"role": role, "won": won, "outcome": log.outcome})
    return out


# --------------------------------------------------------------------------- #
# Strategic layer (SDD 29): periodic, scoreboard-aware posture
# --------------------------------------------------------------------------- #
# SDD 29 v2 — PERFILES de juego. Cada postura es un perfil que SESGA el cerebro por reglas (no solo
# el LLM): `margin` = cuánto poder de más exige para atacar (menor ⇒ ataca más fácil); flags activan
# tácticas (ejército primero, defensa primero, investigar primero, expediciones, colonizar, arsenal
# de misiles/drones). El selector determinista (`pick_posture_rules`) cambia de perfil según estado
# la IA "adapta" aunque no haya LLM. El LLM, si está, refina la elección.
PROFILES: dict[str, dict] = {
    # económico/expansivo: crecer; ataca solo con ventaja clara.
    "economy":     {"margin": 2.2, "min_defense": 1},
    "expand":      {"margin": 2.0, "min_defense": 1, "expedite": True, "colonize": True},
    # investigación: laboratorio + tech antes que lo militar.
    "research":    {"margin": 2.2, "min_defense": 1, "research_first": True},
    # ataque rápido: ejército primero y golpea apenas tiene ventaja mínima.
    "rush":        {"margin": 1.05, "min_defense": 1, "army_first": True},
    "aggressive":  {"margin": 1.1, "min_defense": 1, "army_first": True},
    # raider: ejército + arsenal de misiles/drones para ablandar y presionar.
    "raid":        {"margin": 1.2, "min_defense": 1, "army_first": True, "arsenal": True},
    # conservador/tortuga: muchas defensas, casi no ataca.
    "turtle":      {"margin": 3.0, "min_defense": 3, "defense_first": True},
    "defensive":   {"margin": 3.0, "min_defense": 3, "defense_first": True},
    # mixto (default): equilibrado.
    "opportunist": {"margin": 1.2, "min_defense": 1, "expedite": True},
}
POSTURES = set(PROFILES)


def _profile(player: Player) -> dict:
    return PROFILES.get(player.npc_posture, PROFILES["opportunist"])


def _load_strategy(player: Player) -> dict:
    try:
        return json.loads(player.npc_strategy or "{}")
    except (ValueError, TypeError):
        return {}


def _strategy_due(player: Player, now: datetime, interval: int) -> bool:
    last = player.npc_strategy_updated_at
    if last is None:
        return True
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    return (now - last).total_seconds() >= interval


async def npc_scoreboard(session: AsyncSession, player: Player) -> list[dict]:
    """Ranking de la galaxia de la NPC (SDD 8/12), con `delta` de score vs la última evaluación —
    para inferir 'cómo vienen los demás'. Excluye a la propia NPC."""
    res = await session.execute(
        select(Player).where(Player.galaxy_key == player.galaxy_key, Player.id != player.id)
    )
    prev = _load_strategy(player).get("scores", {})
    scored = [(await player_score(session, p), p) for p in res.scalars()]
    scored.sort(key=lambda x: x[0], reverse=True)
    board = []
    for rank, (score, p) in enumerate(scored, start=1):
        board.append(
            {
                "id": p.id,
                "name": p.username,
                "is_human": not p.is_npc,
                "score": score,
                "rank": rank,
                "delta": score - int(prev.get(p.username, score)),
                "is_leader": rank == 1,
            }
        )
    return board


async def _llm_strategy(state: dict) -> dict:
    """LLM estratégico: lee scoreboard+recursos y elige una postura ({posture,target,why})."""
    settings = get_settings()
    user = state.pop("__user", None)
    model = state.pop("__model", None) or (settings.npc_llm_model or None)  # gpu/cloud por NPC
    system = (
        "You are the STRATEGIST of an NPC race in a turn-based space strategy game. "
        f"Stay in character: {state.get('personality', '')} "
        "Analyze the scoreboard (others' score and growth `delta`) and your own resources/score. "
        "Choose ONE posture for the next while: "
        "'aggressive' (hunt a rival, prefer the leading or fastest-growing human), "
        "'raid' (hit weak rich neighbors), 'defensive' (you are weak/threatened), "
        "'expand' (grow economy), or 'opportunist' (mixed). "
        "If a human clearly leads or grows much faster than you, lean aggressive against them. "
        "If you are weak or under threat, go defensive. "
        'Respond with ONLY JSON: {"posture":"<one>","target":"<rival name|null>","why":"<short>"}.'
    )
    content = await llm_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(state)},
        ],
        max_tokens=settings.npc_strategy_max_tokens,
        json_mode=settings.llm_json_mode,
        user=user,
        kind="npc",
        model=model,
        timeout=settings.npc_llm_timeout_seconds,
    )
    return _extract_json(content)


async def _beatable_targets(session: AsyncSession, player: Player, margin: float) -> list:
    """Bases enemigas alcanzables que la NPC claramente supera (poder propio > defensa × margin)."""
    units = await player_units(session, player.id)
    army = {k: units.get(k, 0) for k in ("soldier", "tank", "aircraft") if units.get(k)}
    my_power = _force_attack_power(army)
    if my_power <= 0:
        return []
    out = []
    for b in await _enemy_bases(session, player):
        if my_power > await _base_defense_estimate(session, b) * margin:
            out.append(b)
    return out


async def pick_posture_rules(session: AsyncSession, player: Player) -> str:
    """Selector de PERFIL DETERMINISTA (sin LLM): mira amenazas, economía, ejército y rivales y
    elige el perfil que mejor encaja AHORA. Es lo que hace que la IA 'adapte' su forma de jugar a
    lo largo de la partida aunque no haya modelo. El LLM, si está, puede refinarlo después."""
    content = get_content()
    # 1) bajo ataque o me reventaron defendiendo → conservador.
    if await _incoming_attacks(session, player):
        return "turtle"
    recent = await _recent_battles(session, player)
    if any(r["role"] == "defender" and not r["won"] for r in recent):
        return "turtle"

    from app.services.research import researched_techs
    buildings = await _buildings(session, player)
    active = {b.building_key for b in buildings if b.status == "active"}
    units = await player_units(session, player.id)
    techs = await researched_techs(session, player.id)

    # 2) juego temprano (poca infraestructura) → crecer economía.
    if len(active) < 4:
        return "economy"

    # 3) si tengo ejército y un objetivo que claramente supero → atacar (raid si tengo arsenal).
    army_power = _force_attack_power({k: units.get(k, 0) for k in ("soldier", "tank", "aircraft")})
    if army_power > 0 and await _beatable_targets(session, player, 1.2):
        has_arsenal = bool(units.get("sonic_missile") or units.get("recon_drone")
                           or "launcher" in active or "drone_factory" in active)
        return "raid" if has_arsenal else "rush"

    # 4) laboratorio pero pocas tech → investigar.
    if "research_lab" in active and len(techs) < max(1, len(content.technologies) // 2):
        return "research"

    # 5) si puedo expandirme (transbordador para expediciones/colonias) → expandir/explorar.
    if "factory" in active and (units.get("shuttle", 0) >= 1 or "antigravity" in techs):
        return "expand"

    # 6) tengo músculo pero nadie fácil a quién pegarle → seguí creciendo el ejército (rush latent)
    if "factory" in active or "barracks" in active:
        return "rush"
    return "opportunist"


async def decide_strategy(
    session: AsyncSession, player: Player, *, now: datetime | None = None, strategize=None
) -> str:
    """Recalcula (cada tanto) la postura estratégica leyendo el scoreboard. Devuelve la postura
    vigente. Ante cualquier fallo (sin LLM, red, JSON inválido) MANTIENE la postura previa."""
    settings = get_settings()
    if not settings.npc_strategy_enabled:
        return player.npc_posture
    now = now or datetime.now(UTC)
    if not _strategy_due(player, now, settings.npc_strategy_interval_seconds):
        return player.npc_posture
    strategize = strategize or _llm_strategy
    # Base DETERMINISTA: elegí el perfil según el estado (funciona SIN LLM → la IA adapta igual).
    if strategize is _llm_strategy and not settings.llm_key:
        try:
            posture = await pick_posture_rules(session, player)
            board = await npc_scoreboard(session, player)
            humans = [b for b in board if b["is_human"]]
            target = (humans or board or [None])[0]
            player.npc_posture = posture
            player.npc_target_id = target["id"] if target else None
            player.npc_strategy_updated_at = now
            player.npc_strategy = json.dumps(
                {"why": "rules", "scores": {b["name"]: b["score"] for b in board}}
            )
            await session.commit()
            return posture
        except Exception:
            await session.rollback()
            return (await session.get(Player, player.id)).npc_posture

    pid = player.id
    try:
        board = await npc_scoreboard(session, player)
        state = {
            "personality": get_content().races.get(player.race_key, {}).get("personality", ""),
            "my_score": await player_score(session, player),
            "my_minerals": await player_stocks(session, player.id),
            "my_units": await player_units(session, player.id),
            "previous_posture": player.npc_posture,
            "scoreboard": board,
            "under_attack": bool(await _incoming_attacks(session, player)),
            "meta": await _meta_for_npc(session),   # SDD 41: que la NPC juegue el meta aprendido
            "__user": f"npc:{player.username}",
            "__model": npc_llm_choice(player)[0],   # gpu/cloud por NPC (comparación)
        }
        out = await strategize(state)
        posture = str(out.get("posture", "")).strip()
        if posture not in POSTURES:
            return player.npc_posture
        target_name = out.get("target")
        target_id = next((b["id"] for b in board if b["name"] == target_name), None)
        player.npc_posture = posture
        player.npc_target_id = target_id
        player.npc_strategy = json.dumps(
            {"why": str(out.get("why", ""))[:200], "scores": {b["name"]: b["score"] for b in board}}
        )
        player.npc_strategy_updated_at = now
        await session.commit()
        return posture
    except Exception:
        await session.rollback()
        fresh = await session.get(Player, pid)
        return fresh.npc_posture if fresh else "opportunist"


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return json.loads(match.group(0) if match else text)


async def _llm_decide(state: dict) -> dict:
    """Call the configured OpenAI-compatible LLM and return the chosen action dict.

    Works with OpenRouter, LiteLLM, Ollama or vLLM — they all speak the same
    /chat/completions schema; only LLM_BASE_URL/LLM_MODEL/LLM_API_KEY change.
    """
    settings = get_settings()
    personality = state.get("personality", "")
    system = (
        "You are an AI playing a turn-based space strategy game as an NPC race. "
        f"Stay in character: {personality} "
        "Use recent_actions/recent_battles for continuity and react to incoming_attacks "
        "(build a turret to defend, or recall a fleet from my_missions). Only attack an enemy "
        "your force clearly outguns; among those, prefer a human rival (enemies[].is_human=true) "
        "over an NPC, to gang up on the leading player. "
        "Honor your `posture`: 'aggressive'/'raid' -> prioritize attacking a beatable enemy "
        "(prefer enemies[].is_target=true, then is_human=true); 'defensive' -> turret/recall; "
        "'expand' -> mines/buildings/expedition. "
        "CRITICAL: `build_options`/`train_options` already list ONLY what you can afford now; "
        "pick a build/train ONLY from those keys. If both are empty, do NOT build/train — choose "
        "another action or {\"action\":\"none\"}. Only `attack` if `can_attack` is true. Check "
        "`recent_actions` and do NOT repeat a move that just failed. "
        "Given your state, choose exactly ONE affordable action consistent with your personality. "
        'Respond with ONLY JSON, one of: '
        '{"action":"build","building":"<key>","mineral":"<key|null>"} (mineral only for a mine), '
        '{"action":"train","unit":"<key>","quantity":<int>}, '
        '{"action":"attack","target_base_id":<int>,"force":{"soldier":<int>,"tank":<int>}}, '
        '{"action":"recall","mission_id":<int>}, '
        '{"action":"expedition","moon_key":"<key>"}, '
        'or {"action":"none"}. '
        # Few-shot: shape the kind of decisions we want (format + priorities).
        'Examples: no mine yet and minerals available -> '
        '{"action":"build","building":"mine","mineral":"iron"}. '
        'incoming_attacks present and a fleet in my_missions -> '
        '{"action":"recall","mission_id":12}. '
        'a beatable enemy with is_human=true -> '
        '{"action":"attack","target_base_id":7,"force":{"tank":5}}.'
    )
    user = state.pop("__user", None)  # SDD 28: atribución por usuario (no va en el prompt)
    model = state.pop("__model", None) or (settings.npc_llm_model or None)  # gpu/cloud por NPC
    content = await llm_chat(
        [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(state)},
        ],
        max_tokens=120,
        json_mode=settings.llm_json_mode,
        user=user,
        kind="npc",
        model=model,
        timeout=settings.npc_llm_timeout_seconds,
    )
    return _extract_json(content)


def _fallback_reason(exc: Exception) -> str:
    """Categoría gruesa del fallo (para medir si aprende): energy|infeasible|parse|llm."""
    msg = str(exc).lower()
    if "energ" in msg:
        return "energy"
    if "json" in msg or isinstance(exc, (ValueError, KeyError)):
        return "parse"
    if type(exc).__name__.endswith("Error"):
        return "infeasible"   # BuildError/TrainingError/CombatError… acción no aplicable
    return "llm"              # red/timeout u otro


def npc_llm_choice(player: Player) -> tuple[str | None, str]:
    """Qué LLM usa ESTE NPC: si su username == npc_cloud_username → modelo de NUBE (backend
    'cloud'); si no → GPU local (backend 'gpu'). Para comparar quién juega mejor (SDD 19 §9)."""
    s = get_settings()
    if s.npc_cloud_username and player.username == s.npc_cloud_username:
        return (s.npc_cloud_model or None, "cloud")
    return (s.npc_llm_model or None, "gpu")


class LlmBrain:
    """Optional LLM-backed brain over any OpenAI-compatible server (OpenRouter, LiteLLM,
    Ollama, vLLM). Falls back to rules on ANY failure (no key/url, network error, rate
    limit, bad JSON, infeasible action) so a tick never breaks.

    `decide` is injectable for testing (defaults to the real LLM call)."""

    def __init__(self, decide=None) -> None:
        self._decide = decide or _llm_decide
        self._fallback = RuleBasedBrain()

    async def act(self, session: AsyncSession, player: Player) -> str | None:
        settings = get_settings()
        if not settings.llm_key and self._decide is _llm_decide:
            return await self._fallback.act(session, player)
        player_id = player.id  # capture before any rollback expires the instance
        model, backend = npc_llm_choice(player)   # GPU local vs nube por NPC (comparación)
        action = None
        try:
            state = await _npc_state(session, player)
            state["__user"] = f"npc:{player.username}"  # SDD 28: atribución de uso LLM por NPC
            state["__model"] = model                    # qué modelo usa ESTE NPC (gpu/cloud)
            # CLAVE (perf): cerrar la transacción ANTES de la llamada lenta al LLM/GPU. Si no, la
            # conexión queda "idle in transaction" reteniendo snapshot/locks durante los ~20-30s de
            # la GPU y, con varios NPCs, el tick cuelga el juego ~2 min. Decidimos SIN transacción
            # abierta y aplicamos después en una transacción corta.
            await session.commit()
            action = await self._decide(state)
            player = await session.get(Player, player_id)  # re-cargar tras el commit
            result = await dispatch_action(session, player, action)
            metrics.NPC_DECISIONS.inc(outcome="llm", backend=backend)   # el LLM decidió y se aplicó
            from app.services.journal import record as _rec
            await _rec(session, "npc_decision", player_id, outcome="llm", backend=backend)
            return result
        except Exception as exc:
            # Any failure (network, rate limit, bad JSON, infeasible action) -> rules.
            # Logueamos el motivo (antes era silencioso → no se sabía por qué la IA caía a reglas).
            logging.getLogger("npc").warning(
                "NPC %s (backend=%s) fallback a reglas: %s: %s",
                getattr(player, "username", player_id), backend, type(exc).__name__, exc,
            )
            metrics.NPC_DECISIONS.inc(outcome="fallback", backend=backend)
            metrics.NPC_FALLBACK_REASON.inc(reason=_fallback_reason(exc))
            await session.rollback()
            player = await session.get(Player, player_id)  # fresh after rollback
            # APRENDIZAJE: la NPC recuerda QUÉ intentó y por qué falló → el próximo prompt lo trae
            # en `recent_actions` y el modelo evita repetir la jugada inviable (ej. sin energía).
            tried = (action or {}).get("action", "?") if isinstance(action, dict) else "?"
            _remember(player, f"intento LLM '{tried}' falló: {str(exc)[:80]}")
            from app.services.journal import record as _rec
            await _rec(session, "npc_decision", player_id, outcome="fallback",
                       backend=backend, reason=_fallback_reason(exc))
            return await self._fallback.act(session, player)


def get_brain() -> NpcBrain:
    return LlmBrain() if get_settings().npc_brain == "llm" else RuleBasedBrain()


# --------------------------------------------------------------------------- #
# Turn runner
# --------------------------------------------------------------------------- #
async def run_npc_turn(session: AsyncSession, player: Player) -> str | None:
    """Advance the NPC's state, let its brain act, and record the action in memory."""
    await advance(session, player)  # brings economy/queues up to date (commits internally)
    await decide_strategy(session, player)  # SDD 29: refresca la postura cada tanto (scoreboard)
    action = await get_brain().act(session, player)
    # Re-fetch (act() may have rolled back/replaced the instance) before writing memory.
    player = await session.get(Player, player.id)
    _remember(player, action or "idle")
    # Métrica: qué hizo la IA (primer token del action: build/train/attack/research/...).
    verb = (action or "idle").split()[0] if (action or "idle").strip() else "idle"
    metrics.NPC_ACTIONS.inc(action=verb, brain=get_settings().npc_brain)
    return action
