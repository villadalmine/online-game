# SDD 9 — LLM local en GPU (Tesla P4 / Quadro Maxwell) para NPCs y asistente

> **Estado:** propuesto · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Relacionado:** [SDD 2 — Asistente](sdd-ai-assistant.md), `app/services/llm.py`,
> [SDD 7 — Capacidad](sdd-capacity-autoscaling.md). **La IA NO escala como la API.**

## 1. Objetivo

Servir la inteligencia de **NPCs** y del **asistente** desde **GPU local** (Tesla **P4** 8 GB
Pascal, o Quadro **Maxwell M-series** ~8 GB) con **Ollama o LiteLLM**, y entender qué pasa con
**varios usuarios concurrentes** sobre una sola GPU y **qué modelo local** rinde bien.

## 2. Punto de partida (ya está casi todo)

El juego ya es **agnóstico del proveedor**: `app/services/llm.py:llm_chat` habla
`/chat/completions` OpenAI-compatible contra `LLM_BASE_URL` (OpenRouter/LiteLLM/Ollama/vLLM), con
**timeout 20 s** y **fallback duro** (NPC→reglas, asistente→blockers deterministas). El Helm expone
`llm.baseUrl/model/apiKey/jsonMode` y **no levanta ningún LLM** (lo corrés vos). Prompts ya cortos:
NPC `max_tokens=120` con **JSON mode**, asistente `max_tokens=400` + **RAG `retrieve`** para no
inflar el contexto. ⇒ Este SDD es sobre **operar la GPU**, no reescribir la app.

## 3. La GPU: qué reserva y qué pasa con varios usuarios

- En k8s, un pod que pide `resources.limits: nvidia.com/gpu: 1` **reserva la GPU entera**; no se
  comparte entre pods salvo *time-slicing/MPS* (no recomendado en 8 GB). Tu intuición es correcta:
  **dentro de ese pod la GPU es dedicada**; si varios usuarios pegan, **no hay problema de
  corrección — se serializan** (cola), el costo es **latencia**, no errores.
- **Ollama** serializa por defecto; `OLLAMA_NUM_PARALLEL` permite algo de paralelismo pero comparte
  VRAM/cómputo → en 8 GB conviene **1–2**. Carga el modelo una vez (keep-alive) para no pagar el
  reload.
- Patrón recomendado: **LiteLLM como proxy** delante de Ollama (sigue siendo OpenAI-compatible) →
  da **límite de concurrencia + cola + rate-limit + fallback** (p.ej. caer a OpenRouter cuando la
  GPU está saturada) y **load-balance** si algún día hay 2+ GPUs/nodos. El juego apunta
  `LLM_BASE_URL` a LiteLLM y listo.

## 4. Qué modelo local rinde bien (8 GB, Pascal/Maxwell)

- **VRAM 8 GB** ⇒ cómodo para **3–4B** (rápidos) y alcanza para **7–8B en Q4** (~4.5–5 GB) con
  contexto moderado. Pascal (P4) tiene INT8 decente; **Maxwell (M-series) es más viejo y lento**
  (sin tensor cores; chequear que la build de CUDA/llama.cpp aún soporte compute 5.2). **El P4 es
  la mejor de las dos.**
- **Recomendación por tarea** (ambas con **JSON/multilingüe ES-EN**):
  - **NPCs** (decisión estructurada, corta, JSON): un **instruct chico con buen apego a JSON** —
    `qwen2.5:7b-instruct` (Q4) si la latencia lo permite, o `qwen2.5:3b` / `llama3.2:3b` para
    snappier. Ollama soporta `format: json` (mapea a `response_format`).
  - **Asistente** (prosa ES/EN sobre los docs del RAG): mismo modelo; **Qwen2.5** rinde bien en
    español. Si querés una sola carga, usá **un único modelo** para ambos (menos VRAM/swaps).
- **Expectativa de throughput** (orden de magnitud, **calibrar**): P4 con 7B Q4 ≈ *unidades–
  decenas* de tok/s. ⇒ NPC (~120 tok) ≈ pocos segundos; asistente (~400 tok) ≈ ~10–30 s. Maxwell:
  más lento. Para snappy en el asistente, preferí **3–4B**.

## 5. ¿Cuántos usuarios concurrentes aguanta la IA?

Clave: **la carga de IA NO es proporcional a los usuarios online**, sino a:
- **NPCs**: corren en el **tick** (cadencia controlada) y son **pocos por galaxia** (uno por raza →
  ver SDD 8). Costo acotado y diferible.
- **Asistente**: **opt-in por interacción** (no corre solo). El pico es "cuántos preguntan a la vez".

