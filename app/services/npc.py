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
from app.services.combat import recall_mission, start_attack
from app.services.economy import player_stocks
from app.services.energy import compute_energy
from app.services.expedition import start_expedition
from app.services.llm import llm_chat
from app.services.onboarding import onboard_player
from app.services.physics import effective_energy_regen
from app.services.scoring import player_score
from app.services.state import advance
from app.services.training import player_units, start_training

SOLDIER_BATCH = 3
ATTACK_POWER_MARGIN = 1.2  # only attack if our attack power exceeds defense by this factor


# --------------------------------------------------------------------------- #
# NPC provisioning
# --------------------------------------------------------------------------- #
NPC_ALLIANCE_NAME = "Consorcio Estelar"
NPC_ALLIANCE_TAG = "AI"


async def ensure_npcs(session: AsyncSession) -> int:
    """Create one NPC per race (onboarded to its home planet) if missing, and keep all
    NPCs in a shared alliance (they cooperate and don't fight each other)."""
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
    await _ensure_npc_alliance(session)
    await session.commit()
    return created


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
        s.energy_max,
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


async def _base_defense_estimate(session: AsyncSession, base: Base_) -> float:
    """Defender unit defense + active turret power at a base (what an attacker faces)."""
    content = get_content()
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

        def afford_units(unit_key: str, qty: int) -> bool:
            spec = content.units[unit_key]
            if not _gated(spec):
                return False
            unit_cost = content.unit_cost_in_minerals(player.race_key, unit_key)
            cost = {m: a * qty for m, a in unit_cost.items()}
            e = spec.get("energy_cost", 0) * qty
            return _can_afford(stocks, energy, cost, e)

        # 0) THREAT RESPONSE: under attack -> recall a roaming fleet, then fortify.
        if await _incoming_attacks(session, player):
            outbound = await _my_outbound(session, player)
            if outbound:
                await recall_mission(session, player, outbound[0].id)
                return "recall fleet to defend"
            if turrets < 3 and afford_building("turret"):
                await start_build(session, player, base, "turret")
                return "build turret (under attack)"

        # 1) Economy: mines for the race's core minerals.
        for mineral in (structural, energetic):
            if mineral not in mines and afford_building("mine"):
                await start_build(session, player, base, "mine", target_mineral=mineral)
                return f"build mine ({mineral})"

        # 2) Ciencia + industria (árbol de tech): laboratorio → investigar → fábrica.
        if "research_lab" not in keys and afford_building("research_lab"):
            await start_build(session, player, base, "research_lab")
            return "build research_lab"
        if "research_lab" in active:   # investigar lo que habilita defensa/industria/expansión
            for tk in ("weapons", "shields", "espionage", "counter_espionage",
                       "antigravity", "mining_efficiency"):
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

        # 3) Baseline defense: keep at least one turret (gated por lab+weapons via afford_building).
        if turrets == 0 and afford_building("turret"):
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

        # 5) Attack: among the bases we clearly outgun, coordinate against the strongest
        #    HUMAN rival (NPCs gang up on the leading player); else hit the weakest base.
        army = {k: units[k] for k in ("soldier", "tank") if units.get(k)}
        my_power = _force_attack_power(army)
        if my_power > 0 and energy >= get_settings().attack_energy_cost:
            beatable = []
            for b in await _enemy_bases(session, player):
                defense = await _base_defense_estimate(session, b)
                if my_power > defense * ATTACK_POWER_MARGIN:  # don't trade evenly
                    owner = await session.get(Player, b.player_id)
                    beatable.append((defense, owner, b))
            if beatable:
                targeted = [b for (_d, o, b) in beatable if o.id == player.npc_target_id]
                humans = [t for t in beatable if not t[1].is_npc]
                if targeted:  # SDD 29: respeta el objetivo de la postura estratégica
                    target = targeted[0]
                elif humans:
                    scored = [(await player_score(session, o), b) for (_d, o, b) in humans]
                    scored.sort(key=lambda x: x[0], reverse=True)  # strongest rival first
                    target = scored[0][1]
                else:
                    beatable.sort(key=lambda x: x[0])  # weakest reachable base
                    target = beatable[0][2]
                await start_attack(session, player, target.id, army)
                return f"attack base {target.id}"

        # 6) Economy/boon: send a shuttle expedition if possible.
        if units.get("shuttle", 0) >= 1:
            for moon_key, moon in content.moons.items():
                if content.moon_galaxy(moon_key) != player.galaxy_key:
                    continue
                if energy >= moon.get("expedition", {}).get("energy_cost", 0):
                    await start_expedition(session, player, moon_key)
                    return f"expedition to {moon_key}"

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
        "energy": round(_current_energy(player), 1),
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
POSTURES = {"aggressive", "defensive", "expand", "raid", "opportunist"}


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
        model=model,
        timeout=settings.npc_llm_timeout_seconds,
    )
    return _extract_json(content)


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
    if strategize is _llm_strategy and not settings.llm_key:
        return player.npc_posture  # sin LLM, no estrategia LLM (mantiene postura/reglas)

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
        "another action or {\"action\":\"none\"}. Check `recent_actions` and do NOT repeat a move "
        "that just failed. "
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
