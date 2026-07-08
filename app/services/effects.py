"""Unified effect multiplier: combines temporary god boons and permanent researched
technologies for a given effect (production | attack | defense). Used by economy and
combat so both bonus sources stack consistently."""
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.services.boons import boon_multiplier


async def multiplier(
    session: AsyncSession, player_id: int, effect: str, now: datetime | None = None
) -> float:
    m = await boon_multiplier(session, player_id, effect, now)
    # Local imports avoid economy<->research and economy<->alliances import cycles.
    from app.services.alliances import alliance_multiplier
    from app.services.research import researched_techs

    content = get_content()
    for key in await researched_techs(session, player_id):
        tech = content.technologies.get(key)
        if tech and tech.get("effect") == effect:
            m *= float(tech.get("magnitude", 1.0))
    m *= await alliance_multiplier(session, player_id, effect)
    # Eventos dinámicos globales (SDD 36): apilan como un multiplicador más.
    from app.services.events import event_multiplier
    m *= await event_multiplier(session, effect, now)
    # SDD 87: una BOMBA CUÁNTICA activa DRENA la producción (penalización progresiva 1%→80%).
    if effect == "production":
        from app.services.quantum import infection_penalty
        m *= await infection_penalty(session, player_id, now)
    return m
