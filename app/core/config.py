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

    # Capacidad / escalado (SDD 7). El SSE pollea la DB por conexión: subir el intervalo
    # baja drásticamente la carga (0.5 rps/CCU a 2 s → 0.2 a 5 s). El pool de DB es por
    # réplica; pool_size × n_réplicas ≤ max_connections de Postgres (techo real → PgBouncer).
    stream_interval: float = 2.0          # default del SSE (s) si el cliente no pide otro
    db_pool_size: int = 5                 # conexiones persistentes por réplica (no-sqlite)
    db_max_overflow: int = 10             # conexiones extra bajo ráfaga
    db_pool_timeout: int = 30             # s a esperar una conexión del pool antes de fallar
    db_pool_recycle: int = 1800           # reciclar conexiones cada N s (evita stale en PgBouncer)

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
    npc_brain: str = "rules"  # "rules" (default) | "llm" (any OpenAI-compatible server)

    # Personal AI assistant (SDD 2): emergency "hack" budget per player per day.
    assistant_hacks_per_day: int = 3

    # Temporadas + protección de novatos (SDD 11).
    season_days: int = 28                 # duración de cada temporada
    season_hall_of_fame_top: int = 10     # cuántos entran al Hall of Fame al cerrar
    newbie_protection_hours: int = 48     # protección al crear el imperio

    # Galaxy instances / shards (SDD 8): máx humanos por instancia de galaxia.
    galaxy_capacity: int = 50

    # Passwordless login por email + código OTP (SDD 6). El login usuario+contraseña sigue
    # existiendo (dev/CLI/tests). En prod este es el camino para el público.
    otp_secret: str = "change-me-otp-secret"   # HMAC del código; fuerte en prod (Secret)
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_length: int = 6
    # Envío de email: console (default, loguea el código — dev/CI sin SMTP) | smtp | resend
    mail_backend: str = "console"
    mail_from: str = "Online Galaxy War <no-reply@localhost>"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    resend_api_key: str = ""

    # LLM provider — any OpenAI-compatible endpoint: OpenRouter, LiteLLM, Ollama, vLLM…
    # Set LLM_* to point anywhere; if unset, falls back to the OPENROUTER_* values below
    # (back-compat). For Ollama: LLM_BASE_URL=http://host:11434/v1, LLM_MODEL=llama3.1,
    # LLM_API_KEY=ollama (ignored). For LiteLLM: its proxy URL + master key.
    llm_api_key: str = ""
    llm_base_url: str = ""
    llm_model: str = ""
    llm_json_mode: bool = True  # ask for response_format=json_object (LiteLLM/Ollama/OpenAI)
    # LLM local en GPU (SDD 9): la IA es serial (una GPU = una cola), NO escala como la API.
    # El timeout corta la espera y dispara el fallback (NPC→reglas, asistente→determinista).
    # El rate-limit del asistente protege la GPU del pico de "todos preguntan a la vez".
    llm_timeout_seconds: float = 20.0
    advisor_rate_limit_per_min: int = 6   # consultas /advisor/ask por jugador por minuto

    # Legacy OpenRouter knobs (still honored as defaults for the LLM_* above).
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_model: str = "google/gemma-4-31b-it:free"

    @property
    def llm_key(self) -> str:
        return self.llm_api_key or self.openrouter_api_key

    @property
    def llm_url(self) -> str:
        return self.llm_base_url or self.openrouter_base_url

    @property
    def llm_model_name(self) -> str:
        return self.llm_model or self.openrouter_model

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def db_backend(self) -> str:
        if self.is_sqlite:
            return "sqlite"
        if "postgres" in self.database_url:
            return "postgres"
        return "other"

    @property
    def safe_database_url(self) -> str:
        """DB URL with any password redacted (safe to log/show)."""
        import re

        return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
