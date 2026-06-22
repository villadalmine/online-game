"""Passwordless login por email + código OTP (SDD 6).

Adapta el patrón de `bot-telegram/src/otp.py` a SQLAlchemy async + identidad `Player`:
- código de N dígitos con CSPRNG (`secrets`, no `random`),
- guardado como HMAC-SHA256(code, OTP_SECRET) — nunca en claro,
- TTL corto + máx intentos + comparación constant-time (`hmac.compare_digest`),
- respuestas uniformes (no se revela si el email existe → anti-enumeración).

`request_code` y `verify_code` son passwordless; el login usuario+contraseña sigue existiendo
(`/auth/login`) para dev/CLI/tests. Email real solo en deploy: en dev `MAIL_BACKEND=console`
loguea el código.
"""
import hashlib
import hmac
import logging
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import EmailOtp, Player
from app.services.mailer import is_valid_email, send_email

log = logging.getLogger("auth_otp")


class AuthOtpError(Exception):
    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.status = status


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def generate_code(length: int) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_code(code: str) -> str:
    salt = get_settings().otp_secret.encode("utf-8") or b"dev-otp-secret"
    return hmac.new(salt, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _otp_subject_body(code: str, ttl_min: int, lang: str) -> tuple[str, str]:
    if lang == "en":
        return (
            "Your Online Galaxy War code",
            f"Your login code is: {code}\nIt expires in {ttl_min} minutes.\n"
            "If you didn't request it, ignore this email.",
        )
    return (
        "Tu código de Online Galaxy War",
        f"Tu código de acceso es: {code}\nVence en {ttl_min} minutos.\n"
        "Si no lo pediste, ignorá este correo.",
    )


async def request_code(session: AsyncSession, email: str, lang: str = "es") -> None:
    """Genera y envía un código. Uniforme: nunca revela si el email tiene cuenta. Respeta un
    cooldown de reenvío (si está dentro, no reenvía pero responde igual)."""
    settings = get_settings()
    email = (email or "").strip().lower()
    if not is_valid_email(email):
        raise AuthOtpError("Email inválido.", 422)

    now = datetime.now(UTC)
    otp = await session.get(EmailOtp, email)
    if otp is not None:
        since = (now - _aware(otp.last_sent_at)).total_seconds()
        if since < settings.otp_resend_cooldown_seconds:
            return  # dentro del cooldown → no reenviar, pero responder uniforme

    code = generate_code(settings.otp_length)
    expires_at = now + timedelta(minutes=settings.otp_ttl_minutes)
    if otp is None:
        otp = EmailOtp(email=email)
        session.add(otp)
    otp.code_hash = hash_code(code)
    otp.attempts = 0
    otp.expires_at = expires_at
    otp.last_sent_at = now
    await session.flush()

    subject, body = _otp_subject_body(code, settings.otp_ttl_minutes, lang)
    try:
        await send_email(email, subject, body)
    except Exception:
        # No rompemos el flujo ni revelamos detalles; queda en logs para operar.
        log.exception("fallo enviando OTP a %s", email)
    await session.commit()


_USERNAME_RE = re.compile(r"[^a-z0-9_]+")


async def _unique_username(session: AsyncSession, email: str) -> str:
    base = _USERNAME_RE.sub("", email.split("@")[0].lower())[:40] or "player"
    candidate = base
    while (
        await session.execute(select(Player.id).where(Player.username == candidate))
    ).first() is not None:
        candidate = f"{base}_{secrets.token_hex(3)}"[:50]
    return candidate


async def verify_code(session: AsyncSession, email: str, code: str) -> Player:
    """Valida el código y devuelve el Player (lo crea si el email es nuevo: signup = login).
    Errores uniformes (401) para no revelar el estado del email/código."""
    settings = get_settings()
    email = (email or "").strip().lower()
    otp = await session.get(EmailOtp, email)
    if otp is None:
        raise AuthOtpError("Código inválido o expirado.", 401)

    now = datetime.now(UTC)
    if now >= _aware(otp.expires_at):
        await session.delete(otp)
        await session.commit()
        raise AuthOtpError("Código inválido o expirado.", 401)

    if hmac.compare_digest(otp.code_hash, hash_code(code)):
        res = await session.execute(select(Player).where(Player.email == email))
        player = res.scalar_one_or_none()
        if player is None:  # signup = login
            player = Player(
                username=await _unique_username(session, email),
                # passwordless: contraseña inutilizable (no la conoce nadie)
                password_hash=hash_password(secrets.token_urlsafe(32)),
                email=email,
            )
            session.add(player)
        await session.delete(otp)
        await session.commit()
        return player

    otp.attempts += 1
    if otp.attempts >= settings.otp_max_attempts:
        await session.delete(otp)
        await session.commit()
        raise AuthOtpError("Código inválido o expirado.", 401)
    await session.commit()
    raise AuthOtpError("Código inválido o expirado.", 401)
