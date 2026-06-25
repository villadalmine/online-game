import asyncio
import contextlib
import hmac
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import FileResponse, HTMLResponse, PlainTextResponse, Response

from app.api.v1 import api_router
from app.core import metrics
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
    # Secretos fuertes en prod (deuda técnica): en production, secretos default/cortos frenan el
    # arranque (el pod no levanta → fuerza arreglarlo); en dev solo avisa.
    weak = settings.weak_secrets()
    if weak:
        msg = f"secretos débiles (default/cortos): {', '.join(weak)} — seteá valores fuertes"
        if settings.is_production:
            raise RuntimeError(f"[online-game] arranque abortado en production: {msg}")
        print(f"[online-game] ⚠️  {msg}", flush=True)
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


@app.exception_handler(StarletteHTTPException)
async def _i18n_http_exception(request: Request, exc: StarletteHTTPException):
    """Traduce el `detail` de los errores conocidos a EN si el request pide inglés (SDD 4)."""
    from fastapi.exception_handlers import http_exception_handler

    from app.content.registry import normalize_lang
    from app.core import i18n_errors

    if isinstance(exc.detail, str):
        lang = normalize_lang(
            request.query_params.get("lang") or request.headers.get("accept-language")
        )
        if lang == "en":
            exc.detail = i18n_errors.translate(exc.detail, "en")
    return await http_exception_handler(request, exc)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    """RED por request (SDD 19). Usa el path-template (no la URL con ids) para no inflar labels."""
    metrics.IN_FLIGHT.inc()
    start = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        metrics.IN_FLIGHT.dec()
        route = request.scope.get("route")
        path = getattr(route, "path", None) or request.url.path
        if path != "/metrics":  # no medirse a sí mismo
            method = request.method
            metrics.HTTP_REQUESTS.inc(method=method, path=path, status=str(status_code))
            metrics.HTTP_DURATION.observe(time.perf_counter() - start, method=method, path=path)


@app.get("/metrics", include_in_schema=False)
async def metrics_endpoint(request: Request):
    """Exposición Prometheus. NO público: si METRICS_TOKEN está seteado, exige Bearer (Prometheus
    lo manda vía bearerTokenSecret). Vacío = abierto (dev). El scrapeo real es in-cluster."""
    token = settings.metrics_token
    if token:
        auth = request.headers.get("authorization", "")
        provided = auth[7:] if auth.lower().startswith("bearer ") else ""
        if not hmac.compare_digest(provided, token):
            return Response(status_code=401)
    # gauges calculados al scrapear: totales + presencia (SDD 21)
    try:
        from sqlalchemy import func, select

        from app.core.redis import get_redis
        from app.models import GalaxyInstance, Player
        from app.services import presence

        redis = await get_redis()
        online = await presence.online_ids(redis)
        metrics.ONLINE_PLAYERS.set(len(online))
        async with SessionLocal() as s:
            n = (
                await s.execute(select(func.count()).select_from(Player).where(~Player.is_npc))
            ).scalar_one()
            metrics.PLAYERS_TOTAL.set(n)
            # opt-in por jugador (cardinalidad): 1 serie por online, filtrable por player/galaxy
            metrics.PLAYER_ONLINE.clear()
            if settings.metrics_per_player and online:
                ids = online[: settings.metrics_per_player_max]
                rows = (
                    await s.execute(
                        select(Player.username, GalaxyInstance.name)
                        .join(GalaxyInstance, Player.galaxy_instance_id == GalaxyInstance.id,
                              isouter=True)
                        .where(Player.id.in_(ids))
                    )
                ).all()
                for username, galaxy in rows:
                    metrics.PLAYER_ONLINE.set(1, player=username, galaxy=galaxy or "-")
    except Exception:
        pass
    return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok", "app": settings.app_name, "db": settings.db_backend}


# El HTML se sirve con `no-cache`: el navegador igual usa ETag para 304s, pero SIEMPRE revalida →
# tras un deploy ves la versión nueva sin hard-refresh (antes quedaba cacheado el HTML viejo).
_NOCACHE = {"Cache-Control": "no-cache"}


@app.get("/", include_in_schema=False)
async def web_client():
    """Minimal playable web UI (vanilla JS, talks to /api/v1)."""
    return FileResponse(WEB_INDEX, headers=_NOCACHE)


@app.get("/game", include_in_schema=False)
async def landing():
    """Landing pública para compartir (SDD 24): bilingüe + Open Graph. Inyecta PUBLIC_URL para que
    og:url/og:image sean absolutas (preview en redes)."""
    html = (REPO_ROOT / "web" / "landing.html").read_text(encoding="utf-8")
    return HTMLResponse(
        html.replace("__PUBLIC_URL__", settings.public_url.rstrip("/")), headers=_NOCACHE
    )


@app.get("/tech", include_in_schema=False)
async def tech_page():
    """Página técnica pública: stack del PoC self-hosted + flujo de tráfico (HAProxy SNI → Cilium
    Gateway → Service → Pod). Estática y sin dependencias externas (coherente con self-hosted)."""
    return FileResponse(REPO_ROOT / "web" / "tech.html", headers=_NOCACHE)


@app.get("/og-image.png", include_in_schema=False)
async def og_image():
    img = REPO_ROOT / "web" / "og-image.png"
    if not img.exists():
        return Response(status_code=404)
    return FileResponse(img, media_type="image/png")
