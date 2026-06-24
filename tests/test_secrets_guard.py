"""Deuda técnica de prod: secretos fuertes. weak_secrets() detecta defaults/cortos y en
production el arranque debe abortar (lo verificamos vía el lifespan)."""
import pytest

from app.core.config import Settings


def _settings(**kw) -> Settings:
    # explícitos (ganan al .env local) para aislar el test del entorno
    base = dict(
        jwt_secret="x" * 32,
        otp_secret="y" * 32,
        environment="production",
        allowed_emails="",
        mail_backend="console",
    )
    base.update(kw)
    return Settings(**base)


def test_default_jwt_secret_is_weak():
    s = _settings(jwt_secret="change-me")
    assert "JWT_SECRET" in s.weak_secrets()


def test_short_jwt_secret_is_weak():
    s = _settings(jwt_secret="too-short")
    assert "JWT_SECRET" in s.weak_secrets()


def test_strong_secrets_are_ok():
    assert _settings().weak_secrets() == []


def test_otp_only_checked_when_passwordless_active():
    # console + sin allowlist ⇒ OTP no está en uso ⇒ no se exige fuerte
    assert "OTP_SECRET" not in _settings(otp_secret="change-me-otp-secret").weak_secrets()
    # con allowlist (passwordless activo) ⇒ se exige fuerte
    s = _settings(otp_secret="change-me-otp-secret", allowed_emails="a@b.com")
    assert "OTP_SECRET" in s.weak_secrets()


def test_is_production_flag():
    assert _settings(environment="production").is_production
    assert _settings(environment="PROD").is_production
    assert not _settings(environment="development").is_production


@pytest.mark.asyncio
async def test_lifespan_aborts_in_prod_with_weak_secret(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "settings", _settings(jwt_secret="change-me"))
    with pytest.raises(RuntimeError, match="secretos débiles"):
        async with main.lifespan(main.app):
            pass
