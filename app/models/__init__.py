from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_npc: Mapped[bool] = mapped_column(Boolean, default=False)
    # Admin (SDD 14 v2): gate de /admin/*. Se siembra desde ADMIN_EMAIL al crear la cuenta.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Estado de cuenta (SDD 14): active (default) | pending | suspended | rejected.
    # Solo las altas nuevas nacen pending si SIGNUP_REQUIRES_APPROVAL.
    status: Mapped[str] = mapped_column(String(20), default="active", server_default="active")
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Passwordless login por email + código OTP (SDD 6). Nullable: cuentas legacy/NPC no tienen.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True, nullable=True)

    # Set during onboarding
    galaxy_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planet_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    race_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    energy: Mapped[float] = mapped_column(Float, default=0.0)
    energy_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Plantas de energía ACTIVAS (cacheado, recomputado en finalize_due_builds): suben el tope y la
    # regen de energía. Lazy-state: se mantiene fresco antes de toda operación de energía.
    active_power_plants: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # NPC short-term memory: JSON list of recent action descriptions (last N).
    npc_memory: Mapped[str] = mapped_column(Text, default="[]")
    # NPC strategic brain (SDD 29): postura persistente decidida cada tanto leyendo el scoreboard.
    npc_posture: Mapped[str] = mapped_column(
        String(20), default="opportunist", server_default="opportunist"
    )
    npc_target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    npc_strategy: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")
    npc_strategy_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # SDD 69 Fase 4: nivel de VIDA ARTIFICIAL desarrollado en el búnker (0 = sin IA autónoma).
    ai_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # SDD 69 Fase 4: interruptor del autopiloto (el jugador lo apaga si la IA hace algo malo).
    ai_autopilot_on: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    # SDD 81: cerebro del autopiloto — rules (determinista) | gpu | cloud | auto (gpu→cloud→reglas).
    ai_brain_mode: Mapped[str] = mapped_column(String(10), default="rules", server_default="rules")
    # SDD 81 v2: rendimiento del cerebro por ruta, JSON {route:{"llm":n,"fallback":m}} → readout
    # in-game + 'auto' prefiere la ruta con mejor tasa de aplicadas (bandit con exploración).
    ai_brain_stats: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")

    # Personal AI assistant: emergency "hack" budget, reset lazily once a day (SDD 2).
    assistant_hacks_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    assistant_hacks_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Asistencia de energía por ranking (SDD 40): cupo diario con reset perezoso.
    assist_energy_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    assist_energy_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Newbie protection (SDD 11): hasta esta fecha no te pueden atacar. null = sin protección.
    protected_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Galaxy instance / shard (SDD 8). null = global (NPCs) o legacy sin asignar.
    galaxy_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("galaxy_instances.id", ondelete="SET NULL"), nullable=True, index=True
    )

    alliance_id: Mapped[int | None] = mapped_column(
        ForeignKey("alliances.id", ondelete="SET NULL"), nullable=True, index=True
    )

    bases: Mapped[list["Base_"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )
    stocks: Mapped[list["ResourceStock"]] = relationship(
        back_populates="player", cascade="all, delete-orphan"
    )


class Base_(Base):
    __tablename__ = "bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    planet_key: Mapped[str] = mapped_column(String(50))
    name: Mapped[str] = mapped_column(String(80))
    # Tipo de base (SDD 37 v2): surface (terrestre) | orbital (estación con robots, sin habitar).
    base_type: Mapped[str] = mapped_column(String(20), default="surface", server_default="surface")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    player: Mapped[Player] = relationship(back_populates="bases")
    buildings: Mapped[list["Building"]] = relationship(
        back_populates="base", cascade="all, delete-orphan"
    )


class Building(Base):
    __tablename__ = "buildings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("bases.id", ondelete="CASCADE"), index=True)
    building_key: Mapped[str] = mapped_column(String(50))
    level: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(20), default="building")  # building | active
    # SDD 66: condición 0-100 (100 = sana). El daño de misiles/bombardeo la baja (gradual, gated por
    # `building_condition_enabled`); < 50 = averiada (rinde a fracción); 0 = destruida.
    condition: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")

    # For mines: which mineral this extracts + lazy production bookkeeping
    production_mineral: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_collected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    base: Mapped[Base_] = relationship(back_populates="buildings")


