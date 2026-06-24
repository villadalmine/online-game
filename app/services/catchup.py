"""Catch-up del recién llegado (SDD 25): nivelar a quien entra a una partida vieja, sin ventaja.

Mira a los **pares de su galaxia** (SDD 8) y lleva al nuevo al **percentil bajo-medio** (P40) del
stock de minerales — nunca por encima (equalizar, no boostear) —, le da **energía full** para poder
actuar y asegura **defensa** (mina + torreta). Nada ofensivo. Corre una vez, en el onboarding.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player, ResourceStock
from app.services.economy import get_or_create_stock


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = int(round(p * (len(s) - 1)))
    return s[idx]


async def _stock_total(session: AsyncSession, player_id: int) -> float:
    rows = (
        await session.execute(
            select(ResourceStock.amount).where(ResourceStock.player_id == player_id)
        )
    ).scalars().all()
    return float(sum(rows))


async def apply_catchup(session: AsyncSession, player: Player) -> dict | None:
    """Aplica el grant si corresponde. Devuelve un resumen (o None si no aplica)."""
    settings = get_settings()
    if player.is_npc or not settings.catchup_enabled:
        return None

    # Pares: humanos de la MISMA instancia de galaxia (SDD 8), ya onboardeados, menos él.
    peers = (
        await session.execute(
            select(Player).where(
                Player.is_npc.is_(False),
                Player.race_key.is_not(None),
                Player.galaxy_instance_id == player.galaxy_instance_id,
                Player.id != player.id,
            )
        )
    ).scalars().all()
    if len(peers) < settings.catchup_min_peers:
        return None  # partida joven / vacía → sin catch-up

    totals = [await _stock_total(session, p.id) for p in peers]
    baseline = _percentile(totals, settings.catchup_percentile)
    mine_total = await _stock_total(session, player.id)

    granted: dict[str, float] = {}
    # Top-up de minerales SOLO hasta el baseline P40 (nunca por encima → sin ventaja).
    if baseline > mine_total:
        content = get_content()
        roles = list(dict.fromkeys(content.races[player.race_key]["resource_roles"].values()))
        per = (baseline - mine_total) / max(1, len(roles))
        for role in roles:
            st = await get_or_create_stock(session, player.id, role)
            st.amount += per
            granted[role] = per

    # Energía full para poder actuar ya (transitorio, regenera; no es ventaja persistente).
    player.energy = settings.energy_max

    # Defensa priorizada: asegurar mina (producción) + torreta (defensa) activas. Nada ofensivo.
    base = (
        await session.execute(select(Base_).where(Base_.player_id == player.id))
    ).scalars().first()
    if base is not None:
        existing = {
            b.building_key
            for b in (
                await session.execute(select(Building).where(Building.base_id == base.id))
            ).scalars()
        }
        struct = (get_content().races[player.race_key]["resource_roles"].get("structural")
                  or next(iter(get_content().races[player.race_key]["resource_roles"].values())))
        if "mine" not in existing:
            session.add(Building(base_id=base.id, building_key="mine", status="active",
                                 production_mineral=struct))
            granted["mine"] = 1
        if "turret" not in existing:
            session.add(Building(base_id=base.id, building_key="turret", status="active"))
            granted["turret"] = 1

    return {"baseline": baseline, "energy": player.energy, "granted": granted}
