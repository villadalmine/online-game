"""NPC (AI-controlled) races.

Design: a pluggable `NpcBrain` decides ONE action per tick for an NPC, executed
through the SAME services a human uses (build/train/attack). The default
`RuleBasedBrain` is deterministic, cheap and dependency-free. `LlmBrain` is an
optional OpenRouter-backed brain behind the same interface, with a hard fallback
to rules — so the game never depends on the network to take an NPC turn.
"""
import json
import re
from datetime import UTC, datetime
from typing import Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.core.security import hash_password
from app.models import AttackMission, Base_, Building, CombatLog, Player
from app.services.build import start_build
from app.services.combat import recall_mission, start_attack
from app.services.economy import player_stocks
from app.services.energy import compute_energy
from app.services.expedition import start_expedition
from app.services.onboarding import onboard_player
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
    alliance = (
        await session.execute(select(Alliance).where(Alliance.name == NPC_ALLIANCE_NAME))
    ).scalar_one_or_none()
    if alliance is None:
        alliance = Alliance(name=NPC_ALLIANCE_NAME, tag=NPC_ALLIANCE_TAG, leader_id=npcs[0].id)
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
        player.energy, player.energy_updated_at, now, s.energy_regen_per_hour, s.energy_max
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

        def afford_building(key: str) -> bool:
            spec = content.buildings[key]
            cost = content.building_cost_in_minerals(player.race_key, key)
            return _can_afford(stocks, energy, cost, spec.get("energy_cost", 0))

        def afford_units(unit_key: str, qty: int) -> bool:
            unit_cost = content.unit_cost_in_minerals(player.race_key, unit_key)
            cost = {m: a * qty for m, a in unit_cost.items()}
            e = content.units[unit_key].get("energy_cost", 0) * qty
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

        # 2) Military buildings: barracks, then a factory for heavy units.
        if "barracks" not in keys and afford_building("barracks"):
            await start_build(session, player, base, "barracks")
            return "build barracks"
        if "barracks" in active and "factory" not in keys and afford_building("factory"):
            await start_build(session, player, base, "factory")
            return "build factory"

        # 3) Baseline defense: keep at least one turret.
        if turrets == 0 and afford_building("turret"):
            await start_build(session, player, base, "turret")
            return "build turret"

        # 4) Train: prefer tanks (factory), else soldiers (barracks).
        if "factory" in active and afford_units("tank", 1):
            await start_training(session, player, base, "tank", 1)
            return "train tank"
        if "barracks" in active and afford_units("soldier", SOLDIER_BATCH):
            await start_training(session, player, base, "soldier", SOLDIER_BATCH)
            return f"train soldier x{SOLDIER_BATCH}"

        # 5) Attack the WEAKEST reachable base, only if we clearly outgun its defense.
        army = {k: units[k] for k in ("soldier", "tank") if units.get(k)}
        my_power = _force_attack_power(army)
        if my_power > 0 and energy >= get_settings().attack_energy_cost:
            targets = await _enemy_bases(session, player)
            scored = [(await _base_defense_estimate(session, b), b) for b in targets]
            scored.sort(key=lambda x: x[0])
            if scored:
                defense, target = scored[0]
                if my_power > defense * ATTACK_POWER_MARGIN:  # don't trade evenly
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

    build_options = {
        key: {
            "minerals": content.building_cost_in_minerals(player.race_key, key),
            "energy": spec.get("energy_cost", 0),
            "category": spec["category"],
        }
        for key, spec in content.buildings.items()
        if key != "headquarters"
    }
    train_options = {
        key: {
            "minerals": content.unit_cost_in_minerals(player.race_key, key),
            "energy": spec.get("energy_cost", 0),
            "requires": spec.get("requires"),
        }
        for key, spec in content.units.items()
    }
    enemies = []
    for b in await _enemy_bases(session, player):
        enemies.append(
            {
                "target_base_id": b.id,
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


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    return json.loads(match.group(0) if match else text)


async def _openrouter_decide(state: dict) -> dict:
    """Call OpenRouter and return the chosen action dict."""
    settings = get_settings()
    personality = state.get("personality", "")
    system = (
        "You are an AI playing a turn-based space strategy game as an NPC race. "
        f"Stay in character: {personality} "
        "Use recent_actions/recent_battles for continuity and react to incoming_attacks "
        "(build a turret to defend, or recall a fleet from my_missions). Attack the enemy "
        "with the lowest defense_estimate, and only if your force clearly outguns it. "
        "Given your state, choose exactly ONE affordable action consistent with your personality. "
        'Respond with ONLY JSON, one of: '
        '{"action":"build","building":"<key>","mineral":"<key|null>"} (mineral only for a mine), '
        '{"action":"train","unit":"<key>","quantity":<int>}, '
        '{"action":"attack","target_base_id":<int>,"force":{"soldier":<int>,"tank":<int>}}, '
        '{"action":"recall","mission_id":<int>}, '
        '{"action":"expedition","moon_key":"<key>"}, '
        'or {"action":"none"}.'
    )
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{settings.openrouter_base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "X-Title": "online-game-npc",
            },
            json={
                "model": settings.openrouter_model,
                "temperature": 0,
                "max_tokens": 120,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(state)},
                ],
            },
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
    return _extract_json(content)


class LlmBrain:
    """Optional OpenRouter-backed brain. Falls back to rules on ANY failure (no key,
    network error, rate limit, bad JSON, infeasible action) so a tick never breaks.

    `decide` is injectable for testing (defaults to the real OpenRouter call)."""

    def __init__(self, decide=None) -> None:
        self._decide = decide or _openrouter_decide
        self._fallback = RuleBasedBrain()

    async def act(self, session: AsyncSession, player: Player) -> str | None:
        settings = get_settings()
        if not settings.openrouter_api_key and self._decide is _openrouter_decide:
            return await self._fallback.act(session, player)
        player_id = player.id  # capture before any rollback expires the instance
        try:
            state = await _npc_state(session, player)
            action = await self._decide(state)
            return await dispatch_action(session, player, action)
        except Exception:
            # Any failure (network, rate limit, bad JSON, infeasible action) -> rules.
            await session.rollback()
            player = await session.get(Player, player_id)  # fresh after rollback
            return await self._fallback.act(session, player)


def get_brain() -> NpcBrain:
    return LlmBrain() if get_settings().npc_brain == "llm" else RuleBasedBrain()


# --------------------------------------------------------------------------- #
# Turn runner
# --------------------------------------------------------------------------- #
async def run_npc_turn(session: AsyncSession, player: Player) -> str | None:
    """Advance the NPC's state, let its brain act, and record the action in memory."""
    await advance(session, player)  # brings economy/queues up to date (commits internally)
    action = await get_brain().act(session, player)
    # Re-fetch (act() may have rolled back/replaced the instance) before writing memory.
    player = await session.get(Player, player.id)
    _remember(player, action or "idle")
    return action
