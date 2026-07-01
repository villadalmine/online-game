from fastapi import APIRouter

from app.api.v1 import (
    admin,
    advisor,
    alliances,
    announcements,
    auth,
    bases,
    bunker,
    catalog,
    colonize,
    combat,
    drones,
    events,
    expeditions,
    galaxies,
    insights,
    intel,
    journal,
    market,
    notifications,
    players,
    public,
    research,
    satellites,
    seasons,
    tts,
    universes,
    world,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(bases.router, prefix="/bases", tags=["bases"])
api_router.include_router(combat.router, prefix="/combat", tags=["combat"])
api_router.include_router(drones.router, prefix="/drones", tags=["drones"])
api_router.include_router(satellites.router, prefix="/satellites", tags=["satellites"])
api_router.include_router(bunker.router, prefix="/bunker", tags=["bunker"])
api_router.include_router(expeditions.router, prefix="/expeditions", tags=["expeditions"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(alliances.router, prefix="/alliances", tags=["alliances"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(world.router, prefix="/world", tags=["world"])
api_router.include_router(seasons.router, prefix="/seasons", tags=["seasons"])
api_router.include_router(galaxies.router, prefix="/galaxies", tags=["galaxies"])
api_router.include_router(public.router, prefix="/public", tags=["public"])
api_router.include_router(intel.router, tags=["intel"])
api_router.include_router(journal.router, tags=["journal"])
api_router.include_router(insights.router, tags=["insights"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(announcements.router, prefix="/announcements", tags=["announcements"])
api_router.include_router(universes.router, prefix="/universes", tags=["universes"])
api_router.include_router(colonize.router, prefix="/colonize", tags=["colonize"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(advisor.router, prefix="/players/me/advisor", tags=["advisor"])
api_router.include_router(tts.router, tags=["tts"])
