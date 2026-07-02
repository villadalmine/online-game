from datetime import datetime
from typing import Literal

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


class MarketTradeRequest(BaseModel):
    planet_key: str
    mineral_key: str
    qty: int


class HubTradeRequest(BaseModel):
    mineral_key: str
    qty: int
    escort: dict[str, int] | None = None


class BlackMarketRequest(BaseModel):
    pay_mineral: str
    pay_qty: int
    get_mineral: str
    escort: dict[str, int] | None = None


class TransportRequest(BaseModel):
    from_planet: str
    to_planet: str
    cargo: dict[str, int]
    escort: dict[str, int] | None = None


class TransportMissionOut(BaseModel):
    id: int
    from_planet: str
    to_planet: str
    cargo: dict[str, int]
    escort: dict[str, int] = {}
    ships: int
    status: str
    arrives_at: datetime


class AssistEnergyResult(BaseModel):
    granted: float
    energy: float
    deficit: float          # 0..1: qué tan por debajo del promedio estás (0 = en/sobre el promedio)
    left: int
    message: str = ""


class ProfileUpdateRequest(BaseModel):
    # Cambiar nick y/o contraseña (autenticado, sin validar email). Al menos uno.
    username: str | None = Field(default=None, min_length=3, max_length=50)
    password: str | None = Field(default=None, min_length=6, max_length=200)


class ProfileUpdateResponse(BaseModel):
    username: str
    access_token: str   # token nuevo (el nick va en el token); seguí logueado


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
    returns_at: datetime | None = None


class IntelReportOut(BaseModel):
    target_id: int
    target: str | None
    depth: float
    confidence: float
    as_of: datetime
    payload: dict
    shared: bool = False      # intel aportada por un aliado (shared_vision), no espiada por vos
    via: str | None = None    # aliado que la consiguió (si shared)


class AttackRequest(BaseModel):
    target_base_id: int
    force: dict[str, int]
    source_base_id: int | None = None   # SDD 62: base de la que salen las tropas (guarnición)


class MoveTroopsRequest(BaseModel):
    to_base_id: int
    units: dict[str, int]


class SatelliteLaunchRequest(BaseModel):
    unit_key: str                       # survey_satellite | spy_satellite
    target_id: int | None = None        # jugador objetivo (solo para spy)


class BunkerDigRequest(BaseModel):
    base_id: int


class BunkerBuildRequest(BaseModel):
    base_id: int
    room_key: str
    cell: int


class BunkerRaidRequest(BaseModel):
    target_id: int
    action: str   # gas | rats | water


class TributeRequest(BaseModel):
    minerals: dict[str, float] = {}
    energy: float = 0.0


class TroopMoveOut(BaseModel):
    id: int
    from_base_id: int
    to_base_id: int
    units: dict[str, int]
    status: str
    arrives_at: datetime


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


class ColonizeRequest(BaseModel):
    planet_key: str
    mode: str = "surface"   # surface | orbital


class ColonyOut(BaseModel):
    base_id: int
    planet_key: str
    name: str
    base_type: str = "surface"


class ColonizeOptionOut(BaseModel):
    planet: str
    name: str
    habitability: float
    can_colonize: bool
    verdict: str            # great | ok | poor | impossible
    modifiers: dict
    reasons: list[str]
    is_home: bool = False
    abundance_highlights: list[str] = []
    # Pre-cálculo: costo que tendría fundar acá ahora (energía + transbordadores), por modo.
    energy_surface: float = 0.0
    energy_orbital: float = 0.0
    shuttle_cost: int = 1


class ActiveEventOut(BaseModel):
    key: str
    name: str
    description: str
    icon: str
    effect: str
    magnitude: float
    ends_at: datetime


class JournalEventOut(BaseModel):
    seq: int
    at: datetime
    player_id: int | None
    type: str
    payload: dict


class CombatSimRequest(BaseModel):
    attacker_force: dict[str, int]
    defender_force: dict[str, int] = {}
    attacker_atk_mult: float = 1.0
    defender_def_mult: float = 1.0
    defender_flat_defense: float = 0.0


