"""Calculadora de combate (SDD 34): helpers puros sobre la misma fórmula que `resolve_combat`,
más un `plan_attack` que estima la defensa del objetivo **desde tu intel** (SDD 35) — así la
calculadora y la IA dan números exactos y auditables sin filtrar el estado real del defensor.
"""
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.models import Base_, Player


class PlanError(Exception):
    pass


# --------------------------------------------------------------------------- #
# Helpers puros (testeables a mano contra la matriz del SDD 34)
# --------------------------------------------------------------------------- #
def loss_ratios(attack_score: float, defense_score: float) -> tuple[float, float]:
    """(cuota_atacante, cuota_defensor) = pérdidas proporcionales a la cuota del rival."""
    total = attack_score + defense_score
    if total <= 0:
        return 0.0, 0.0
    return defense_score / total, attack_score / total


def min_attack_power(defense_score: float, atk_mult: float, margin: float = 1.0) -> float:
    """Poder de ataque (antes de tu multiplicador) para alcanzar `margin`× la defensa."""
    if atk_mult <= 0:
        return math.inf
    return defense_score * margin / atk_mult


def units_for_power(power: float, unit_key: str, stat: str = "attack") -> int | None:
    a = get_content().units.get(unit_key, {}).get("stats", {}).get(stat, 0)
    if a <= 0:
        return None
    return math.ceil(power / a)


def defense_needed(expected_attack: float, def_mult: float, flat_defense: float = 0.0) -> float:
    """Poder de defensa (unidades) que necesitás para aguantar un ataque esperado."""
    if def_mult <= 0:
        return math.inf
    return max(0.0, expected_attack / def_mult - flat_defense)


# --------------------------------------------------------------------------- #
# Multiplicador de ataque efectivo del jugador (raza × tech × boons × alianza)
# --------------------------------------------------------------------------- #
async def attack_mult(session: AsyncSession, attacker: Player) -> float:
    from app.services.effects import multiplier
    base = get_content().races.get(attacker.race_key, {}).get("bonuses", {}).get(
        "military_attack", 1.0
    )
    return base * await multiplier(session, attacker.id, "attack")


def _estimate_defense(payload: dict) -> float | None:
    """Defensa estimada desde la intel graduada (cota alta = conservadora para atacar)."""
    army = payload.get("army_defense")
    if army is None:
        return None  # intel demasiado superficial (no se reveló la defensa)
    d = float(army[1]) if isinstance(army, list) else float(army)
    turrets = payload.get("turrets")
    if isinstance(turrets, (int, float)):
        d += turrets * get_content().buildings.get("turret", {}).get("defense_power", 0)
    return d


# --------------------------------------------------------------------------- #
# Plan contra un objetivo real (usa TU intel; no filtra el estado exacto del rival)
# --------------------------------------------------------------------------- #
async def plan_attack(
    session: AsyncSession, observer: Player, target_base_id: int, margin: float = 2.0
) -> dict:
    from app.services.espionage import player_intel

    base = await session.get(Base_, target_base_id)
    if base is None:
        raise PlanError("Base objetivo no encontrada.")
    if base.player_id == observer.id:
        raise PlanError("Es tu propia base.")

    rep = {r["target_id"]: r for r in await player_intel(session, observer)}.get(base.player_id)
    if rep is None:
        raise PlanError("Sin inteligencia de ese objetivo: espialo primero 🕵.")
    d_est = _estimate_defense(rep["payload"])
    if d_est is None:
        raise PlanError("Tu intel es muy superficial: espiá más profundo para ver su defensa.")

    atk_mult = await attack_mult(session, observer)
    need_power = min_attack_power(d_est, atk_mult, margin)

    options = []
    for key, spec in get_content().units.items():
        atk = spec.get("stats", {}).get("attack", 0)
        if atk <= 0:
            continue
        qty = units_for_power(need_power, key) or 0
        attack_score = qty * atk * atk_mult
        a_loss, d_loss = loss_ratios(attack_score, d_est)
        options.append({
            "unit": key,
            "qty": qty,
            "attack_score": round(attack_score, 1),
            "est_attacker_loss_pct": round(a_loss * 100),
            "est_defender_loss_pct": round(d_loss * 100),
            "wins": attack_score > d_est,
        })
    options.sort(key=lambda o: o["qty"])

    return {
        "target": rep["target"],
        "target_base_id": target_base_id,
        "depth": rep["depth"],
        "confidence": rep["confidence"],
        "as_of": rep["as_of"],
        "shared": rep.get("shared", False),
        "estimated_defense": round(d_est, 1),
        "atk_mult": round(atk_mult, 3),
        "margin": margin,
        "attack_power_needed": round(need_power, 1),
        "options": options,
    }
