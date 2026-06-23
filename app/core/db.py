from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import Settings, get_settings

settings = get_settings()


def engine_kwargs(s: Settings) -> dict:
    """Pool args for create_async_engine. SQLite (dev/tests) keeps its single-file
    defaults; Postgres (prod) gets a tuned pool (SDD 7). pool_size × réplicas es el
    techo de conexiones contra Postgres — de ahí PgBouncer a gran escala."""
    if s.is_sqlite:
        return {"future": True}
    return {
        "future": True,
        "pool_size": s.db_pool_size,
        "max_overflow": s.db_max_overflow,
        "pool_timeout": s.db_pool_timeout,
        "pool_recycle": s.db_pool_recycle,
        "pool_pre_ping": True,
    }


engine = create_async_engine(settings.database_url, **engine_kwargs(settings))
SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


def get_sessionmaker():
    """Dependency returning the session factory (overridable in tests).

    Used by long-lived handlers (e.g. the SSE stream) that open/close their own
    sessions per poll instead of holding one request-scoped session open."""
    return SessionLocal


async def init_models() -> None:
    """Create tables directly (used by tests). App startup uses run_migrations()."""
    # Import models so they register on Base.metadata
    from app import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def run_migrations() -> None:
    """Apply Alembic migrations up to head (sync; call via asyncio.to_thread in async code).

    Used at app startup so schema changes apply automatically — no manual DB reset in dev.
    Idempotent: a no-op when already at head."""
    from alembic import command
    from alembic.config import Config

    from app.core.config import REPO_ROOT

    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")
