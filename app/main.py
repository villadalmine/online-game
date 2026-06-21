import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.responses import FileResponse

from app.api.v1 import api_router
from app.core.config import REPO_ROOT, get_settings
from app.core.db import SessionLocal, run_migrations

settings = get_settings()
WEB_INDEX = REPO_ROOT / "web" / "index.html"


async def _auto_tick_loop(interval: int) -> None:
    """Advance the world periodically so the game is alive without manual ticks."""
    from app.worker import run_tick

    while True:
        await asyncio.sleep(interval)
        try:
            async with SessionLocal() as session:
                await run_tick(session)
        except Exception:  # never let a bad tick kill the loop
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Apply migrations on startup so schema changes take effect with no manual reset.
    # Run in a thread because Alembic's async env uses asyncio.run internally.
    await asyncio.to_thread(run_migrations)
    brain = settings.npc_brain
    if brain == "llm":
        brain = f"llm@{settings.llm_url} ({settings.llm_model_name})"
    print(
        f"[online-game] DB={settings.db_backend} ({settings.safe_database_url}) · "
        f"auto-tick={settings.auto_tick_seconds}s · npc={brain} · migraciones aplicadas ✓",
        flush=True,
    )
    task = None
    if settings.auto_tick_seconds > 0:
        task = asyncio.create_task(_auto_tick_loop(settings.auto_tick_seconds))
    try:
        yield
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "app": settings.app_name, "db": settings.db_backend}


@app.get("/", include_in_schema=False)
async def web_client():
    """Minimal playable web UI (vanilla JS, talks to /api/v1)."""
    return FileResponse(WEB_INDEX)
