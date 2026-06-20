from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player
from app.core.db import get_session
from app.models import Player
from app.schemas import (
    AllianceCreate,
    AllianceDetailOut,
    AllianceMemberOut,
    AllianceOut,
    AllianceRankingEntryOut,
    AllianceTransferRequest,
)
from app.services.alliances import (
    AllianceError,
    create_alliance,
    join_alliance,
    leave_alliance,
    list_alliances,
    member_count,
    members,
    transfer,
)
from app.services.scoring import player_score

router = APIRouter()


@router.get("/ranking", response_model=list[AllianceRankingEntryOut])
async def alliance_ranking(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Alliances ranked by the combined score of their members."""
    entries = []
    for a, count in await list_alliances(session):
        total = sum([await player_score(session, m) for m in await members(session, a.id)])
        entries.append((total, a, count))
    entries.sort(key=lambda x: x[0], reverse=True)
    return [
        AllianceRankingEntryOut(
            rank=i + 1, id=a.id, name=a.name, tag=a.tag, member_count=count, score=score
        )
        for i, (score, a, count) in enumerate(entries)
    ]


def _out(a, count) -> AllianceOut:
    return AllianceOut(
        id=a.id, name=a.name, tag=a.tag, type=a.type, leader_id=a.leader_id, member_count=count
    )


@router.get("", response_model=list[AllianceOut])
async def list_all(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    return [_out(a, c) for a, c in await list_alliances(session)]


@router.post("", response_model=AllianceOut, status_code=status.HTTP_201_CREATED)
async def create(
    body: AllianceCreate,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        a = await create_alliance(session, player, body.name, body.tag, body.type)
    except AllianceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return _out(a, await member_count(session, a.id))


@router.post("/transfer")
async def transfer_minerals(
    body: AllianceTransferRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Comercio: transferí minerales a un aliado (requiere beneficio 'trade')."""
    try:
        await transfer(session, player, body.to_player_id, body.mineral, body.amount)
    except AllianceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"transferred": body.amount, "mineral": body.mineral, "to": body.to_player_id}


@router.post("/{alliance_id}/join", response_model=AllianceOut)
async def join(
    alliance_id: int,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        a = await join_alliance(session, player, alliance_id)
    except AllianceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return _out(a, await member_count(session, a.id))


@router.post("/leave")
async def leave(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    try:
        await leave_alliance(session, player)
    except AllianceError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return {"left": True}


@router.get("/{alliance_id}", response_model=AllianceDetailOut)
async def detail(
    alliance_id: int,
    _: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    ms = await members(session, alliance_id)
    if not ms:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alianza vacía o inexistente")
    from app.models import Alliance

    a = await session.get(Alliance, alliance_id)
    return AllianceDetailOut(
        id=a.id, name=a.name, tag=a.tag, type=a.type, leader_id=a.leader_id, member_count=len(ms),
        members=[
            AllianceMemberOut(id=m.id, username=m.username, race_key=m.race_key, is_npc=m.is_npc)
            for m in ms
        ],
    )
