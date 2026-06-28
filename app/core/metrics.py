"""Métricas Prometheus sin dependencias (SDD 19).

Registro en memoria del proceso (Counter/Gauge/Histogram) + `render()` en el formato de
exposición de Prometheus. Multi-réplica: cada pod expone lo suyo y Prometheus suma (usar rate()).
Reglas: labels ACOTADOS (nunca ids/emails de jugador → cardinalidad + privacidad).
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_metrics: list[_Metric] = []


def _fmt_labels(names: tuple[str, ...], values: tuple[str, ...]) -> str:
    if not names:
        return ""
    inner = ",".join(f'{n}="{_esc(v)}"' for n, v in zip(names, values, strict=False))
    return "{" + inner + "}"


def _esc(v: str) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


class _Metric:
    def __init__(self, name: str, help_: str, labelnames: tuple[str, ...] = ()):
        self.name = name
        self.help = help_
        self.labelnames = labelnames
        _metrics.append(self)


class Counter(_Metric):
    kind = "counter"

    def __init__(self, name, help_, labelnames=()):
        super().__init__(name, help_, tuple(labelnames))
        self._vals: dict[tuple[str, ...], float] = {}

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = tuple(str(labels.get(n, "")) for n in self.labelnames)
        with _lock:
            self._vals[key] = self._vals.get(key, 0.0) + amount

    def _lines(self) -> list[str]:
        out = []
        for key, v in list(self._vals.items()):
            out.append(f"{self.name}{_fmt_labels(self.labelnames, key)} {v}")
        if not self._vals:
            out.append(f"{self.name} 0")
        return out


class Gauge(_Metric):
    kind = "gauge"

    def __init__(self, name, help_, labelnames=()):
        super().__init__(name, help_, tuple(labelnames))
        self._vals: dict[tuple[str, ...], float] = {}

    def set(self, value: float, **labels) -> None:
        key = tuple(str(labels.get(n, "")) for n in self.labelnames)
        with _lock:
            self._vals[key] = float(value)

    def inc(self, amount: float = 1.0, **labels) -> None:
        key = tuple(str(labels.get(n, "")) for n in self.labelnames)
        with _lock:
            self._vals[key] = self._vals.get(key, 0.0) + amount

    def dec(self, amount: float = 1.0, **labels) -> None:
        self.inc(-amount, **labels)

    def clear(self) -> None:
        """Olvida todas las series con label (para gauges recalculados en cada scrape)."""
        with _lock:
            self._vals.clear()

    def _lines(self) -> list[str]:
        out = []
        for key, v in list(self._vals.items()):
            out.append(f"{self.name}{_fmt_labels(self.labelnames, key)} {v}")
        if not self._vals:
            out.append(f"{self.name} 0")
        return out


_DEFAULT_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10)


class Histogram(_Metric):
    kind = "histogram"

    def __init__(self, name, help_, labelnames=(), buckets=_DEFAULT_BUCKETS):
        super().__init__(name, help_, tuple(labelnames))
        self.buckets = tuple(buckets)
        self._counts: dict[tuple[str, ...], list[int]] = {}
        self._sum: dict[tuple[str, ...], float] = {}
        self._n: dict[tuple[str, ...], int] = {}

    def observe(self, value: float, **labels) -> None:
        key = tuple(str(labels.get(n, "")) for n in self.labelnames)
        with _lock:
            counts = self._counts.setdefault(key, [0] * len(self.buckets))
            for i, b in enumerate(self.buckets):
                if value <= b:
                    counts[i] += 1
            self._sum[key] = self._sum.get(key, 0.0) + value
            self._n[key] = self._n.get(key, 0) + 1

    def _lines(self) -> list[str]:
        out = []
        for key in list(self._n.keys()):
            base = self.labelnames
            counts = self._counts[key]
            cumulative = 0
            for i, b in enumerate(self.buckets):
                cumulative = counts[i]
                lab = _fmt_labels(base + ("le",), key + (str(b),))
                out.append(f"{self.name}_bucket{lab} {cumulative}")
            lab_inf = _fmt_labels(base + ("le",), key + ("+Inf",))
            out.append(f"{self.name}_bucket{lab_inf} {self._n[key]}")
            out.append(f"{self.name}_sum{_fmt_labels(base, key)} {self._sum[key]}")
            out.append(f"{self.name}_count{_fmt_labels(base, key)} {self._n[key]}")
        return out


def render() -> str:
    """Serializa todo el registro en formato de exposición Prometheus (text/plain)."""
    lines: list[str] = []
    for m in _metrics:
        lines.append(f"# HELP {m.name} {m.help}")
        lines.append(f"# TYPE {m.name} {m.kind}")
        lines.extend(m._lines())
    return "\n".join(lines) + "\n"


# --- Métricas del juego (SDD 19) -------------------------------------------------------------
HTTP_REQUESTS = Counter(
    "http_requests_total", "Requests HTTP por método/ruta/status", ("method", "path", "status")
)
HTTP_DURATION = Histogram(
    "http_request_duration_seconds", "Latencia de requests HTTP", ("method", "path")
)
IN_FLIGHT = Gauge("http_requests_in_flight", "Requests HTTP en curso")

SSE_CONNECTIONS = Gauge("game_sse_connections", "Conexiones SSE abiertas (conectados ahora)")
PLAYERS_TOTAL = Gauge("game_players_total", "Jugadores humanos totales")
ONLINE_PLAYERS = Gauge("game_online_players", "Jugadores online (heartbeat /players/me)")  # SDD 21
# Opt-in (alta cardinalidad): 1 por jugador online, filtrable por player/galaxy en Grafana.
PLAYER_ONLINE = Gauge("game_player_online", "Jugador online (1)", ("player", "galaxy"))
SIGNUPS = Counter("game_signups_total", "Altas de jugadores", ("method",))  # method=password|otp
LOGINS = Counter("game_logins_total", "Logins exitosos", ("method",))

# Eventos de negocio (SDD 19): un solo Counter con label `kind` (set fijo y acotado de stats.bump):
# buildings_built, units_trained, research_completed, expeditions_completed, attacks_launched,
# battles_won/lost, resources_mined/looted/lost. Cardinalidad baja (nunca ids de jugador).
GAME_EVENTS = Counter("game_events_total", "Eventos del juego por tipo", ("kind",))

# Journal de acciones (SDD 38): un counter por TIPO de evento del log append-only. Como toda
# acción que cambia estado llama journal.record(), Grafana ve TODO (incl. espionaje y calculadora)
# sin instrumentar cada servicio a mano. Cardinalidad baja (set acotado de tipos, sin ids).
JOURNAL_EVENTS = Counter("game_journal_events_total", "Acciones registradas por tipo", ("kind",))

# Tick del mundo
TICK_DURATION = Histogram("game_tick_duration_seconds", "Duración de run_tick")
TICK_LAST_RUN = Gauge("game_tick_last_run_timestamp", "Unix ts del último tick OK")

# LLM (IA): no escala como la API (SDD 9). status=ok|error
LLM_REQUESTS = Counter("game_llm_requests_total", "Llamadas al LLM", ("status",))
LLM_LATENCY = Histogram("game_llm_latency_seconds", "Latencia del LLM")
# SDD 28 §3.5: correlación propia del juego — llamadas LLM por TIPO (advisor|npc|other), baja
# cardinalidad (sin player). La fuente de verdad de tokens/costo/backend sigue siendo LiteLLM.
LLM_CALLS = Counter("game_llm_calls_total", "Llamadas al LLM por tipo", ("kind", "status"))

# NPC (SDD): entender CÓMO juega la IA y si "mejora". `action` = qué hizo (build/train/attack/...);
# `brain` = rules|llm. `outcome` = llm (el LLM decidió) | fallback (falló y cayó a reglas) →
# más 'llm' y menos 'fallback' = la IA está razonando, no adivinando.
NPC_ACTIONS = Counter("game_npc_actions_total", "Acciones de NPC por tipo", ("action", "brain"))
NPC_DECISIONS = Counter("game_npc_decisions_total",
                        "Decisiones de NPC: el LLM decidió vs cayó a reglas, por backend gpu/cloud",
                        ("outcome", "backend"))
NPC_FALLBACK_REASON = Counter("game_npc_fallback_reason_total",
                              "Por qué la jugada del LLM no se aplicó (energy/infeasible/parse)",
                              ("reason",))
# SDD 29 v2: PERFIL/postura vigente de cada NPC → gauge por postura (cuántas NPC juegan así AHORA).
# Recalculado en cada tick (clear + recount) → en Grafana ves cómo la IA cambia de estrategia.
NPC_POSTURE = Gauge("game_npc_posture", "NPCs por perfil/postura vigente", ("posture",))
# A quién ataca la NPC: human|npc. Responde "¿también se pelean entre NPCs?" en un gráfico.
NPC_ATTACK_TARGETS = Counter("game_npc_attack_targets_total",
                             "Ataques lanzados por NPC, por tipo de objetivo", ("target",))
