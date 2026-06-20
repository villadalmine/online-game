from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTENT_DIR = REPO_ROOT / "content"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Online Galaxy War"
    environment: str = "development"

    database_url: str = "sqlite+aiosqlite:///./game.db"
    redis_url: str = "redis://localhost:6379/0"
    redis_enabled: bool = False  # off by default so local/dev/tests need no Redis

    # Redis-backed features
    catalog_cache_ttl: int = 300  # seconds
    attack_rate_limit_per_min: int = 20

    jwt_secret: str = "change-me-in-prod"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080

    # Game balance (overridable via env)
    energy_regen_per_hour: float = 10.0
    energy_max: float = 240.0
    energy_start: float = 60.0

    # Combat balance
    attack_energy_cost: float = 25.0
    loot_fraction: float = 0.2  # share of each defender mineral looted on a win
    # Fleet travel time (seconds): one-way. Same planet is quick; cross-planet is slow.
    travel_seconds_same_planet: int = 60
    travel_seconds_cross_planet: int = 300

    # World auto-tick: background loop that advances the world (NPC turns, mission
    # arrivals, queues) every N seconds. 0 = off. Use >0 for single-instance/dev so the
    # browser feels alive; in multi-replica prod keep 0 and use the k8s CronJob instead.
    auto_tick_seconds: int = 0

    # NPC (AI-controlled races)
    npc_enabled: bool = True
    npc_brain: str = "rules"  # "rules" (default) | "llm" (OpenRouter, optional)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
