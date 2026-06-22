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
    # Passwordless login por email + código OTP (SDD 6). Nullable: cuentas legacy/NPC no tienen.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True, nullable=True)

    # Set during onboarding
    galaxy_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planet_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    race_key: Mapped[str | None] = mapped_column(String(50), nullable=True)

    energy: Mapped[float] = mapped_column(Float, default=0.0)
    energy_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    # NPC short-term memory: JSON list of recent action descriptions (last N).
    npc_memory: Mapped[str] = mapped_column(Text, default="[]")

    # Personal AI assistant: emergency "hack" budget, reset lazily once a day (SDD 2).
    assistant_hacks_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    assistant_hacks_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    __table_args__ = (UniqueConstraint("player_id", "mineral_key", name="uq_player_mineral"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    mineral_key: Mapped[str] = mapped_column(String(50))
    amount: Mapped[float] = mapped_column(Float, default=0.0)

    player: Mapped[Player] = relationship(back_populates="stocks")


class UnitStock(Base):
    """How many of each unit a player has (counts), like ResourceStock for minerals."""

    __tablename__ = "unit_stocks"
    __table_args__ = (UniqueConstraint("player_id", "unit_key", name="uq_player_unit"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), index=True)
    unit_key: Mapped[str] = mapped_column(String(50))
    quantity: Mapped[int] = mapped_column(Integer, default=0)

    player: Mapped[Player] = relationship()


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
    force: Mapped[str] = mapped_column(Text, default="{}")  # JSON unit_key -> qty
    status: Mapped[str] = mapped_column(String(20), default="outbound")  # outbound|returning|done
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON: outcome/loot/survivors
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    arrives_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    returns_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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
