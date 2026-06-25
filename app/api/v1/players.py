from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_player, lock_current_player
from app.core.db import get_session
from app.core.redis import get_redis
from app.core.security import create_access_token, hash_password
from app.models import Base_, Player
from app.schemas import (
    OnboardRequest,
    PlayerStateOut,
    PlayerSummaryOut,
    ProfileUpdateRequest,
    ProfileUpdateResponse,
    RankingEntryOut,
)
from app.services import presence
from app.services.onboarding import OnboardingError, onboard_player
from app.services.scoring import player_score
from app.services.state import advance, snapshot

router = APIRouter()


@router.get("/ranking", response_model=list[RankingEntryOut])
async def ranking(
    _: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Leaderboard: score = edificios + poder militar + minerales + techs + victorias."""
    res = await session.execute(select(Player).where(Player.race_key.is_not(None)))
    entries = [(await player_score(session, p), p) for p in res.scalars()]
    entries.sort(key=lambda x: x[0], reverse=True)
    return [
        RankingEntryOut(
            rank=i + 1, id=p.id, username=p.username, race_key=p.race_key,
            is_npc=p.is_npc, score=score,
        )
        for i, (score, p) in enumerate(entries)
    ]


@router.get("", response_model=list[PlayerSummaryOut])
async def list_players(
    me: Player = Depends(get_current_player), session: AsyncSession = Depends(get_session)
):
    """Scoreboard: jugadores de TU galaxia (SDD 8) + NPCs (ambientales)."""
    res = await session.execute(select(Player).where(Player.race_key.is_not(None)))
    out: list[PlayerSummaryOut] = []
    for p in res.scalars():
        if not p.is_npc and p.galaxy_instance_id != me.galaxy_instance_id:
            continue  # otra galaxia: no la ves
        bres = await session.execute(select(Base_.id).where(Base_.player_id == p.id).limit(1))
        out.append(
            PlayerSummaryOut(
                id=p.id,
                username=p.username,
                race_key=p.race_key,
                planet_key=p.planet_key,
                is_npc=p.is_npc,
                home_base_id=bres.scalar_one_or_none(),
                alliance_id=p.alliance_id,
            )
        )
    return out


@router.get("/me", response_model=PlayerStateOut)
async def get_me(
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
    redis: Redis | None = Depends(get_redis),
):
    if player.race_key is not None:
        await advance(session, player)
    await presence.touch(redis, player.id)  # SDD 21: heartbeat de "online"
    return await snapshot(session, player)


@router.post("/me/profile", response_model=ProfileUpdateResponse)
async def update_profile(
    body: ProfileUpdateRequest,
    player: Player = Depends(lock_current_player),
    session: AsyncSession = Depends(get_session),
):
    """Cambiar tu nick y/o contraseña sin validar email (ya estás autenticado). El reset de
    contraseña olvidada va por OTP (login por código → cambiás la clave acá). Devuelve un token
    nuevo porque el nick viaja en el token."""
    if body.username is None and body.password is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nada para cambiar.")
    if body.username and body.username != player.username:
        taken = (
            await session.execute(select(Player).where(Player.username == body.username))
        ).scalar_one_or_none()
        if taken is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese nombre de usuario ya está en uso.")
        player.username = body.username
    if body.password:
        player.password_hash = hash_password(body.password)
    await session.commit()
    return ProfileUpdateResponse(
        username=player.username, access_token=create_access_token(player.username)
    )


@router.post("/onboard", response_model=PlayerStateOut, status_code=status.HTTP_201_CREATED)
async def onboard(
    body: OnboardRequest,
    player: Player = Depends(get_current_player),
    session: AsyncSession = Depends(get_session),
):
    if player.status != "active":   # SDD 14: no se puede jugar hasta que el admin apruebe
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Tu cuenta espera aprobación del admin." if player.status == "pending"
            else "Tu cuenta no está activa.",
        )
    try:
        await onboard_player(session, player, body.galaxy_key, body.planet_key, body.race_key)
    except OnboardingError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    await session.commit()
    return await snapshot(session, player)
