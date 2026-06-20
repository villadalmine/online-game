import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app import models  # noqa: F401  (register tables on Base.metadata)
from app.core.db import Base


def _make_engine():
    return create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )


@pytest_asyncio.fixture
async def session():
    """In-memory DB session for service-level (unit/integration) tests."""
    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


class Harness:
    """Bundles the HTTP client and a session maker bound to the SAME in-memory DB,
    so e2e tests act via HTTP and may arrange/seed state directly via the DB."""

    def __init__(self, http: httpx.AsyncClient, session_maker):
        self.http = http
        self.session_maker = session_maker


@pytest_asyncio.fixture
async def client():
    """HTTP harness wired to the real FastAPI app over a fresh in-memory DB.

    Overrides get_session so every request shares one in-memory engine; lifespan
    is intentionally not entered (no init_models on the real engine).
    """
    from app.core.db import get_session
    from app.main import app

    engine = _make_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def _override_get_session():
        async with maker() as s:
            yield s

    app.dependency_overrides[get_session] = _override_get_session
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield Harness(c, maker)
    app.dependency_overrides.clear()
    await engine.dispose()
