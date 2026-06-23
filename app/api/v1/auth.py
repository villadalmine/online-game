from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import normalize_lang
from app.core.config import get_settings
from app.core.db import get_session
from app.core.security import create_access_token, hash_password, verify_password
from app.models import Player
from app.schemas import (
    LoginRequest,
    RegisterRequest,
    RequestCodeRequest,
    RequestCodeResponse,
    TokenResponse,
    VerifyCodeRequest,
)
from app.services import auth_otp
from app.services.mailer import is_valid_email

router = APIRouter()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    # Allowlist (SDD 14): si está activa, el registro por usuario+contraseña también queda gateado
    # — solo emails autorizados. Sin allowlist (default dev), registro abierto como antes.
    allowed = get_settings().allowed_email_set
    email = (body.email or "").strip().lower() or None
    if allowed:
        if email is None or not is_valid_email(email):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Registro por invitación: email requerido."
            )
        if email not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Ese email no está autorizado.")

    exists = await session.execute(select(Player).where(Player.username == body.username))
    if exists.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "El usuario ya existe")
    if email is not None:
        taken = await session.execute(select(Player.id).where(Player.email == email))
        if taken.first() is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "Ese email ya tiene cuenta.")
    player = Player(
        username=body.username, password_hash=hash_password(body.password), email=email
    )
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


# ---- Passwordless: email + código OTP (SDD 6) -------------------------------
@router.post("/request-code", response_model=RequestCodeResponse)
async def request_code(
    body: RequestCodeRequest,
    lang: str | None = None,
    accept_language: str | None = Header(default=None),
    session: AsyncSession = Depends(get_session),
):
    """Manda un código al email. Respuesta SIEMPRE uniforme (no revela si el email existe)."""
    try:
        await auth_otp.request_code(session, body.email, normalize_lang(lang or accept_language))
    except auth_otp.AuthOtpError as e:
        raise HTTPException(e.status, str(e)) from e
    return RequestCodeResponse(sent=True)


@router.post("/verify-code", response_model=TokenResponse)
async def verify_code(body: VerifyCodeRequest, session: AsyncSession = Depends(get_session)):
    """Verifica el código y devuelve el JWT (crea la cuenta si el email es nuevo)."""
    try:
        player = await auth_otp.verify_code(session, body.email, body.code)
    except auth_otp.AuthOtpError as e:
        raise HTTPException(e.status, str(e)) from e
    return TokenResponse(access_token=create_access_token(player.username))
