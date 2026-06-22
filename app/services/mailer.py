"""Email sender, provider-agnostic and dependency-free (SDD 6).

Backends (MAIL_BACKEND): `console` (default — logs the message, for dev/CI without SMTP),
`smtp` (stdlib smtplib in a thread), `resend` (HTTP via httpx, already a dep). Validates the
address against header-injection (CR/LF). One place to change how mail goes out.
"""
import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage

import httpx

from app.core.config import get_settings

log = logging.getLogger("mailer")

# "no es basura" + anti CRLF-injection en headers (no pretende cubrir RFC 5322 entero).
_EMAIL_RE = re.compile(r"^[^@\s,;<>\"\\]+@[^@\s,;<>\"\\]+\.[^@\s,;<>\"\\]+$")


def is_valid_email(addr: str) -> bool:
    return bool(addr) and "\n" not in addr and "\r" not in addr and bool(_EMAIL_RE.match(addr))


async def send_email(to: str, subject: str, body: str) -> None:
    """Send a plain-text email via the configured backend. Raises on hard failures so the caller
    can decide (the OTP flow logs and still responds uniformly to avoid enumeration)."""
    settings = get_settings()
    if not is_valid_email(to):
        raise ValueError(f"email inválido: {to!r}")
    backend = settings.mail_backend.lower()

    if backend == "console":
        log.warning("[mail:console] to=%s subject=%s\n%s", to, subject, body)
        return
    if backend == "smtp":
        await asyncio.to_thread(_send_smtp, settings, to, subject, body)
        return
    if backend == "resend":
        await _send_resend(settings, to, subject, body)
        return
    raise ValueError(f"MAIL_BACKEND desconocido: {settings.mail_backend}")


def _build_message(settings, to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.mail_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _send_smtp(settings, to: str, subject: str, body: str) -> None:
    msg = _build_message(settings, to, subject, body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def _send_resend(settings, to: str, subject: str, body: str) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json={"from": settings.mail_from, "to": [to], "subject": subject, "text": body},
        )
        resp.raise_for_status()
