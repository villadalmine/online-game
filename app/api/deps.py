from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
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


async def get_current_admin(player: Player = Depends(get_current_player)) -> Player:
    """Gate de /admin/* (SDD 14 v2). Si ADMIN_EMAIL está configurado, exige ser admin (is_admin
    o ese email). Vacío = sin gate (dev/test, comportamiento actual)."""
    admin_email = get_settings().admin_email.strip().lower()
    if not admin_email:
        return player
    if player.is_admin or (player.email or "").lower() == admin_email:
        return player
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo el admin puede hacer esto.")
