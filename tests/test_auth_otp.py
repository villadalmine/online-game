"""SDD 6 — passwordless login (email + código OTP): tests de servicio."""
from datetime import UTC, datetime, timedelta

from app.models import EmailOtp, Player
from app.services import auth_otp


async def _request(session, monkeypatch, email, code="123456"):
    monkeypatch.setattr(auth_otp, "generate_code", lambda n: code)
    await auth_otp.request_code(session, email)


async def test_request_stores_hashed_code_not_plaintext(session, monkeypatch):
    await _request(session, monkeypatch, "a@b.com", "123456")
    otp = await session.get(EmailOtp, "a@b.com")
    assert otp is not None
    assert otp.code_hash != "123456"               # nunca en claro
    assert otp.code_hash == auth_otp.hash_code("123456")
    assert otp.attempts == 0 and auth_otp._aware(otp.expires_at) > datetime.now(UTC)


async def test_verify_creates_player_signup_equals_login(session, monkeypatch):
    await _request(session, monkeypatch, "new@b.com", "654321")
    player = await auth_otp.verify_code(session, "new@b.com", "654321")
    assert isinstance(player, Player) and player.email == "new@b.com"
    # el OTP se consumió
    assert await session.get(EmailOtp, "new@b.com") is None
    # segundo login del mismo email -> mismo player, no duplica
    await _request(session, monkeypatch, "new@b.com", "654321")
    again = await auth_otp.verify_code(session, "new@b.com", "654321")
    assert again.id == player.id


async def test_verify_wrong_code_counts_attempts_then_locks(session, monkeypatch):
    await _request(session, monkeypatch, "c@b.com", "111111")
    for _ in range(auth_otp.get_settings().otp_max_attempts - 1):
        try:
            await auth_otp.verify_code(session, "c@b.com", "000000")
            raise AssertionError("debería fallar")
        except auth_otp.AuthOtpError as e:
            assert e.status == 401
    otp = await session.get(EmailOtp, "c@b.com")
    assert otp.attempts == auth_otp.get_settings().otp_max_attempts - 1
    # el intento final inválido invalida el OTP (lo borra)
    try:
        await auth_otp.verify_code(session, "c@b.com", "000000")
        raise AssertionError("debería fallar")
    except auth_otp.AuthOtpError:
        pass
    assert await session.get(EmailOtp, "c@b.com") is None


async def test_verify_expired_is_rejected(session, monkeypatch):
    await _request(session, monkeypatch, "d@b.com", "222222")
    otp = await session.get(EmailOtp, "d@b.com")
    otp.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    try:
        await auth_otp.verify_code(session, "d@b.com", "222222")
        raise AssertionError("expirado debería fallar")
    except auth_otp.AuthOtpError as e:
        assert e.status == 401
    assert await session.get(EmailOtp, "d@b.com") is None


async def test_verify_no_pending_is_uniform_401(session):
    try:
        await auth_otp.verify_code(session, "nobody@b.com", "123456")
        raise AssertionError("sin pendiente debería fallar")
    except auth_otp.AuthOtpError as e:
        assert e.status == 401


async def test_invalid_email_rejected(session):
    try:
        await auth_otp.request_code(session, "not-an-email")
        raise AssertionError("email inválido debería fallar")
    except auth_otp.AuthOtpError as e:
        assert e.status == 422


async def test_resend_within_cooldown_keeps_previous_code(session, monkeypatch):
    codes = iter(["111111", "222222"])
    monkeypatch.setattr(auth_otp, "generate_code", lambda n: next(codes))
    await auth_otp.request_code(session, "e@b.com")           # genera 111111
    first_hash = (await session.get(EmailOtp, "e@b.com")).code_hash
    await auth_otp.request_code(session, "e@b.com")           # dentro del cooldown -> no reenvía
    assert (await session.get(EmailOtp, "e@b.com")).code_hash == first_hash
    # el código viejo sigue siendo válido
    player = await auth_otp.verify_code(session, "e@b.com", "111111")
    assert player.email == "e@b.com"