class CombatSimOut(BaseModel):
    outcome: str
    attack_score: float
    defense_score: float
    attacker_losses: dict[str, int] = {}
    defender_losses: dict[str, int] = {}


# ---- SDD 49: lanzadera de misiles ------------------------------------------
class StrikeRequest(BaseModel):
    launcher_base_id: int
    target_base_id: int
    force: dict[str, int]


class StrikeMissionOut(BaseModel):
    id: int
    launcher_base_id: int
    target_base_id: int
    force: dict[str, int]
    status: str
    arrives_at: datetime
    tribute: dict | None = None      # SDD 67: oferta de tributo del defensor (si la hay)


class IncomingStrikeOut(BaseModel):
    id: int
    target_base_id: int
    arrives_at: datetime
    is_nuclear: bool = False         # SDD 67: solo el nuclear se puede negociar
    tribute: dict | None = None      # lo que ya ofreciste (para no re-ofrecer)
    can_offer: bool = False          # tenés government activo + diplomacy


class StrikeSimRequest(BaseModel):
    force: dict[str, int]
    intercept_capacity: float = 0.0   # = Σ intercept_power de las torretas activas del rival
    atk_mult: float = 1.0


class StrikeSimOut(BaseModel):
    impacted: dict[str, int] = {}
    intercepted: dict[str, int] = {}
    damage: float = 0.0
    area: bool = False


# ---- SDD 50: drones intra-planeta ------------------------------------------
class DroneLaunchRequest(BaseModel):
    factory_base_id: int
    target_base_id: int
    force: dict[str, int]
    max_ticks: int | None = None


class DroneSquadronOut(BaseModel):
    id: int
    target_base_id: int
    planet_key: str
    force: dict[str, int]              # drones vivos
    status: str
    drain_per_tick: float = 0.0        # Σ energy_per_tick de los drones vivos
    intel_quality: float = 0.0         # mejor intel viva (0 si no hay espías)
    eta_energy_ticks: float | None = None   # ticks hasta morir por energía (None = se sostiene)
    eta_turrets_ticks: float | None = None  # ticks hasta caer todos por torretas (None = sin AA)
    ticks_done: int = 0


class DroneSimRequest(BaseModel):
    force: dict[str, int]
    antiair: float = 0.0
    energy: float = 0.0
    regen_per_tick: float = 0.0
    max_ticks: int | None = None


class DroneSimOut(BaseModel):
    survive_ticks: int                 # cuántos ticks vive el escuadrón (cota efectiva)
    eta_energy_ticks: float | None = None
    eta_turrets_ticks: float | None = None
    drain_per_tick: float = 0.0
    intel_quality: float = 0.0
    attack_per_tick: float = 0.0
    losses: dict[str, int] = {}        # drones derribados en `survive_ticks`
    survivors: dict[str, int] = {}


class CombatPlanRequest(BaseModel):
    target_base_id: int
    margin: float = 2.0


class CombatPlanOption(BaseModel):
    unit: str
    qty: int
    attack_score: float
    est_attacker_loss_pct: int
    est_defender_loss_pct: int
    wins: bool


