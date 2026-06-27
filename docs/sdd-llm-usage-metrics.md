# SDD 28 — Métricas de uso de LLM por usuario (monetización) + GPU en tiempo real

> **Estado:** **completo** (app + infra vivos; solo virtual-key budgets queda "a futuro") · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 9 LLM en GPU](sdd-local-gpu-llm.md), [SDD 19 métricas](sdd-observability-metrics.md),
> [SDD 21 presencia/métricas por entidad](sdd-presence-dimensional-metrics.md), `app/services/llm.py`,
> LiteLLM (`ai/litellm-proxy`), HAMI, Prometheus/Grafana.

## 1. Objetivo
Dos cosas observables en **Grafana**:
1. **Uso de GPU en tiempo real** — cuánto consume cada modelo/instancia (VRAM, cómputo) en las 2 placas.
2. **Uso de LLM por usuario** — qué jugador usó el asistente, cuántas llamadas/tokens, y **por qué
   backend** (GPU local / OpenRouter free / pago) → base para **monetizar** el uso ("el usuario X
   gastó N tokens, M en GPU y K en OpenRouter").

Respuesta corta a *"¿se puede loguear esa métrica?"*: **sí**. LiteLLM ya emite métricas Prometheus
con label `end_user` (tracking activado en su config); **solo falta que el juego pase `user` en cada
request**. La GPU se ve con HAMI (+ DCGM opcional para % de cómputo).

## 2. Estado actual (verificado 2026-06-24)
- **LiteLLM** (`ai/litellm-proxy`): `success_callback: ["prometheus"]` y
  `disable_end_user_cost_tracking_prometheus_only: false` → **end_user tracking ON**. Hay
  `ServiceMonitor litellm-proxy-metrics` (Prometheus ya scrapea `/metrics`).
- **GPU/HAMI**: `hami-device-plugin` + `hami-scheduler` (con ServiceMonitor) exponen asignación/uso de
  vGPU (mem/cores) por pod. **No** hay DCGM-exporter (falta el % de cómputo crudo).
- **El juego NO pasa `user`** en `app/services/llm.py` (payload = model/messages/response_format) →
  hoy `end_user` queda vacío y no hay atribución por jugador. **Bloqueante #1.**

## 3. Diseño

### 3.1 Atribución por usuario (el cambio clave, app)
- `app/services/llm.py:call_llm(...)` agrega parámetro **`user: str | None`** y lo incluye en el
  payload OpenAI: `payload["user"] = user`. LiteLLM lo mapea a `end_user`.
- **Callers pasan identidad**:
  - **Asistente** (`advisor.py`): `user = player.username` (o `f"player:{player.id}"`).
  - **NPCs** (`npc.py`): `user = f"npc:{player.username}"` (separable de humanos en las queries).
- Resultado: LiteLLM etiqueta cada request con `end_user` + `model`/`model_group`.

### 3.2 Métricas que quedan disponibles (LiteLLM → Prometheus)
Con `end_user` poblado, las series clave (labels `end_user`, `model`, `model_group`):
- `litellm_total_tokens{end_user,model}` — tokens por usuario y modelo.
- `litellm_requests_metric{end_user,model}` — nº de llamadas.
- `litellm_spend_metric{end_user,model}` — **costo** (LiteLLM lo calcula por modelo; los free dan 0,
  los pagos > 0 → así separás GPU/free de pago).
- `litellm_deployment_successful_fallbacks_total{fallback_model}` — cuántas cayeron al fallback.
- **Backend usado** = label `model_group`/`model`: `local-gpu` (GPU), `*-free`/`gpt-oss-free`/… (OpenRouter
  free), `paid-final` (pago). → "usuario X: GPU=…, free=…, pago=…".

### 3.3 GPU en tiempo real (Grafana)
- **Ya disponible (HAMI)**: uso de vGPU por pod/placa (mem reservada/usada, cores) desde las métricas
  de `hami-scheduler`/`device-plugin`. Permite ver `ollama-a` (P4) vs `ollama-b` (M4000).
- **Opcional (recomendado) DCGM-exporter** para **% de utilización de cómputo** y VRAM real por GPU
  (`DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED`). Se instala como DaemonSet en el nodo GPU
  (`srv-t7910`) con su ServiceMonitor → dashboard "GPU en vivo".
- **Ollama**: expone poco; la utilización real viene de DCGM/HAMI, no de Ollama.

### 3.4 Dashboards Grafana (data-driven, en el repo)
- **"GPU en vivo"**: util % y VRAM por placa (DCGM) + vGPU asignada por pod (HAMI). Refresh 5-10s.
- **"LLM usage / billing"**: por `end_user` → tokens, requests, spend, split por `model_group`
  (GPU/free/pago) + tasa de fallbacks. Tabla top-N usuarios + serie temporal.
- Se versionan como ConfigMap con `grafana_dashboard: "1"` (igual que el dashboard del juego, SDD 19).

### 3.5 (Opcional) métrica propia del juego
SDD 19 ya expone `/metrics`. Se puede sumar `game_llm_calls_total{player,kind}` (kind=advisor|npc)
para correlacionar, pero **la fuente de verdad de tokens/costo/backend es LiteLLM** (sabe el ruteo y
el costo). No duplicar el cálculo de costo en la app.

## 4. Monetización (cómo se usa)
- **Reporte por usuario**: `sum by (end_user, model_group) (litellm_total_tokens)` y `litellm_spend_metric`
  → cuánto usó cada uno y en qué backend. Exportable a facturación.
- **Política**: free hasta X tokens/día en GPU/free; el excedente o el uso de modelos **pago**
  (`paid-final`) se cobra. El rate-limit del asistente (SDD 9, `advisor_rate_limit_per_min`) ya acota
  abuso; el cap por usuario puede vivir en LiteLLM (virtual keys con budget por `end_user`).
- **LiteLLM virtual keys**: a futuro, una key por jugador/tenant con `max_budget` → LiteLLM corta solo
  y la métrica de spend es por key. (Hoy alcanza con `end_user` para medir.)

## 5. Validación / tests
- **App**: `call_llm` incluye `user` en el payload (unit test del payload); advisor/npc lo pasan (e2e
  que el request saliente lo lleva — mock del transporte).
- **Métrica**: tras una llamada del asistente, `litellm_total_tokens{end_user="player:…"}` incrementa
  (verificable contra `/metrics` de litellm en un test de integración manual).
- **Dashboards**: cargan en Grafana (JSON válido); paneles devuelven datos con tráfico real.

## 5.ter DCGM-exporter (uso físico de GPU) — plan + estado (2026-06-24)
**Coexistencia con HAMI:** no chocan, leen capas distintas — HAMI = **asignación lógica** (lo
reservado por pod/placa); DCGM = **utilización física** (NVML/DCGM: util%, VRAM real, temp, watts).
**Regla:** DCGM-exporter **NO pide `nvidia.com/gpu`** → no consume vGPU ni pasa por HAMI (lee el
driver directo: DaemonSet `runtimeClassName: nvidia` + privileged). Solo telemetría read-only.

**Placas viejas:** P4 (6.1) y M4000 (5.2) soportan los campos `DCGM_FI_DEV_*` (util/VRAM/temp/power),
**no** los `DCGM_FI_PROF_*` (Volta+). → CSV custom recortado a `DEV_*` para no hacer ruido.

**Estado: HECHO** (en `infra-ai`, no en el chart del juego — es infra de cluster):
- Rol `install-dcgm-exporter` (idempotente, `kubernetes.core.k8s`) + DaemonSet/Service/ServiceMonitor
  (`release: kube-prometheus-stack`) + dashboard "GPU — DCGM (vivo)". Target **`make dcgm`**.
- Verificado en vivo: `DCGM_FI_DEV_GPU_UTIL/FB_USED/GPU_TEMP/POWER_USAGE` por placa
  (M4000 58 °C / Tesla P4 88 °C, VRAM ~4.7 GB c/u). Labels `gpu`, `modelName`.
- **Foto completa**: DCGM (uso real) + HAMI (`hami_gpu_*`, asignado) + LiteLLM (`end_user`, por usuario).

## 5.bis Estado de implementación (2026-06-24) — v1
- **App**: `app/services/llm.py:llm_chat(..., user=...)` manda el campo OpenAI `user`; el asistente
  pasa `player:<username>` (`advisor.py`) y los NPCs `npc:<username>` (`npc.py`, vía `state["__user"]`
  que NO se filtra al prompt). Tests: `test_npc.py` (payload lleva `user`; `__user` fuera del prompt).
- **LiteLLM (vía Ansible, infra-ai):** el campo `user` **NO** surfacea `end_user` con la config previa.
  Hizo falta `litellm_settings.enable_end_user_cost_tracking_prometheus_only: true` (el flag
  `disable_...` no alcanza). **Verificado 2026-06-24**: con el flag, `end_user="player:…"` aparece en
  `litellm_{input,output,total}_tokens_metric_total`, `litellm_spend_metric_total`,
  `litellm_requests_metric_total` y latencias → atribución/billing por usuario y backend real.
- **Dashboard**: `deploy/helm/dashboards/llm-usage.json` (ConfigMap `grafana_dashboard`): in-flight,
  requests/s por `requested_model` (backend), tokens/s por `model`, **tabla tokens por usuario (24h)**,
  **tabla spend por usuario × backend (24h)**, fallbacks/s → free, y **GPU por placa** (HAMI:
  `hami_gpu_memory_allocated_bytes`, `hami_gpu_core_allocated_ratio`). Métricas verificadas en vivo
  (`litellm_*_metric_total` con label `end_user`/`requested_model`/`model`; HAMI `hami_gpu_*`).
- **Métrica propia del juego (§3.5) — HECHA (2026-06-26):** `game_llm_calls_total{kind,status}`
  (kind=advisor|npc|other) en `llm_chat` → correlación in-app de uso por tipo, baja cardinalidad
  (sin player). La fuente de verdad de tokens/costo/backend sigue siendo LiteLLM (`end_user`). Test
  `test_llm_calls_metric_by_kind`.
- **DCGM-exporter — HECHO y VIVO** (verificado 2026-06-27): DaemonSet `dcgm-exporter` en ns `ai`
  (label `gpu=on`), rol `install-dcgm-exporter` + `make dcgm` en infra-ai. Ver §5.ter.
- **Dashboards Grafana — HECHOS y VIVOS** (verificado 2026-06-27): `grafana-dashboard-gpu-dcgm`
  ("GPU en vivo", ns ai), `grafana-dashboard-gpu-llm-billing` + `grafana-dashboard-gpu-tenants`
  ("LLM billing", ns monitoring), `litellm-ai-traffic-dashboard`, y los del juego
  (`galaxy-grafana-dashboard`: online-game + npc-ai + llm-usage).
- **Único pendiente (opcional, "a futuro"): LiteLLM virtual keys con budget por jugador** — corta/
  cobra automático por `end_user`. Hoy la **medición ya funciona** vía `end_user` (no bloquea nada);
  solo hace falta cuando se monetice de verdad (decidir política de free tier + cutoff). Requiere
  decisión de producto + cambio app (key por jugador) + LiteLLM (`/key/generate`, `max_budget`).

## 6. Riesgos / decisiones
- **Cardinalidad**: `end_user` por jugador es alta cardinalidad en Prometheus. Mitigar: solo humanos
  (no por-NPC individual; agrupar NPCs en `npc:*`), y/o usar el cost-tracking de LiteLLM (DB) para el
  detalle fino y Prometheus solo para agregados. Revisar retención.
- **Privacidad**: `end_user` debería ser el **id/nickname**, nunca el email (SDD 20).
- **DCGM en Maxwell/Pascal**: el P4 (6.1) y M4000 (5.2) son viejos; DCGM-exporter los soporta, pero
  validar que publique util%. Si no, quedarse con HAMI (mem/cores asignados).
- **Costo "real" de GPU**: LiteLLM marca spend=0 para modelos locales; para "costo" de GPU se puede
  asignar un precio nominal por token local (config) si se quiere cobrar también el cómputo propio.

## 7. Implementación (orden sugerido, cuando se decida)
1. App: `user` en `call_llm` + callers (advisor/npc). Test. (Desbloquea TODO lo demás.)
2. Dashboard "LLM usage/billing" (LiteLLM ya tiene los datos). 
3. DCGM-exporter + dashboard "GPU en vivo" (infra-ai, idempotente, igual que el tier ollama).
4. (Futuro) LiteLLM virtual keys con budget por jugador para cortar/cobrar automático → **§8**.

## 8. Diseño: virtual keys con budget por jugador (a futuro, no implementado)

> **Estado:** **diseño** (decisión 2026-06-27: documentar, no codear hasta monetizar). Hoy la medición
> por `end_user` ya da el dato; esto agrega el **corte/cobro automático**. Es el único pendiente de
> SDD 28. **No arrancar sin usuarios reales pagando** (sería optimización prematura).

### 8.1 Por qué virtual keys (y no seguir solo con `end_user`)
`end_user` **mide** (tokens/spend por jugador, ya vivo) pero **no corta**: un jugador puede pedirle al
asistente sin límite más allá del `advisor_rate_limit_per_min` (SDD 9). Una **virtual key de LiteLLM
por jugador** con `max_budget` hace que **LiteLLM mismo** rechace (HTTP 400 "budget exceeded") cuando el
jugador supera su presupuesto → corte sin lógica de cobro en la app, y el spend queda atribuido a la
key (= jugador). Es la pieza que convierte "medir" en "cobrar/limitar".

### 8.2 Mapeo key ↔ jugador
- **Una virtual key por jugador humano** (los NPC siguen con la master key + `user="npc:*"`; no se les
  cobra). Se crea **lazy** la primera vez que el jugador usa el asistente.
- Nuevo modelo/columna: `Player.llm_key_id` (el id de la key en LiteLLM) + el token cifrado, o solo el
  id si la app pide la key al vault de LiteLLM. **Nunca** loguear la key; tratarla como secreto (SDD 20).
- La app llama al asistente con **la key del jugador** (header `Authorization: Bearer <vk>`) en vez de
  la master key. Mantiene `user=player:<id>` igual (doble atribución: por key y por end_user).

### 8.3 API LiteLLM (gestión de keys)
- **Crear**: `POST /key/generate` `{ user_id, max_budget, budget_duration, models, rpm_limit }` →
  devuelve `{ key, key_name }`. `budget_duration: "1d"` (o "30d") = budget que **se resetea** solo.
- **Consultar**: `GET /key/info?key=` → `spend`, `max_budget`, `budget_reset_at` (para mostrar al
  jugador "te queda X de tu cuota de hoy").
- **Actualizar / borrar**: `POST /key/update`, `POST /key/delete` (al borrar cuenta, SDD 20).
- Requiere la **master key** de LiteLLM (ya existe, en `install-litellm-proxy/defaults/secrets.yml`);
  la app la usa solo para administrar keys, no para inferencia.

### 8.4 Política (parámetros, data-driven en config del juego)
- `llm_free_tokens_per_day` (p.ej. 50k) → `max_budget` traducido a costo equivalente, o usar
  `max_budget` directo en USD nominal. **GPU local y modelos `*-free` cuestan ~0** → el budget en
  USD casi no los toca; el budget muerde sobre todo en `paid-final`. Decisión: ¿el free tier limita
  **tokens totales** (incluido GPU) o solo **gasto en pago**? → arrancar limitando **gasto en pago**
  (lo que cuesta plata real) y dejar GPU/free generosos.
- `budget_duration: "1d"` (reset diario) para un free tier renovable.
- Al **superar**: LiteLLM devuelve error → la app lo traduce a un toast claro ("llegaste a tu cuota de
  IA de hoy; vuelve mañana o subí de plan") y **cae a la respuesta del brain de reglas** (el asistente
  ya tiene fallback determinista, SDD 1/9) → el juego no se rompe, solo pierde el "sabor" LLM.

### 8.5 Tiers / monetización (gancho a futuro)
- `free` (budget chico, modelos GPU/free), `premium` (budget mayor, habilita `paid-final`). El tier
  vive en `Player` y mapea a un `max_budget` distinto vía `POST /key/update`. El cobro real (pasarela)
  es otro SDD; acá solo el **enforcement** técnico.

### 8.6 Validación (cuando se implemente)
- Unit: la app crea la key lazy y persiste `llm_key_id`; usa la key del jugador en el request.
- e2e (mock LiteLLM): con budget=0 el asistente cae al fallback de reglas y muestra el toast de cuota;
  con budget disponible usa LLM. Borrar cuenta → `key/delete`.
- Métrica: `litellm_spend_metric{api_key=...}` por key coincide con el jugador.

### 8.7 Riesgos
- **No prematuro**: sin usuarios pagando, esto agrega complejidad (gestión de secretos por jugador,
  fallos de la API de keys) sin valor → por eso queda en diseño.
- **Secreto por jugador**: más superficie; cifrar en DB, rotar al sospechar fuga, nunca exponer al front.
- **Fallo de LiteLLM/key**: si la gestión de keys falla, **degradar a la master key + fallback de
  reglas**, nunca dejar al jugador sin asistente por un problema de billing.
