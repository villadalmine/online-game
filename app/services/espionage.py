"""Espionaje e inteligencia (SDD 35).

Mandás espías a un objetivo; al llegar resuelven y generan un IntelReport (info graduada según la
profundidad lograda); vuelven, y si los detectan caen algunos + se avisa al defensor.

`resolve_spy()` es puro/determinista (testeable sin DB). El resto despacha/resuelve la misión
con el mismo patrón que el combate (viaje → resolver al llegar → volver)."""
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, IntelReport, Player, SpyMission
from app.services.combat import travel_seconds
from app.services.economy import player_stocks
from app.services.effects import multiplier
from app.services.energy import spend_energy
from app.services.notifications import notify
from app.services.physics import effective_energy_regen
from app.services.scoring import player_score
from app.services.training import get_or_create_unit_stock, player_units


class SpyError(Exception):
    pass


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _power(force: dict[str, int], stat: str) -> float:
    content = get_content()
    return sum(
        q * content.units.get(k, {}).get("stats", {}).get(stat, 0) for k, q in force.items()
    )


@dataclass
class SpyResult:
    depth: float          # 0..1: profundidad/precisión de la intel
    detect_prob: float    # 0..1: cuota del defensor (= prob. de detección / bajas)


def resolve_spy(spy_power: float, counter_power: float) -> SpyResult:
    """Puro: depth = spy/(spy+counter). Sin defensa ⇒ intel total. Los multiplicadores se aplican
    afuera (ya vienen en spy_power/counter_power)."""
    total = spy_power + counter_power
    if total <= 0:
        return SpyResult(1.0, 0.0)
    return SpyResult(spy_power / total, counter_power / total)


def _blur(value: float, depth: float):
    """Exacto si la profundidad es alta; si no, un rango (más ancho cuanto menos profundidad)."""
    if depth >= 0.95:
        return round(value)
    err = max(0.05, 1.0 - depth)
    return [max(0, round(value * (1 - err))), round(value * (1 + err))]


async def _counter_power(session: AsyncSession, target: Player) -> float:
    """Defensa de espionaje del objetivo: sus espías (stat spy) + edificios counter_intel."""
    content = get_content()
    units = await player_units(session, target.id)
    base_power = _power(units, "spy")
    res = await session.execute(
        select(Building)
        .join(Base_, Building.base_id == Base_.id)
        .where(Base_.player_id == target.id)
    )
    building_power = 0.0
    for b in res.scalars():
        if b.status == "active":
            building_power += content.buildings.get(b.building_key, {}).get("counter_power", 0)
    return base_power + building_power


async def graded_payload(session: AsyncSession, target: Player, depth: float) -> dict:
    """Qué se revela del objetivo según `depth` (ofuscación: rangos en vez de exactos)."""
    payload: dict = {"score": await player_score(session, target)}  # siempre visible
    if depth < 0.25:
        return payload  # sólo presencia/score público
    units = await player_units(session, target.id)
    payload["army_attack"] = _blur(_power(units, "attack"), depth)
    payload["army_defense"] = _blur(_power(units, "defense"), depth)
    if depth >= 0.5:
        stocks = await player_stocks(session, target.id)
        payload["minerals_total"] = _blur(sum(stocks.values()), depth)
    if depth >= 0.6:
        res = await session.execute(
            select(Building).join(Base_, Building.base_id == Base_.id).where(
                Base_.player_id == target.id
            )
        )
        bs = list(res.scalars())
        payload["buildings"] = sorted({b.building_key for b in bs})
        payload["turrets"] = sum(1 for b in bs if b.building_key == "turret")
    if depth >= 0.8:
        payload["units"] = units  # conteo (casi) exacto
    return payload


def intel_confidence(report: IntelReport, now: datetime | None = None) -> float:
    """confianza = depth · decaimiento por antigüedad (half-life configurable)."""
    now = now or datetime.now(UTC)
    hl = get_settings().intel_confidence_half_life_seconds
    age = max(0.0, (now - _aware(report.as_of)).total_seconds())
    decay = 0.5 ** (age / hl) if hl > 0 else 1.0
    return round(report.depth * decay, 3)


async def start_spy(
    session: AsyncSession, observer: Player, target_base_id: int, spies: dict[str, int]
) -> SpyMission:
    settings = get_settings()
    now = datetime.now(UTC)
    base = await session.get(Base_, target_base_id)
    if base is None:
        raise SpyError("Base objetivo no encontrada.")
    if base.player_id == observer.id:
        raise SpyError("No podés espiarte a vos mismo.")
    target = await session.get(Player, base.player_id)
    if not observer.is_npc and not target.is_npc and \
            observer.galaxy_instance_id != target.galaxy_instance_id:
        raise SpyError("Ese jugador está en otra galaxia.")

    spies = {k: int(q) for k, q in spies.items() if k == "spy" and q and int(q) > 0}
    if not spies:
        raise SpyError("Tenés que enviar al menos 1 espía.")
    have = (await player_units(session, observer.id)).get("spy", 0)
    if have < spies["spy"]:
        raise SpyError(f"No tenés suficientes espías (tenés {have}).")

    if not spend_energy(
        observer, settings.spy_energy_cost, now,
        effective_energy_regen(observer, settings), settings.energy_max,
    ):
        raise SpyError("Energía insuficiente para espiar.")

    stock = await get_or_create_unit_stock(session, observer.id, "spy")
    stock.quantity -= spies["spy"]  # los espías salen del stock mientras viajan

    travel = travel_seconds(observer.planet_key, target.planet_key)
    mission = SpyMission(
        observer_id=observer.id,
        target_id=target.id,
        target_base_id=target_base_id,
        force=json.dumps(spies),
        status="outbound",
        arrives_at=now + timedelta(seconds=travel),
    )
    session.add(mission)
    await session.flush()
    return mission


