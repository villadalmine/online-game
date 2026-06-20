from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
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
