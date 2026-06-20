"""Player onboarding: choose galaxy/planet/race, create homebase + starting stock."""
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import Base_, Building, Player
from app.services.economy import get_or_create_stock

STARTING_STOCK = 500.0  # of each mineral the race actually uses


class OnboardingError(Exception):
    pass


async def onboard_player(
    session: AsyncSession, player: Player, galaxy_key: str, planet_key: str, race_key: str
) -> Base_:
    content = get_content()
    settings = get_settings()

    if player.race_key is not None:
        raise OnboardingError("El jugador ya fue inicializado.")
    if galaxy_key not in content.galaxies:
        raise OnboardingError(f"Galaxia desconocida: {galaxy_key}")
    if planet_key not in content.planets or content.planet_galaxy[planet_key] != galaxy_key:
        raise OnboardingError(f"Planeta invalido para la galaxia: {planet_key}")
    if race_key not in content.races:
        raise OnboardingError(f"Raza desconocida: {race_key}")

    now = datetime.now(UTC)
    player.galaxy_key = galaxy_key
    player.planet_key = planet_key
    player.race_key = race_key
    player.energy = settings.energy_start
    player.energy_updated_at = now

    base = Base_(player=player, planet_key=planet_key, name="Base central")
    session.add(base)
    await session.flush()

    # Headquarters is free and instantly active.
    hq = Building(
        base_id=base.id, building_key="headquarters", status="active", completes_at=now
    )
    session.add(hq)

    # Seed starting minerals for the race's resource roles.
    for role in content.races[race_key]["resource_roles"].values():
        stock = await get_or_create_stock(session, player.id, role)
        stock.amount = STARTING_STOCK

    return base
