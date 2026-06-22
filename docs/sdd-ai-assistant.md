# SDD 2 — Asistente AI personal (consejero + "hack" de emergencia)

> **Estado:** propuesto · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Depende de:** [SDD 1 — Grafo de dependencias](sdd-dependency-graph.md), `app/services/npc.py`
> (infra LLM), `app/services/economy.py`, `app/core/config.py` (`LLM_*`)

## 1. Objetivo

Dar a **cada jugador humano** un **asistente AI personal** que:

1. **Entiende la dinámica del juego** apoyándose en el **grafo de dependencias** del SDD 1 como
   *skill*/grounding (no "alucina" reglas: razona sobre el grafo real).
2. **Sugiere qué hacer**: cuando te quedás trabado porque te falta un material, te dice *qué te
   falta, cuánto y cómo conseguirlo*, y propone **acciones ejecutables de un clic** (construir
   mina, investigar, expedición…).
3. **Hack de emergencia:** si te quedaste duro porque *la cagaste en el chat / mal gastaste*,
   le pedís al asistente y **"hackea el servidor" y te consigue lo que te falta** — pero
   **máximo 3 veces por día**.

Usa **el mismo LLM que las NPC** (proveedor-agnóstico OpenAI-compatible vía `LLM_*`, con
**fallback** determinista si no hay LLM o falla). API-first: web/CLI/Telegram consumen lo mismo.

## 2. Arquitectura (encaja con lo existente)

```
Cliente ──HTTP──> /api/v1/players/me/advisor/*
                      │
        app/services/advisor.py
          ├─ snapshot(player)                 (SDD1)
          ├─ analyze(target) por objetivo     (SDD1)  ← grounding determinista
          ├─ llm_chat(system, history, user)  (app/services/llm.py, compartido con NPC)
          └─ grant_hack(target)               (economía + presupuesto diario)
```

### 2.1 Refactor compartido: `app/services/llm.py` (extraer, no romper)

Hoy la llamada HTTP cruda al LLM vive en `npc._llm_decide`. Extraemos el transporte a un módulo
chico para reusarlo sin duplicar:

```python
async def llm_chat(messages: list[dict], *, max_tokens=400, json_mode=False) -> str:
    """POST a {LLM_BASE_URL}/chat/completions (OpenRouter/LiteLLM/Ollama/vLLM).
    Devuelve el content. Lanza si no hay key/url o si la red falla."""
```

`npc._llm_decide` pasa a usar `llm_chat(..., json_mode=settings.llm_json_mode)` (mismo
comportamiento; tests del NPC siguen verdes). El asistente lo usa con `json_mode=False` para la
redacción y con un parse tolerante para las `suggestions`.

### 2.2 Persistencia (continuidad de la charla)

Modelo nuevo `AdvisorMessage` (espejo de `AllianceMessage`, ya probado):

```python
class AdvisorMessage(Base):
    id; player_id (FK, index); role: "user"|"assistant"; body: str(2000); created_at
```

Las últimas N (p.ej. 10) se envían como historial al LLM → continuidad ("como te dije antes…").

### 2.3 Presupuesto del hack (lazy por timestamp, sin depender de Redis)

Siguiendo el principio del proyecto (estado lazy, Redis degradable, todo full-local SQLite),
el contador vive en `Player`:

```python
assistant_hacks_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
assistant_hacks_reset_at: Mapped[datetime|None]  # inicio del día UTC del conteo actual
```

`_hack_budget(player, now)`: si `reset_at` es de un día anterior → `used=0`, `reset_at=hoy`
(reset perezoso al usarse, sin cron). `HACKS_PER_DAY = 3` (config `assistant_hacks_per_day`,
data/env-driven). Migración Alembic aditiva (con `server_default`, ojo SQLite — ver CLAUDE.md).

## 3. API

Todas bajo `get_current_player`, prefijo `/api/v1/players/me/advisor`.

### `POST /ask`
```jsonc
// req
{ "message": "no puedo construir una fábrica, ¿qué hago?" }
// res
{
  "reply": "Te faltan 60 de hierro para la fábrica. Tenés abundancia de hierro en Marte:
            construí una mina de hierro y en ~1h lo tenés. Si querés ya, te queda 1 hack hoy.",
  "blockers": [ /* BlockerReport del SDD1 para el/los objetivos detectados */ ],
  "suggestions": [ {"action":"build","building":"mine","mineral":"iron"} ],
  "hack_available": true, "hacks_left": 1
}
```
- Flujo: `advance` → `snapshot` → objetivos relevantes vía **RAG `retrieve`** (lo que el
  jugador menciona) + los no construidos → `analyze` cada uno (SDD1) → armar **contexto
  compacto** (docs recuperados + estado + blockers + historial) → `llm_chat` para la **prosa**
  (`reply`). **Las `suggestions` se generan deterministas del análisis** (no las inventa la LLM):
  así son SIEMPRE acciones válidas (build/train/research) — la LLM solo redacta. Esto evita que
  una alucinación produzca una acción inválida (decisión de implementación, jun-2026).
- **Fallback sin LLM:** si `llm_chat` lanza o no hay key, se responde con un `reply` armado de
  los `blockers` deterministas ("Te falta X: tenés A/B; conseguilo con una mina de Y") y
  `suggestions` derivadas (la mina del mineral faltante, la expedición, etc.). El asistente
  **siempre** responde algo útil.
