from fastapi import APIRouter

from app.api.v1 import (
    admin,
    advisor,
    alliances,
    auth,
    bases,
    catalog,
    combat,
    expeditions,
    notifications,
    players,
    research,
    world,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(players.router, prefix="/players", tags=["players"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(bases.router, prefix="/bases", tags=["bases"])
api_router.include_router(combat.router, prefix="/combat", tags=["combat"])
api_router.include_router(expeditions.router, prefix="/expeditions", tags=["expeditions"])
api_router.include_router(research.router, prefix="/research", tags=["research"])
api_router.include_router(alliances.router, prefix="/alliances", tags=["alliances"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(world.router, prefix="/world", tags=["world"])
api_router.include_router(advisor.router, prefix="/players/me/advisor", tags=["advisor"])
