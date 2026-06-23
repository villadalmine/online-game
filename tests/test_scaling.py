"""SDD 7 (capacidad/pool/SSE) + SDD 9 (LLM local: timeout/rate-limit) — piezas testeables.

Lo de infra (HPA/PDB/recursos del Helm, manifiestos de GPU) se valida con `helm lint/template`
y los ejemplos en deploy/gpu-llm/; acá cubrimos lo que vive en la app."""
from app.core.config import Settings
from app.core.db import engine_kwargs


def test_engine_kwargs_sqlite_keeps_defaults():
    # SQLite (dev/tests) NO recibe args de pool (el pool por defecto va con el archivo único).
    s = Settings(database_url="sqlite+aiosqlite:///./game.db")
    kw = engine_kwargs(s)
    assert kw == {"future": True}
    assert "pool_size" not in kw


def test_engine_kwargs_postgres_tunes_pool():
    # Postgres (prod) recibe el pool tuneado (SDD 7): el techo de conexiones es por réplica.
    s = Settings(
        database_url="postgresql+asyncpg://u:p@host:5432/db",
        db_pool_size=7,
        db_max_overflow=13,
        db_pool_timeout=42,
    )
    kw = engine_kwargs(s)
    assert kw["pool_size"] == 7
    assert kw["max_overflow"] == 13
    assert kw["pool_timeout"] == 42
    assert kw["pool_pre_ping"] is True


def test_scaling_defaults_present():
    s = Settings()
    # Defaults conservadores: comportamiento actual si no se setea nada.
    assert s.stream_interval == 2.0
    assert s.db_pool_size == 5
    assert s.llm_timeout_seconds == 20.0
    assert s.advisor_rate_limit_per_min == 6


async def test_bump_increments_prometheus_events(session):
    # SDD 19: stats.bump emite game_events_total{kind=...} (métricas de negocio).
    from app.core import metrics
    from app.models import Player
    from app.services import stats

    p = Player(username="evtmetric", password_hash="x")
    session.add(p)
    await session.commit()
    await stats.bump(session, p.id, buildings_built=2, units_trained=1)
    out = metrics.render()
    assert 'game_events_total{kind="buildings_built"}' in out
    assert 'game_events_total{kind="units_trained"}' in out


def test_scaling_overridable():
    s = Settings(stream_interval=5.0, llm_timeout_seconds=30.0, advisor_rate_limit_per_min=2)
    assert s.stream_interval == 5.0
    assert s.llm_timeout_seconds == 30.0
    assert s.advisor_rate_limit_per_min == 2
