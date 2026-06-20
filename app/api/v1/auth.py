from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Player
from app.schemas import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    exists = await session.execute(select(Player).where(Player.username == body.username))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El usuario ya existe")
    player = Player(username=body.username, password_hash=hash_password(body.password))
    session.add(player)
    await session.commit()
    return TokenResponse(access_token=create_access_token(player.username))


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, session: AsyncSession = Depends(get_session)):
    res = await session.execute(select(Player).where(Player.username == body.username))
    player = res.scalar_one_or_none()
    if player is None or not verify_password(body.password, player.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Credenciales invalidas")
    return TokenResponse(access_token=create_access_token(player.username))