- `suggestions` **no se ejecutan solas**: el cliente las muestra como botones; al click llaman a
  los endpoints reales (`/bases/{id}/build`, `/research`, …). El asistente *aconseja*, no actúa
  por vos (salvo el hack, que es explícito).

### `POST /hack`
```jsonc
// req
{ "target": "factory" }          // qué querés desbloquear
// res 200
{ "granted": {"iron": 60}, "message": "💀 Acceso root concedido… 60 de hierro materializados.",
  "hacks_left": 0 }
// res 429 cuando agotaste el día
{ "detail": "Sin hacks hoy (3/3). Vuelven mañana." }
```
- Calcula `analyze(target)` (SDD1). Otorga **solo el faltante mínimo** (`need-have`) de los
  `mineral` blockers del objetivo (y, si aplica, la **energía** faltante). **Nunca** unidades,
  ni ataques, ni build instantáneo → no rompe el balance de combate; es una muleta económica.
- **Acotado**: como mucho desbloquea *ese* objetivo una vez. Si el target ya es `buildable`,
  responde 400 ("no te falta nada para eso").
- Descuenta 1 del presupuesto diario (lazy reset). Idempotencia/atomicidad: se hace dentro de la
  transacción; si el grant falla, no se descuenta.
- **Trazabilidad/anti-abuso**: cada hack emite una `Notification` privada al jugador y se
  registra (log). Decisión de diseño: **no** se publica en el feed del mundo (para no exponer
  que alguien "hizo trampa"); queda como mecánica personal. Configurable a futuro.

### `GET /messages`
Historial de la charla (paginado simple, como el chat de alianza), para repintar la UI.

## 4. Grounding del LLM (el "skill")

`system` prompt del asistente (resumen):

> Sos el asistente personal de un jugador en un juego de estrategia espacial por turnos. Tu
> conocimiento del juego es el **grafo de dependencias** que te paso (minerales, minas,
> edificios, unidades, tecnologías y qué requiere cada cosa). **Recomendá solo cosas posibles
> según el grafo y el estado del jugador.** Si está trabado, explicá *qué le falta, cuánto y
> cómo conseguirlo* (mina local, expedición, saqueo, comercio). Sugerí 1-3 acciones concretas
> en JSON con el schema dado. No inventes reglas ni recursos que no estén en el grafo.

`user`/contexto incluye: grafo compacto `(race,planet)` (de SDD1), snapshot del jugador,
`BlockerReport` de los objetivos candidatos, e historial reciente. Respuesta esperada:
`reply` (texto) + bloque JSON `suggestions` (parse tolerante con `_extract_json`, ya existe).

La **verdad** sobre factibilidad y faltantes es **determinista (SDD1)** — el LLM redacta y
prioriza, pero `hack`/`suggestions` se validan contra `analyze`/los servicios reales antes de
ofrecerse, así una alucinación nunca produce una acción inválida.

## 5. Cliente web (consumidor delgado)

Card nueva "🧠 Asistente" (como el chat de alianza, sobrevive al refresh): input de texto, lista
de mensajes, botones para cada `suggestion`, y un botón **"Hackear (N/3 hoy)"** que llama a
`/hack` con confirmación. Sin lógica de juego en el front (API-first).

**Claridad (jun-2026):** la card separa explícitamente **Acciones** ("gastan tus recursos":
build/train/research) del **Hack** ("te *regala* el material/energía que falta; no construye,
después tocá una acción"), con nombres legibles. Si nombrás un mineral ("mina de silicio"), el
asistente ofrece una sugerencia que construye **esa** mina (lleva `target_mineral`), y al tocarla
el form de build se **sincroniza** — así no se construye otro mineral por una selección vieja del
dropdown.

## 6. Plan de tests (regla del proyecto)

**Servicio** (`tests/test_advisor.py`):
- `ask` con LLM mockeado (inyectar `llm_chat`): devuelve `reply` + `suggestions` parseadas y
  `blockers` coherentes con SDD1.
- `ask` **sin LLM** (key vacía / `llm_chat` lanza): fallback determinista responde con blockers
  y al menos una `suggestion` (la mina del mineral faltante).
- `hack` happy path: con faltante de `iron`, otorga exactamente `need-have`, el target queda
  `buildable`, `hacks_left` baja.
- `hack` sobre target ya construible → 400, no descuenta.
- presupuesto: 3 hacks ok, el **4º del día → 429**; tras cruzar `reset_at` (día siguiente) →
  vuelve a permitir (reset lazy).

**E2E HTTP** (`tests/test_api_e2e.py`):
- `POST /advisor/ask` (LLM dep override) feliz + error (sin onboarding → 4xx claro).
- `POST /advisor/hack` feliz + `429` al agotar el día.

**Browser** (`tests/browser/`): la card responde y el botón de hack refleja `N/3`.

**CHANGELOG + ROADMAP** al mergear.

## 7. Seguridad / balance / decisiones

- El "hack" es una **mecánica de juego deliberada** (muleta anti-frustración), no un bug:
  acotado a faltante mínimo, solo minerales/energía, **3/día**, trazado. No otorga ventaja
  militar directa.
- **Costo LLM:** `max_tokens` chico, historial corto; el asistente es opt-in por interacción
  (no corre en cada tick). Reusa la misma cuota/endpoint que las NPC.
- **Privacidad de prompts:** el estado del jugador va al LLM configurado por el operador (puede
  ser local: Ollama/LiteLLM) — coherente con que el LLM ya es del operador, no de Anthropic por
  defecto.
- **Degradación:** sin LLM y sin Redis, el asistente y el hack funcionan igual (DB + SDD1).
