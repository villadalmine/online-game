from collections.abc import AsyncIterator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.redis import get_redis, player_lock
from app.core.security import decode_token
from app.models import Player

bearer = HTTPBearer(auto_error=True)


async def get_current_player(
    creds: HTTPAuthorizationCredentials = Depends(bearer),
    session: AsyncSession = Depends(get_session),
) -> Player:
    username = decode_token(creds.credentials)
    if username is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token invalido")
    res = await session.execute(select(Player).where(Player.username == username))
    player = res.scalar_one_or_none()
    if player is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Jugador no encontrado")
    return player


async def lock_current_player(
    player: Player = Depends(get_current_player),
    redis: Redis | None = Depends(get_redis),
) -> AsyncIterator[Player]:
    """Como get_current_player, pero toma un lock por jugador mientras dura el request: serializa
    acciones mutantes (build/train/research/expedición/ataque) → sin doble-gasto por concurrencia.
    Sin Redis es no-op (dev/tests). Si otro request del mismo jugador lo tiene → 409."""
    async with player_lock(redis, player.id) as acquired:
        if not acquired:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Ya tenés una acción en curso, reintentá."
            )
        yield player


async def get_current_admin(player: Player = Depends(get_current_player)) -> Player:
    """Gate de /admin/* (SDD 14 v2). Si ADMIN_EMAIL está configurado, exige ser admin (is_admin
    o ese email). Vacío = sin gate (dev/test, comportamiento actual)."""
    admin_email = get_settings().admin_email.strip().lower()
    if not admin_email:
        return player
    if player.is_admin or (player.email or "").lower() == admin_email:
        return player
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el admin puede hacer esto.")