Con **una GPU serial**, el límite es `~ (tok/s) / (tokens_por_respuesta)` respuestas/seg. Ejemplo
ilustrativo: 15 tok/s ÷ 400 tok ≈ **1 respuesta cada ~27 s** → del orden de **~2 asistentes/min**
antes de encolar. Por eso:
- **Rate-limit por usuario** en el asistente (ya hay patrón en `core/redis.py`) + **límite de
  concurrencia/cola en LiteLLM**.
- **Fallback agresivo**: si la cola/`timeout` (20 s) se pasa → respuesta determinista (asistente) o
  reglas (NPC). Ya implementado; acá solo se **configura** (timeout, cola).
- **Separar rutas**: NPC→GPU local (barato, en background); asistente→GPU local **con fallback a un
  hosted** (OpenRouter) bajo saturación, vía LiteLLM. Mantener prompts cortos (RAG ya ayuda).

## 6. Despliegue (sin tocar la app; todo es infra + config)

- **Nodo GPU**: NVIDIA device plugin + runtime; tu Ollama/LiteLLM corre **fuera del chart** del
  juego (el chart solo apunta `llm.baseUrl`). Pod de Ollama con `nvidia.com/gpu: 1`, `nodeSelector`
  al nodo de la P4/Quadro, PVC para los pesos, `OLLAMA_KEEP_ALIVE` largo.
- **Config del juego**: `npc.brain=llm`, `llm.baseUrl=http://litellm…/v1` (o Ollama directo),
  `llm.model=qwen2.5:3b` (o el elegido), `llm.jsonMode=true`. Para Ollama, `llm.apiKey` cualquier
  cosa (lo ignora).
- **Una sola GPU** = una instancia de serving; escalar IA = **más GPUs/nodos + LiteLLM
  load-balance**, no HPA del pod de GPU (no se fracciona).

## 7. Verificación
- **Benchmark** de tok/s y latencia end-to-end por modelo candidato (NPC 120 tok / asistente
  400 tok) en P4 y en Maxwell → elegir modelo y `max_tokens`.
- **Prueba de saturación**: N asistentes simultáneos → confirmar que **encola** y que el
  **fallback** se dispara al timeout (no errores al usuario).
- **Calidad**: set chico de prompts NPC (¿el JSON parsea? ¿decisiones sensatas?) y asistente
  (¿consejo correcto en ES/EN, fiel al grafo?). La verdad de factibilidad ya es determinista
  (SDD 1), así que el LLM solo redacta/prioriza.

## 7.bis Estado de implementación (2026-06-23) — v1
- **App (testeable):** **timeout del LLM configurable** (`LLM_TIMEOUT_SECONDS`, antes 20s fijo en
  `app/services/llm.py`) → corta la espera de la GPU serial y dispara el fallback ya existente
  (NPC→reglas, asistente→determinista). **Rate-limit del asistente** por jugador en
  `/advisor/ask` (`advisor_rate_limit_per_min`, 429 al pasarse) usando el patrón de
  `core/redis.py`. Config en `app/core/config.py`.
- **Infra/ejemplos (fuera del chart):** `deploy/gpu-llm/` con `ollama.yaml` (1 GPU dedicada, PVC
  de pesos, keep-alive, `NUM_PARALLEL=1`), `litellm.yaml` (+ ConfigMap: proxy OpenAI-compatible
  con cola/retries/fallback) y `README.md` (topología, elección de modelo 3–4B/7B Q4 en P4 vs
  Maxwell, concurrencia serial). El chart sólo apunta `llm.baseUrl`/`llm.timeoutSeconds`.
- Tests: `tests/test_scaling.py` (defaults/overrides de `llm_timeout_seconds`/
  `advisor_rate_limit_per_min`) + e2e `test_advisor_rate_limited` (429).
- **Pendiente (follow-up):** **benchmark real** de tok/s y latencia por modelo candidato en
  P4/Maxwell (NPC 120 tok / asistente 400 tok) → elegir modelo y `max_tokens`; prueba de
  saturación (N asistentes → encolado + fallback); fallback a hosted vía LiteLLM bajo carga.

## 8. Riesgos / decisiones
- **Maxwell viejo**: puede quedar sin soporte en builds nuevas de CUDA/llama.cpp; el **P4** es la
  apuesta segura. Si ninguna alcanza la latencia deseada en 7B, **bajar a 3–4B**.
- **GPU = recurso serial**: nunca poner la IA en el camino crítico sin fallback (ya garantizado).
- **VRAM**: un solo modelo cargado para NPC+asistente evita swaps; vigilar contexto + `NUM_PARALLEL`.
- **Costo/latencia vs. calidad**: para NPCs alcanza un modelo chico; el asistente puede preferir
  uno mejor con fallback hosted bajo carga.
