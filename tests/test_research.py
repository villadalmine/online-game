from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.security import hash_password
from app.models import Base_, Building, Player
from app.services.effects import multiplier
from app.services.onboarding import onboard_player
from app.services.research import (
    ResearchError,
    finalize_due_research,
    researched_techs,
    start_research,
)


async def _onboarded(session, race="terran", planet="earth") -> Player:
    p = Player(username="r", password_hash=hash_password("secret123"))
    session.add(p)
    await session.flush()
    await onboard_player(session, p, "milky_way", planet, race)
    await session.commit()
    return p


async def _add_lab(session, p):
    base = (await session.execute(select(Base_).where(Base_.player_id == p.id))).scalars().first()
    session.add(Building(base_id=base.id, building_key="research_lab", status="active"))
    await session.commit()


async def test_research_requires_lab(session):
    p = await _onboarded(session)
    with pytest.raises(ResearchError):
        await start_research(session, p, "mining_efficiency")


async def test_research_finalizes_and_applies_effect(session):
    p = await _onboarded(session)
    await _add_lab(session, p)
    order = await start_research(session, p, "mining_efficiency")
    await session.commit()

    order.completes_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    assert await finalize_due_research(session, p) == 1
    await session.commit()

    assert "mining_efficiency" in await researched_techs(session, p.id)
    # production multiplier now reflects the +25% tech
    assert await multiplier(session, p.id, "production") == pytest.approx(1.25)


async def test_cannot_research_twice(session):
    p = await _onboarded(session)
    await _add_lab(session, p)
    order = await start_research(session, p, "weapons")
    order.completes_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    await finalize_due_research(session, p)
    await session.commit()
    with pytest.raises(ResearchError):
        await start_research(session, p, "weapons")