class ResourceStock(Base):
    __tablename__ = "resource_stocks"
    # SDD 42 Fase 2: el stock es POR PLANETA (el material vive donde está). Único por (jugador,
    # mineral, planeta). El agregado por jugador se calcula sumando (economy.player_stocks).
    __table_args__ = (
        UniqueConstraint("player_id", "mineral_key", "planet_key", name="uq_player_mineral_planet"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    mineral_key: Mapped[str] = mapped_column(String(50))
    planet_key: Mapped[str] = mapped_column(String(50), default="", server_default="")
    amount: Mapped[float] = mapped_column(Float, default=0.0)

    player: Mapped[Player] = relationship(back_populates="stocks")


class UnitStock(Base):
    """How many of each unit a player has (counts), like ResourceStock for minerals.

    SDD 62 (guarnición): `base_id` ubica la unidad en una base. NULL = pool global del jugador
    (comportamiento histórico, modo `garrison_enabled=False`). Con guarnición, cada base tiene sus
    propias tropas. `player_units` suma todas las filas (global) → el modo OFF no cambia."""

    __tablename__ = "unit_stocks"
    __table_args__ = (
        UniqueConstraint("player_id", "unit_key", "base_id", name="uq_player_unit_base"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    unit_key: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    base_id: Mapped[int | None] = mapped_column(
        ForeignKey("bases.id", ondelete="CASCADE"), nullable=True, index=True
    )

    player: Mapped[Player] = relationship()


class TroopMove(Base):
    """SDD 62: traslado de tropas entre bases propias. Salen de `from_base` al crearse y se
    depositan en `to_base` al llegar (lazy by timestamp)."""

    __tablename__ = "troop_moves"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    from_base_id: Mapped[int] = mapped_column(ForeignKey("bases.id", ondelete="CASCADE"))
    to_base_id: Mapped[int] = mapped_column(ForeignKey("bases.id", ondelete="CASCADE"))
    units: Mapped[str] = mapped_column(Text, default="{}")   # JSON unit_key -> qty
    status: Mapped[str] = mapped_column(String(20), default="moving")  # moving | done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TrainingOrder(Base):
    """A queued batch of units; lands in UnitStock when its timer elapses."""

    __tablename__ = "training_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("bases.id", ondelete="CASCADE"), index=True)
    unit_key: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="training")  # training | done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    base: Mapped[Base_] = relationship()


class ExpeditionOrder(Base):
    """A mission to a moon; delivers grants + a boon when its timer elapses."""

    __tablename__ = "expedition_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    moon_key: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="traveling")  # traveling | done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    player: Mapped[Player] = relationship()


class ActiveBoon(Base):
    """A temporary buff granted by a god. Applied lazily while expires_at > now."""

    __tablename__ = "active_boons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    source_moon: Mapped[str] = mapped_column(String(50))
    effect: Mapped[str] = mapped_column(String(30))  # production | attack | defense
    magnitude: Mapped[float] = mapped_column(Float, default=1.0)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    player: Mapped[Player] = relationship()


class AttackMission(Base):
    """A fleet in transit. Committed units are removed from the attacker's stock while
    away; the battle resolves on arrival and survivors+loot return later."""

    __tablename__ = "attack_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attacker_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    defender_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_base_id: Mapped[int] = mapped_column(Integer)
    # SDD 62: base de la que SALEN las tropas (guarnición). NULL = pool global (modo histórico).
    source_base_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    force: Mapped[str] = mapped_column(Text, default="{}")  # JSON unit_key -> qty
    status: Mapped[str] = mapped_column(String(20), default="outbound")  # outbound|returning|done
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON: outcome/loot/survivors
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    returns_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class StrikeMission(Base):
    """Una salva de misiles en vuelo intra-planeta (SDD 49). Los misiles se consumen al lanzarse
    (se descuentan del stock); resuelve al llegar (intercepción + daño) y NO vuelve."""

    __tablename__ = "strike_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attacker_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    defender_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    launcher_base_id: Mapped[int] = mapped_column(Integer)
    target_base_id: Mapped[int] = mapped_column(Integer)
    force: Mapped[str] = mapped_column(Text, default="{}")  # JSON missile_key -> qty
    status: Mapped[str] = mapped_column(String(20), default="outbound")  # outbound|done|cancelled
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON: impacted/intercepted/damage
    # SDD 67: oferta de tributo del defensor (diplomacia nuclear). JSON {minerals:{}, energy}.
    tribute: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuantumInfection(Base):
    """SDD 87: un gusano de IA cuántica infectando una base. Mientras `active` DRENA (penaliza la
    producción, progresivo 1%→80% en ~7 días, derivado de `created_at`). Se desactiva mandando
    tropas, pagando rescate, o con tech cuántica (`disarm=quantum`) — en ese último caso queda
    `leaking=True`: filtra la info de la base al atacante hasta que orbite un inhibidor."""

    __tablename__ = "quantum_infections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    defender_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    attacker_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    base_id: Mapped[int] = mapped_column(Integer, index=True)
    status: Mapped[str] = mapped_column(String(20), default="active")   # active|disarmed
    disarm: Mapped[str | None] = mapped_column(String(20), nullable=True)  # troops|ransom|quantum
    leaking: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    disarmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DroneSquadron(Base):
    """Un escuadrón de drones orbitando una base enemiga del mismo planeta (SDD 50). Lazy por
    timestamp: al leer, `advance_drones` aplica los ticks transcurridos (derribos por torretas,
    drenaje de TU energía, daño de ataque) y mata el escuadrón sin energía o sin drones."""

    __tablename__ = "drone_squadrons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    factory_base_id: Mapped[int] = mapped_column(Integer)
    target_base_id: Mapped[int] = mapped_column(Integer)
    planet_key: Mapped[str] = mapped_column(String(50), default="")
    force: Mapped[str] = mapped_column(Text, default="{}")  # JSON drone_key -> qty alive
    status: Mapped[str] = mapped_column(String(20), default="orbiting")  # orbiting|dead|recalled
    max_ticks: Mapped[int | None] = mapped_column(Integer, nullable=True)  # tope opcional del panel
    ticks_done: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_tick_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SatelliteMission(Base):
    """SDD 61: un satélite en órbita. `kind=survey` orbita tu planeta; `kind=spy` orbita el de un
    enemigo y acumula `discovered_pct` (mapa de sus bases). Lazy by timestamp: `advance_satellites`
    aplica las órbitas (sube el %, drena energía, lo bajan los drones, deorbita)."""

    __tablename__ = "satellite_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), nullable=True, index=True
    )
    unit_key: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(20), default="spy")   # survey | spy
    target_planet: Mapped[str] = mapped_column(String(50), default="")
    shield_grade: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    energy: Mapped[float] = mapped_column(Float, default=0.0)
    discovered_pct: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="orbiting")  # orbiting|lost|deorbited
    last_tick_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Bunker(Base):
    """SDD 64: búnker subterráneo bajo una base. Mapa de habitaciones + medidores de salud
    (comida/agua/gente, 0-100) que regeneran lazy por las salas y bajan por sabotaje."""

    __tablename__ = "bunkers"
    __table_args__ = (UniqueConstraint("base_id", name="uq_bunker_base"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    base_id: Mapped[int] = mapped_column(ForeignKey("bases.id", ondelete="CASCADE"), index=True)
    food_health: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")
    water_health: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")
    people_health: Mapped[float] = mapped_column(Float, default=100.0, server_default="100")
    # SDD 64 v2: electrónica (research_room/atomic_lab) → moneda de repoblación.
    electronics: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    # SDD 69 Fase 1: excavaciones hechas → lado efectivo de la grilla = bunker_grid + grid_level.
    grid_level: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BunkerRoom(Base):
    """SDD 64: una habitación del búnker en una celda del mapa subterráneo."""

    __tablename__ = "bunker_rooms"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bunker_id: Mapped[int] = mapped_column(ForeignKey("bunkers.id", ondelete="CASCADE"), index=True)
    room_key: Mapped[str] = mapped_column(String(50))
    cell: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="building")  # building | active
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BunkerStock(Base):
    """SDD 69 Fase 1: mineral guardado en la BÓVEDA de un búnker. Vive bajo tierra → el saqueo de
    combate (que solo toca ResourceStock de superficie) NO lo alcanza: reserva para reconstruir y
    volver a conquistar tras una guerra. Capacidad = Σ storage de las salas `vault` activas."""

    __tablename__ = "bunker_stocks"
    __table_args__ = (UniqueConstraint("bunker_id", "mineral_key", name="uq_bunker_stock"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bunker_id: Mapped[int] = mapped_column(ForeignKey("bunkers.id", ondelete="CASCADE"), index=True)
    mineral_key: Mapped[str] = mapped_column(String(50))
    amount: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")


class BunkerRaid(Base):
    """SDD 64: una incursión de sabotaje sobre el búnker de un rival (gas/ratas/agua). Log para el
    tope diario e historial."""

    __tablename__ = "bunker_raids"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attacker_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    bunker_id: Mapped[int] = mapped_column(ForeignKey("bunkers.id", ondelete="CASCADE"))
    action: Mapped[str] = mapped_column(String(20))   # gas | rats | water
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SpyMission(Base):
    """Espías en tránsito hacia un objetivo (SDD 35). Resuelven al llegar (generan intel) y vuelven;
    si los detectan, algunos caen y el defensor es notificado."""

    __tablename__ = "spy_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observer_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_base_id: Mapped[int] = mapped_column(Integer)
    force: Mapped[str] = mapped_column(Text, default="{}")  # JSON {spy: qty}
    status: Mapped[str] = mapped_column(String(20), default="outbound")  # outbound|returning|done
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON: depth/detected/losses
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    returns_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class IntelReport(Base):
    """Inteligencia acumulada de un observador sobre un objetivo (SDD 35). Única por par; se
    actualiza al espiar. `payload` = campos revelados según `depth`; `as_of` para la confianza."""

    __tablename__ = "intel_reports"
    __table_args__ = (
        UniqueConstraint("observer_id", "target_id", name="uq_intel_obs_target"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    observer_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    depth: Mapped[float] = mapped_column(Float, default=0.0)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Alliance(Base):
    """A group of players who can't attack each other."""

    __tablename__ = "alliances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    tag: Mapped[str] = mapped_column(String(8))
    type: Mapped[str] = mapped_column(String(30), default="full")
    leader_id: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AllianceMessage(Base):
    """A chat message posted to an alliance, visible only to its members."""

    __tablename__ = "alliance_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alliance_id: Mapped[int] = mapped_column(
        ForeignKey("alliances.id", ondelete="CASCADE"), index=True
    )
    sender_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerStats(Base):
    """Contadores de por vida de un jugador (SDD 12), incrementados en los procesadores."""

    __tablename__ = "player_stats"

    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    battles_won: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    battles_lost: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attacks_launched: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    buildings_built: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    units_trained: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    research_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expeditions_completed: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    resources_mined: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    resources_looted: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    resources_lost: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")


class PlayerSample(Base):
    """SDD 51 — muestra periódica del ESTADO de un jugador (energía/stock/unidades/score) para
    graficar 'cómo me fue en el tiempo'. Append-only, throttleada en state.advance (lazy, sin cron).
    Los EVENTOS (ataques/builds/…) ya salen del journal (SDD 38); esto cubre el estado, que no es
    un evento. Index (player_id, at) para consultas por rango baratas."""

    __tablename__ = "player_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    energy: Mapped[float] = mapped_column(Float, default=0.0)
    energy_max: Mapped[float] = mapped_column(Float, default=0.0)
    stock_total: Mapped[float] = mapped_column(Float, default=0.0)
    units_total: Mapped[int] = mapped_column(Integer, default=0)
    score: Mapped[int] = mapped_column(Integer, default=0)
    stocks_json: Mapped[str] = mapped_column(Text, default="{}")
    units_json: Mapped[str] = mapped_column(Text, default="{}")


class GalaxyInstance(Base):
    """Instancia jugable de una galaxia (shard, SDD 8): acota cuántos humanos comparten mundo.
    `template_key` = la galaxia data-driven (milky_way…); al llenarse, los nuevos van a otra."""

    __tablename__ = "galaxy_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    template_key: Mapped[str] = mapped_column(String(50), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(80))
    capacity: Mapped[int] = mapped_column(Integer)
    player_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | full
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Season(Base):
    """Temporada (SDD 11): ventana de tiempo sobre el mundo persistente. Al cerrar, los mejores
    entran al Hall of Fame y arranca la siguiente. El imperio NO se borra."""

    __tablename__ = "seasons"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    seq: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)  # active|closed
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class HallOfFame(Base):
    """Posición final de un jugador en una temporada cerrada (persiste para siempre, SDD 11)."""

    __tablename__ = "hall_of_fame"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id", ondelete="CASCADE"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(50))  # snapshot para mostrar sin join
    rank: Mapped[int] = mapped_column(Integer)
    points: Mapped[int] = mapped_column(Integer)
    awarded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EmailOtp(Base):
    """Código OTP pendiente por email (SDD 6). `email` PK ⇒ pedir uno nuevo reemplaza el anterior.
    El código se guarda hasheado (HMAC), nunca en claro."""

    __tablename__ = "email_otps"

    email: Mapped[str] = mapped_column(String(254), primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdvisorMessage(Base):
    """A turn in the player's conversation with their personal AI assistant (SDD 2)."""

    __tablename__ = "advisor_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))  # user | assistant
    body: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PlayerTech(Base):
    """A technology a player has finished researching (grants a permanent effect)."""

    __tablename__ = "player_techs"
    __table_args__ = (UniqueConstraint("player_id", "tech_key", name="uq_player_tech"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    tech_key: Mapped[str] = mapped_column(String(50))


class ResearchOrder(Base):
    """A technology being researched; becomes a PlayerTech when its timer elapses."""

    __tablename__ = "research_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    tech_key: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="researching")  # researching | done
    completes_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    """An event the player should see (incoming attack, battle result, queue done…)."""

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    message: Mapped[str] = mapped_column(String(255))
    data: Mapped[str] = mapped_column(Text, default="{}")
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorldEvent(Base):
    """Evento dinámico activo del mundo (SDD 36, "happy hour"). Activo si starts_at ≤ now < ends_at.
    `effect`/`magnitude` se leen perezosamente (apilan como un multiplicador más)."""

    __tablename__ = "world_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(40), index=True)
    effect: Mapped[str] = mapped_column(String(30))
    magnitude: Mapped[float] = mapped_column(Float, default=1.0)
    scope: Mapped[str] = mapped_column(String(40), default="all")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")


class EventGrant(Base):
    """Marca que un jugador ya reclamó un evento one-shot (p.ej. free_units), para no repetir."""

    __tablename__ = "event_grants"
    __table_args__ = (UniqueConstraint("player_id", "event_id", name="uq_event_grant"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("world_events.id", ondelete="CASCADE"))


class MarketPrice(Base):
    """Precio dinámico del hub galáctico (SDD 42 Fase 3): un precio por (galaxia, mineral) que se
    mueve por oferta/demanda (comprar sube, vender baja) y revierte lento al valor intrínseco."""

    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint("galaxy_key", "mineral_key", name="uq_market_price"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    galaxy_key: Mapped[str] = mapped_column(String(50), index=True)
    mineral_key: Mapped[str] = mapped_column(String(50))
    price: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TransportMission(Base):
    """Transporte de minerales entre planetas del jugador (SDD 42 Fase 2). Sale del planeta origen,
    viaja, y al llegar acredita la carga al planeta destino (las naves vuelven al stock)."""

    __tablename__ = "transport_missions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    from_planet: Mapped[str] = mapped_column(String(50))
    to_planet: Mapped[str] = mapped_column(String(50))
    cargo: Mapped[str] = mapped_column(Text, default="{}")        # {mineral: qty}
    escort: Mapped[str] = mapped_column(Text, default="{}", server_default="{}")  # {unit: qty}
    ships: Mapped[int] = mapped_column(Integer, default=1)        # naves de carga usadas
    status: Mapped[str] = mapped_column(String(20), default="outbound")  # outbound | done
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GameEvent(Base):
    """Append-only journal of everything players do (SDD 38): `id` = orden total (seq).
    Fuente de verdad para medir todo, exportar la partida a YAML y reproducirla."""

    __tablename__ = "game_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # autoincrement = seq global
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"), index=True, nullable=True
    )
    type: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    # Versión del juego al ocurrir el evento (SDD 41): permite segmentar/ventanear los datos cuando
    # cambian unidades/balance/reglas → la data vieja sigue sirviendo (sabés de qué ruleset es).
    version: Mapped[str] = mapped_column(
        String(20), default="dev", server_default="dev", index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class MetaInsight(Base):
    """Insight agregado del meta (SDD 41), upsert por `key`. Datos derivados del journal que el
    asistente y los NPCs leen para jugar/aconsejar con datos reales. Base para dashboards y ML."""

    __tablename__ = "meta_insights"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    payload: Mapped[str] = mapped_column(Text, default="{}")
    sample_n: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CombatLog(Base):
    """Persisted battle report (history). `details` holds a JSON blob."""

    __tablename__ = "combat_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attacker_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    defender_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    target_base_id: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(20))  # attacker | defender | draw
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
