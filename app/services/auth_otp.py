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
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import metrics
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

    # Allowlist de altas (SDD 14): si está configurada, solo emails autorizados —o jugadores ya
    # existentes— reciben código. Salida UNIFORME (no enviar pero responder igual) para no revelar
    # la lista. Quitar a alguien de la lista no bloquea a quien ya tiene cuenta.
    allowed = settings.allowed_email_set
    if allowed and email not in allowed:
        exists = (
            await session.execute(select(Player.id).where(Player.email == email))
        ).first()
        if exists is None:
            log.info("request_code: email no autorizado (allowlist) — no se envía código")
            return

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


async def _unique_username(session: AsyncSession) -> str:
    """Nickname NEUTRO para el alta por OTP (SDD 20): NO derivar del email (no exponerlo en el
    nombre público). El usuario puede renombrarse luego (PATCH /players/me/username)."""
    while True:
        candidate = f"comandante-{secrets.token_hex(3)}"
        if (
            await session.execute(select(Player.id).where(Player.username == candidate))
        ).first() is None:
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
            admin_email = settings.admin_email.strip().lower()
            is_admin = bool(admin_email) and email == admin_email
            # SDD 14: si la aprobación está activa, las altas nuevas nacen 'pending' (el admin entra
            # siempre 'active'). Flag OFF → 'active' (no rompe).
            status = "pending" if (settings.signup_requires_approval and not is_admin) else "active"
            player = Player(
                username=await _unique_username(session),
                # passwordless: contraseña inutilizable (no la conoce nadie)
                password_hash=hash_password(secrets.token_urlsafe(32)),
                email=email,
                is_admin=is_admin,
                status=status,
            )
            session.add(player)
            metrics.SIGNUPS.inc(method="otp")
            if status == "pending":
                await _notify_admins_pending(session, player)
        await session.delete(otp)
        await session.commit()
        metrics.LOGINS.inc(method="otp")
        return player

    otp.attempts += 1
    if otp.attempts >= settings.otp_max_attempts:
        await session.delete(otp)
        await session.commit()
        raise AuthOtpError("Código inválido o expirado.", 401)
    await session.commit()
    raise AuthOtpError("Código inválido o expirado.", 401)


async def _notify_admins_pending(session: AsyncSession, new_player: Player) -> None:
    """SDD 14: avisa a los admins (in-app) que hay una cuenta esperando aprobación."""
    from app.services.notifications import notify
    res = await session.execute(select(Player).where(Player.is_admin.is_(True)))
    admins = res.scalars().all()
    for admin in admins:
        await notify(
            session, admin.id, "signup_pending",
            f"Nueva cuenta espera aprobación: {new_player.username} ({new_player.email}).",
            {"username": new_player.username, "email": new_player.email},
        )
