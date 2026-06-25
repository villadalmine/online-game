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

    # Colonización (SDD 37): fundar bases en otros planetas.
    max_colonies: int = 3                 # máximo de colonias (además del mundo natal)
    colonize_energy_cost: float = 60.0    # energía por colonización (escala con nº de colonias)
    app_version: str = "dev"              # SDD 41: versión del juego (se setea por env APP_VERSION)
    meta_compute_interval_seconds: int = 600   # cada cuánto recalcula el meta (en el tick)
    assist_energy_per_day: int = 3        # SDD 40: veces/día que podés pedir energía de nivelado
    assist_energy_normal: float = 100.0   # +energía para jugadores que no son del fondo
    orbital_yield: float = 0.4            # rinde de una base orbital (robots, sin habitabilidad)
    orbital_cost_mult: float = 1.8        # la colonización orbital cuesta más energía

    # Eventos dinámicos "happy hour" (SDD 36): el tick puede arrancar uno en horas aleatorias.
    event_chance_per_tick: float = 0.25   # prob. por tick (si no hay activo y pasó el cooldown)
    event_cooldown_seconds: int = 1800    # mínimo entre eventos (30 min)

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

    # Catch-up del recién llegado (SDD 25): nivela al nuevo al percentil P40 de sus pares (sin
    # ventaja), con energía full + defensa. Solo si hay ≥ min_peers en su galaxia.
    catchup_enabled: bool = True
    catchup_percentile: float = 0.4
    catchup_min_peers: int = 3

    # Espionaje / inteligencia (SDD 35).
    spy_energy_cost: float = 5.0
    intel_confidence_half_life_seconds: int = 28800   # 8h: la intel pierde confianza con el tiempo

    # Inteligencia estratégica de NPCs (SDD 29): capa estratégica periódica que lee el scoreboard
    # y fija una postura. Opt-in; cae a la postura previa si el LLM falla (SDD 9).
    npc_strategy_enabled: bool = True
    npc_strategy_interval_seconds: int = 1800   # recalcular la estrategia cada ~30 min/NPC
    npc_strategy_max_tokens: int = 250

    # Multiplicadores físicos del planeta (SDD 13 §4). Opt-in: off ⇒ comportamiento actual. Anclados
    # a la Tierra=1.0; gravity_g→tiempo de construcción, insolation→regen de energía. Acotados.
    physics_enabled: bool = False
    physics_gravity_sensitivity: float = 0.5      # pendiente de gravity_g sobre el tiempo de build
    physics_insolation_sensitivity: float = 0.5   # pendiente de insolation sobre la regen
    physics_min_mult: float = 0.5                 # techo inferior de un multiplicador físico
    physics_max_mult: float = 2.0                 # techo superior (evita extremos como Mercurio)
    # mean_temp_c → refrigeración: temperaturas lejos del confort (frío o calor) drenan energía.
    physics_comfort_temp_c: float = 15.0          # temperatura "neutral" (≈ Tierra)
    physics_temp_sensitivity: float = 0.5         # cuánto penaliza el desvío térmico
    physics_temp_scale_c: float = 200.0           # escala del desvío térmico (°C por unidad)

    # Passwordless login por email + código OTP (SDD 6). El login usuario+contraseña sigue
    # existiendo (dev/CLI/tests). En prod este es el camino para el público.
    otp_secret: str = "change-me-otp-secret"   # HMAC del código; fuerte en prod (Secret)
    otp_ttl_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_length: int = 6
    # Defensa anti-abuso del endpoint OTP (SDD 6/14): tope de request-code por IP por minuto.
    # El envío real ya está acotado por allowlist + cooldown; esto frena el martilleo del endpoint.
    otp_rate_limit_per_min: int = 5
    # Allowlist de altas (SDD 14, modo simple): lista de emails autorizados a registrarse,
    # separados por coma. Vacío = registro abierto (comportamiento actual). Si está seteada, solo
    # esos emails (o jugadores ya existentes) reciben código en /auth/request-code. Cambiarla =
    # redeploy/restart. El gate es uniforme (no revela la lista → anti-enumeración).
    allowed_emails: str = ""

    # Admin (SDD 14 v2): email del admin. Si está seteado, /admin/* exige ser admin (ese email
    # o is_admin=True). Vacío = sin gate (dev/test, comportamiento actual).
    admin_email: str = ""

    # Observabilidad (SDD 19): si está seteado, /metrics exige Bearer = este token (Prometheus lo
    # manda por bearerTokenSecret) → no queda público por el gateway. Vacío = abierto (dev).
    metrics_token: str = ""

    # Landing pública (SDD 24): URL base absoluta para og:url/og:image (preview en redes).
    # Ej: https://tu-dominio. Vacío = og relativas (preview pobre, pero la página anda).
    public_url: str = ""

    # Presencia + métricas por entidad (SDD 21).
    presence_window_seconds: int = 90       # "online" = visto en esta ventana
    metrics_per_player: bool = False        # opt-in: gauges por jugador (cardinalidad alta)
    metrics_per_player_max: int = 200       # tope de series por jugador

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
    def allowed_email_set(self) -> set[str]:
        """Emails autorizados (lower, sin espacios). Vacío ⇒ registro abierto."""
        return {e.strip().lower() for e in self.allowed_emails.split(",") if e.strip()}

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

    def weak_secrets(self) -> list[str]:
        """Nombres de secretos que siguen en su default o son demasiado cortos (< 16 bytes).
        En production el arranque falla si esta lista no está vacía (deuda técnica: secretos
        fuertes en prod). Solo se chequea OTP si el login passwordless está activo (allowlist o
        mailer real); en dev/CLI con login usuario+clave no estorba."""
        weak: list[str] = []
        defaults = {"change-me", "change-me-in-prod", "change-me-otp-secret", ""}
        if self.jwt_secret in defaults or len(self.jwt_secret) < 16:
            weak.append("JWT_SECRET")
        otp_in_use = bool(self.allowed_email_set) or self.mail_backend != "console"
        if otp_in_use and (self.otp_secret in defaults or len(self.otp_secret) < 16):
            weak.append("OTP_SECRET")
        return weak

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() in ("production", "prod")

    @property
    def safe_database_url(self) -> str:
        """DB URL with any password redacted (safe to log/show)."""
        import re

        return re.sub(r"://([^:/@]+):[^@]+@", r"://\1:***@", self.database_url)


@lru_cache
def get_settings() -> Settings:
    return Settings()