class CombatPlanOut(BaseModel):
    target: str | None
    target_base_id: int
    depth: float
    confidence: float
    as_of: datetime
    shared: bool = False
    estimated_defense: float
    atk_mult: float
    margin: float
    attack_power_needed: float
    options: list[CombatPlanOption]


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
    base_type: str = "surface"   # surface | orbital (SDD 37)
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
    posture: str | None = None   # SDD 29 v2: perfil/postura vigente de la NPC (qué está jugando)
    recent_actions: list[str] = []   # SDD 29: últimas jugadas de la NPC (qué hizo / cómo reaccionó)


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
    stocks_by_planet: dict[str, dict[str, float]] = {}   # SDD 42: stock por planeta
    units: dict[str, int] = {}
    # SDD 62: guarnición — unidades por base ({base_id: {unit: qty}}). Vacío en modo global (OFF)
    # hasta entrenar con garrison ON. El front agrupa por planeta sumando las bases.
    units_by_base: dict[str, dict[str, int]] = {}
    bases: list[BaseOut]
    training: list[TrainingOrderOut] = []
    expeditions: list[ExpeditionOrderOut] = []
    boons: list[ActiveBoonOut] = []
    missions_outgoing: list[AttackMissionOut] = []
    missions_incoming: list[IncomingAttackOut] = []
    # SDD 55 §3.3: ataques recibidos en las últimas 24 h + tope diario (anti-farmeo). El front
    # muestra "ataques recibidos hoy X/Y". 0 en max = sin tope.
    attacks_received_today: int = 0
    max_incoming_attacks_per_day: int = 0
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
    is_admin: bool = False                            # SDD 14: muestra el panel de admin
    account_status: str = "active"                    # SDD 14: active | pending | suspended
    transports: list[TransportMissionOut] = []        # SDD 42: envíos de minerales en curso
    spy_missions: list[SpyMissionOut] = []            # SDD 35: espías en vuelo/volviendo
    # SDD 47: estado de minería. mining = {staffing, available_workers, required_workers};
    # storage = {planeta: {mineral: {cap, stock, free, overflowing}}}. Vacío si los flags están off.
    mining: dict = {}
    # SDD 62: con guarnición ON, capacidad por planeta ({planet: {...}}). Vacío en modo global.
    mining_by_planet: dict = {}
    housing_by_planet: dict = {}
    troop_moves: list[TroopMoveOut] = []   # SDD 62: traslados de tropas en curso
    storage: dict = {}
    # SDD 46: alojamiento. housing = {dominio: {capacity, occupancy, free}}.
    housing: dict = {}
    # SDD 49: salvas de misiles en vuelo (propias). SDD 50: escuadrones de drones orbitando + intel
    # en vivo por base objetivo. Vacíos si los flags strike_enabled/drones_enabled están off.
    strikes: list[StrikeMissionOut] = []
    strikes_incoming: list[IncomingStrikeOut] = []   # SDD 67: salvas entrantes (nuclear negociable)
    drones: list[DroneSquadronOut] = []
    intel_live: dict = {}
    # SDD 61: satélites propios en órbita + mapas de enemigos ({target_id: {pct, bases}}).
    satellites: list[dict] = []
    enemy_maps: dict = {}
    # SDD 64: búnkeres subterráneos (medidores comida/agua/gente + mapa de salas).
    bunkers: list[dict] = []


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
class AdminPlayerEdit(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=50)
    email: str | None = Field(default=None, max_length=254)
    status: str | None = None


class AdvisorAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Selector de modelo (SDD 9): gpu (local, default) | cloud (pago barato, con budget) | byok.
    model_mode: Literal["gpu", "cloud", "byok"] = "gpu"
    byok_key: str | None = Field(default=None, max_length=200)   # key del jugador (no se persiste)
    byok_model: str | None = Field(default=None, max_length=120)   # ej "google/gemma-3-27b-it:free"
    byok_base_url: str | None = Field(default=None, max_length=300)


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
    # SDD 2: objetivos que el jugador puede CREAR GRATIS con el hack (aun teniendo materiales).
    # El front les pone un botón "🔓 crear gratis" distinto del "Construir" (que sí cobra).
    hack_targets: list[str] = []


class AdvisorHackRequest(BaseModel):
    target: str = Field(min_length=1, max_length=50)
    # SDD 2: mina/silo eligen qué mineral extraen/almacenan. Si no se pasa, el hack usa el mineral
    # estructural de la raza (siempre producible) como default → el hack también crea minas/silos.
    target_mineral: str | None = None


class AdvisorHackResult(BaseModel):
    granted: dict[str, float] = {}
    message: str
    hacks_left: int


class AdvisorMessageOut(BaseModel):
    id: int
    role: str
    body: str
    created_at: datetime
