# LLM local en GPU (SDD 9) — ejemplos

Estos manifiestos corren **fuera** del chart del juego. El chart sólo apunta a un endpoint
OpenAI-compatible vía `llm.baseUrl`; el serving de la GPU (Ollama / LiteLLM) es infraestructura
aparte porque **la IA no escala como la API** (una GPU = una cola serial; ver
[SDD 7](../../docs/sdd-capacity-autoscaling.md) y [SDD 9](../../docs/sdd-local-gpu-llm.md)).

## Topología recomendada

```
juego (API/worker)  ──LLM_BASE_URL──▶  LiteLLM (proxy: cola + rate-limit + fallback)
                                              │
                                              ├─▶ Ollama en GPU (P4/Quadro)  [primario]
                                              └─▶ OpenRouter (hosted)        [fallback bajo saturación]
```

LiteLLM mantiene OpenAI-compatible, da **límite de concurrencia + cola** y **load-balance** si
algún día hay 2+ GPUs. Si querés algo mínimo, apuntá el juego directo a Ollama (`ollama.yaml`)
y omití LiteLLM.

## Pasos

1. **Nodo GPU**: instalá el NVIDIA device plugin (`nvidia.com/gpu` schedulable) y el runtime.
   Etiquetá el nodo: `kubectl label node <nodo> gpu=nvidia-p4`.
2. **Ollama**: `kubectl apply -f ollama.yaml` (reserva 1 GPU, PVC para los pesos, keep-alive
   largo para no recargar el modelo). Bajá el modelo: `kubectl exec deploy/ollama -- ollama pull qwen2.5:3b`.
3. **LiteLLM** (opcional pero recomendado): editá `litellm-config.yaml` (modelo + fallback) y
   `kubectl apply -f litellm.yaml`.
4. **Apuntá el juego** (values del chart):
   ```sh
   helm upgrade --install online-game deploy/helm \
     --set npc.brain=llm \
     --set llm.baseUrl=http://litellm.gpu-llm.svc:4000/v1 \
     --set llm.model=qwen2.5:3b \
     --set llm.apiKey=sk-anything \
     --set llm.jsonMode=true \
     --set llm.timeoutSeconds=30
   ```

## Elección de modelo (8 GB, Pascal/Maxwell)

- **P4** (Pascal) es la apuesta segura; Maxwell es más viejo/lento (sin tensor cores).
- 8 GB ⇒ cómodo para **3–4B** (snappy) y alcanza **7–8B en Q4** con contexto moderado.
- Default sugerido: **`qwen2.5:3b`** (buen apego a JSON y español, rápido) para NPCs **y**
  asistente con una sola carga (menos swaps de VRAM). Subí a `qwen2.5:7b-instruct` si la
  latencia del asistente lo permite.

## Concurrencia y fallback

- La GPU es **serial**: con varios usuarios **encola** (latencia), no falla. El asistente tiene
  `advisor_rate_limit_per_min` por jugador y, al pasarse el `llm.timeoutSeconds`, **cae al
  fallback determinista** (asistente) o a **reglas** (NPC) — nunca hay error al usuario.
- En LiteLLM configurá `num_retries`/`fallbacks` para derivar a un hosted (OpenRouter) cuando
  la GPU está saturada.

> Verificación (SDD 9 §7): benchmark de tok/s por modelo (NPC ~120 tok / asistente ~400 tok) y
> prueba de saturación (N asistentes simultáneos → confirmar encolado + disparo del fallback).
