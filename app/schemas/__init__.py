from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6, max_length=128)
    # Requerido si hay allowlist activa (SDD 14): el email debe estar autorizado.
    email: str | None = Field(default=None, max_length=254)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ---- SDD 6: passwordless login (email + código OTP) -------------------------
class RequestCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class RequestCodeResponse(BaseModel):
    sent: bool = True


class VerifyCodeRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=4, max_length=12)


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


class SpyRequest(BaseModel):
    target_base_id: int
    spies: dict[str, int] = {"spy": 1}


class SpyMissionOut(BaseModel):
    id: int
    target_base_id: int
    status: str
    arrives_at: datetime


class IntelReportOut(BaseModel):
    target_id: int
    target: str | None
    depth: float
    confidence: float
    as_of: datetime
    payload: dict


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


# ---- SDD 8: galaxy instances ------------------------------------------------
class GalaxyInstanceOut(BaseModel):
    id: int
    template_key: str
    seq: int
    name: str
    capacity: int
    player_count: int
    status: str


# ---- SDD 11: temporadas + Hall of Fame --------------------------------------
class SeasonOut(BaseModel):
    id: int
    seq: int
    name: str
    starts_at: datetime
    ends_at: datetime
    status: str


class SeasonRankingEntryOut(BaseModel):
    rank: int
    player_id: int
    username: str
    score: int


class HallOfFameEntryOut(BaseModel):
    season_id: int
    rank: int
    username: str
    points: int
    awarded_at: datetime


# ---- SDD 12: métricas + showcase público ------------------------------------
class PlayerStatsOut(BaseModel):
    battles_won: int = 0
    battles_lost: int = 0
    attacks_launched: int = 0
    buildings_built: int = 0
    units_trained: int = 0
    research_completed: int = 0
    expeditions_completed: int = 0
    resources_mined: float = 0
    resources_looted: float = 0
    resources_lost: float = 0


class PublicLeaderboardEntryOut(BaseModel):
    rank: int
    username: str
    race_key: str | None = None
    score: int


class GlobalStatsOut(BaseModel):
    players: int
    empires: int
    battles: int
    minerals_mined: float
    season: SeasonOut | None = None


class PublicProfileOut(BaseModel):
    username: str
    race_key: str | None = None
    planet_key: str | None = None
    is_npc: bool = False
    score: int
    stats: PlayerStatsOut
    seasons_played: int
    best_rank: int | None = None
    hof_count: int
    season_history: list[HallOfFameEntryOut] = []


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
    protected_until: datetime | None = None          # newbie protection (SDD 11)
    season: SeasonOut | None = None                  # temporada actual
    galaxy_instance: GalaxyInstanceOut | None = None  # tu shard de galaxia (SDD 8)


# ---- SDD 1: dependency graph -------------------------------------------------
class Cost(BaseModel):
    minerals: dict[str, float] = {}
    energy: float = 0.0


class Source(BaseModel):
    """How to obtain a mineral when your planet doesn't produce it."""
    kind: str  # local_mine | expedition | loot | alliance_trade
    detail: str
    estimate_per_hour: float | None = None


class Blocker(BaseModel):
    kind: str  # mineral | energy | building | not_producible
    key: str
    have: float
    need: float
    sources: list[Source] = []


class BlockerReport(BaseModel):
    target: str
    buildable: bool
    blockers: list[Blocker] = []
    prerequisites: list[str] = []  # buildings to have active first, topological order


# ---- SDD 2: personal AI assistant -------------------------------------------
class AdvisorAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class Suggestion(BaseModel):
    action: str  # build | train | research | expedition (same shape NPCs dispatch)
    label: str = ""
    params: dict = {}


class AdvisorReply(BaseModel):
    reply: str
    blockers: list[BlockerReport] = []
    suggestions: list[Suggestion] = []
    hack_available: bool = False
    hacks_left: int = 0


class AdvisorHackRequest(BaseModel):
    target: str = Field(min_length=1, max_length=50)


class AdvisorHackResult(BaseModel):
    granted: dict[str, float] = {}
    message: str
    hacks_left: int


class AdvisorMessageOut(BaseModel):
    id: int
    role: str
    body: str
    created_at: datetime
