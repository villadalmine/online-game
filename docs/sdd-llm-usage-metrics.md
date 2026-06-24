# SDD 28 — Métricas de uso de LLM por usuario (monetización) + GPU en tiempo real

> **Estado:** propuesto · **Fecha:** 2026-06-24
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
4. (Futuro) LiteLLM virtual keys con budget por jugador para cortar/cobrar automático.
