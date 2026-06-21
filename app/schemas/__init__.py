from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OnboardRequest(BaseModel):
    galaxy_key: str
    planet_key: str
    race_key: str


class BuildRequest(BaseModel):
    building_key: str
    target_mineral: str | None = None


class TrainRequest(BaseModel):
    unit_key: str
    quantity: int = Field(default=1, ge=1, le=1000)


class TrainingOrderOut(BaseModel):
    id: int
    base_id: int
    unit_key: str
    quantity: int
    completes_at: datetime


class ExpeditionRequest(BaseModel):
    moon_key: str


class ExpeditionOrderOut(BaseModel):
    id: int
    moon_key: str
    completes_at: datetime


class ActiveBoonOut(BaseModel):
    source_moon: str
    effect: str
    magnitude: float
    expires_at: datetime


class ResearchRequest(BaseModel):
    tech_key: str


class ResearchOrderOut(BaseModel):
    id: int
    tech_key: str
    completes_at: datetime


class RankingEntryOut(BaseModel):
    rank: int
    id: int
    username: str
    race_key: str | None
    is_npc: bool
    score: int


class AttackRequest(BaseModel):
    target_base_id: int
    force: dict[str, int]


class AttackMissionOut(BaseModel):
    id: int
    target_base_id: int
    force: dict[str, int]
    status: str
    arrives_at: datetime
    returns_at: datetime | None = None


class IncomingAttackOut(BaseModel):
    """Fog of war: a defender sees an attack inbound, but not its composition."""

    id: int
    target_base_id: int
    arrives_at: datetime


class CombatLogOut(BaseModel):
    id: int
    attacker_id: int
    defender_id: int
    target_base_id: int
    outcome: str
    details: dict
    created_at: datetime


class BuildingOut(BaseModel):
    id: int
    building_key: str
    level: int
    status: str
    production_mineral: str | None
    completes_at: datetime


class BaseOut(BaseModel):
    id: int
    name: str
    planet_key: str
    buildings: list[BuildingOut]


class NotificationOut(BaseModel):
    id: int
    type: str
    message: str
    data: dict
    is_read: bool
    created_at: datetime


class MarkReadRequest(BaseModel):
    ids: list[int] | None = None  # None = marcar todas


class AllianceCreate(BaseModel):
    name: str = Field(min_length=3, max_length=60)
    tag: str = Field(min_length=1, max_length=8)
    type: str = "full"


class AllianceTransferRequest(BaseModel):
    to_player_id: int
    mineral: str
    amount: float = Field(gt=0)


class WorldEventOut(BaseModel):
    type: str
    message: str
    created_at: datetime


class AllianceMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=500)


class AllianceMessageOut(BaseModel):
    id: int
    sender_id: int
    sender_username: str
    body: str
    created_at: datetime


class AllianceOut(BaseModel):
    id: int
    name: str
    tag: str
    type: str
    leader_id: int
    member_count: int


class AllianceMemberOut(BaseModel):
    id: int
    username: str
    race_key: str | None
    is_npc: bool


class AllianceDetailOut(AllianceOut):
    members: list[AllianceMemberOut]


class AllianceRankingEntryOut(BaseModel):
    rank: int
    id: int
    name: str
    tag: str
    member_count: int
    score: int


class PlayerSummaryOut(BaseModel):
    id: int
    username: str
    race_key: str | None
    planet_key: str | None
    is_npc: bool
    home_base_id: int | None
    alliance_id: int | None = None


class PlayerStateOut(BaseModel):
    id: int
    username: str
    galaxy_key: str | None
    planet_key: str | None
    race_key: str | None
    energy: float
    energy_max: float
    stocks: dict[str, float]
    units: dict[str, int] = {}
    bases: list[BaseOut]
    training: list[TrainingOrderOut] = []
    expeditions: list[ExpeditionOrderOut] = []
    boons: list[ActiveBoonOut] = []
    missions_outgoing: list[AttackMissionOut] = []
    missions_incoming: list[IncomingAttackOut] = []
    technologies: list[str] = []
    research: list[ResearchOrderOut] = []
    alliance_id: int | None = None
    alliance_name: str | None = None
    alliance_type: str | None = None
    alliance_incoming: list[IncomingAttackOut] = []  # attacks on allies (shared_vision)
    unread_notifications: int = 0
