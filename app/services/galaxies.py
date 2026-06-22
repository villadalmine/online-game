"""Galaxy instances / shards (SDD 8): acotan cuántos humanos comparten un mundo.

Al hacer onboarding se asigna una instancia ABIERTA del template elegido; si todas están llenas,
se crea una nueva (seq+1). Los NPC quedan sin instancia (`galaxy_instance_id = NULL`) → son
"ambientales" (visibles/atacables desde cualquier instancia) en v1. Las interacciones humano↔humano
se filtran por instancia (combate, scoreboard). Liga con temporadas (SDD 11) y métricas (SDD 12).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.registry import get_content
from app.core.config import get_settings
from app.models import GalaxyInstance, Player


async def _open_instance(session: AsyncSession, template_key: str) -> GalaxyInstance | None:
    res = await session.execute(
        select(GalaxyInstance)
        .where(GalaxyInstance.template_key == template_key, GalaxyInstance.status == "open")
        .order_by(GalaxyInstance.seq)
        .limit(1)
    )
    return res.scalar_one_or_none()


async def assign_instance(
    session: AsyncSession, player: Player, template_key: str
) -> GalaxyInstance:
    """Asigna al jugador una instancia abierta del template; crea una nueva si están llenas."""
    inst = await _open_instance(session, template_key)
    if inst is None:
        max_seq = (
            await session.execute(
                select(func.max(GalaxyInstance.seq)).where(
                    GalaxyInstance.template_key == template_key
                )
            )
        ).scalar() or 0
        seq = int(max_seq) + 1
        gname = get_content().galaxies.get(template_key, {}).get("name", template_key)
        inst = GalaxyInstance(
            template_key=template_key,
            seq=seq,
            name=f"{gname} #{seq}",
            capacity=get_settings().galaxy_capacity,
            player_count=0,
            status="open",
        )
        session.add(inst)
        await session.flush()
    player.galaxy_instance_id = inst.id
    inst.player_count += 1
    if inst.player_count >= inst.capacity:
        inst.status = "full"
    return inst


async def instance_of(session: AsyncSession, player: Player) -> GalaxyInstance | None:
    if player.galaxy_instance_id is None:
        return None
    return await session.get(GalaxyInstance, player.galaxy_instance_id)


async def list_instances(session: AsyncSession) -> list[GalaxyInstance]:
    res = await session.execute(
        select(GalaxyInstance).order_by(GalaxyInstance.template_key, GalaxyInstance.seq)
    )
    return list(res.scalars())


async def ensure_assigned(session: AsyncSession, player: Player) -> GalaxyInstance | None:
    """Backfill perezoso: asigna instancia a un humano onboardeado que aún no la tenga (legacy)."""
    if player.is_npc or player.race_key is None or player.galaxy_instance_id is not None:
        return await instance_of(session, player)
    inst = await assign_instance(session, player, player.galaxy_key)
    await session.commit()
    return inst
