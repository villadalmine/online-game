"""Guards that Alembic migrations stay in sync with the ORM models:
`alembic upgrade head` must create every table defined on Base.metadata.
"""
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from app import models  # noqa: F401  (register tables on Base.metadata)
from app.core.config import REPO_ROOT
from app.core.db import Base


def test_upgrade_head_creates_all_model_tables(tmp_path):
    db = tmp_path / "migrated.db"
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db}")

    command.upgrade(cfg, "head")

    engine = sa.create_engine(f"sqlite:///{db}")
    tables = set(sa.inspect(engine).get_table_names())
    engine.dispose()

    expected = set(Base.metadata.tables)
    assert expected <= tables, f"faltan tablas en la migracion: {expected - tables}"
    assert "alembic_version" in tables