async def _save_intel(session: AsyncSession, observer_id: int, target_id: int,
                      depth: float, payload: dict, now: datetime) -> None:
    res = await session.execute(
        select(IntelReport).where(
            IntelReport.observer_id == observer_id, IntelReport.target_id == target_id
        )
    )
    report = res.scalar_one_or_none()
    if report is None:
        report = IntelReport(observer_id=observer_id, target_id=target_id)
        session.add(report)
    report.depth = depth
    report.payload = json.dumps(payload)
    report.as_of = now


async def process_spy_missions(
    session: AsyncSession, now: datetime | None = None, observer_id: int | None = None
) -> int:
    """Resuelve espionajes que llegaron (genera intel) y devuelve los espías que vuelven."""
    now = now or datetime.now(UTC)
    conds = [SpyMission.status.in_(("outbound", "returning"))]
    if observer_id is not None:
        conds.append(SpyMission.observer_id == observer_id)
    res = await session.execute(select(SpyMission).where(*conds))
    processed = 0
    for m in res.scalars():
        if m.status == "outbound" and _aware(m.arrives_at) <= now:
            observer = await session.get(Player, m.observer_id)
            target = await session.get(Player, m.target_id)
            force = json.loads(m.force)
            esp = await multiplier(session, observer.id, "espionage", now)
            spy_power = _power(force, "spy") * esp
            counter = await _counter_power(session, target) * await multiplier(
                session, target.id, "counter_espionage", now
            )
            r = resolve_spy(spy_power, counter)
            payload = await graded_payload(session, target, r.depth)
            await _save_intel(session, observer.id, target.id, round(r.depth, 3), payload, now)
            sent = force.get("spy", 0)
            lost = min(sent, round(sent * r.detect_prob))
            survivors = sent - lost
            if r.detect_prob >= 0.5 and not target.is_npc:
                await notify(
                    session, target.id, "spy_detected",
                    f"⚠ Detectaste espionaje de {observer.username} (cayeron {lost}).",
                    {"from": observer.username, "lost": lost},
                )
            m.details = json.dumps({"depth": round(r.depth, 3), "detected": r.detect_prob >= 0.5,
                                    "lost": lost})
            m.force = json.dumps({"spy": survivors} if survivors else {})
            travel = travel_seconds(observer.planet_key, target.planet_key)
            m.status = "returning"
            m.returns_at = now + timedelta(seconds=travel)
            processed += 1
        elif m.status == "returning" and m.returns_at and _aware(m.returns_at) <= now:
            survivors = json.loads(m.force).get("spy", 0)
            if survivors:
                stock = await get_or_create_unit_stock(session, m.observer_id, "spy")
                stock.quantity += survivors
            m.status = "done"
            processed += 1
    return processed


async def player_intel(session: AsyncSession, observer: Player) -> list[dict]:
    """Intel del jugador, fusionada con la de sus aliados si la alianza tiene `shared_vision`
    (red de espionaje compartida): por cada objetivo gana la mejor confianza; la propia siempre
    pisa a la del aliado para que espiar vos mismo siempre valga la pena."""
    # Local import: alliances no importa espionage, pero espionage<->alliances cerrarían ciclo.
    from app.services.alliances import has_benefit, members

    now = datetime.now(UTC)
    observer_ids = {observer.id}
    if observer.alliance_id and await has_benefit(session, observer.id, "shared_vision"):
        observer_ids = {m.id for m in await members(session, observer.alliance_id)}

    res = await session.execute(
        select(IntelReport).where(IntelReport.observer_id.in_(observer_ids))
    )
    best: dict[int, dict] = {}
    for r in res.scalars():
        if r.target_id in observer_ids:
            continue  # no muestres intel sobre vos mismo ni sobre tus aliados
        conf = intel_confidence(r, now)
        prev = best.get(r.target_id)
        mine = r.observer_id == observer.id
        # gana: la propia, o (si ninguna es propia) la de mayor confianza
        if prev and (prev["_mine"] or (not mine and prev["confidence"] >= conf)):
            continue
        target = await session.get(Player, r.target_id)
        ally = None if mine else await session.get(Player, r.observer_id)
        best[r.target_id] = {
            "target_id": r.target_id,
            "target": target.username if target else None,
            "depth": round(r.depth, 3),
            "confidence": conf,
            "as_of": r.as_of,
            "payload": json.loads(r.payload),
            "shared": not mine,
            "via": ally.username if ally else None,
            "_mine": mine,
        }
    return [{k: v for k, v in d.items() if k != "_mine"} for d in best.values()]
