# SDD 73 — Asistente pre-login (widget) + evaluación de Open WebUI

> **Estado:** **EVALUACIÓN / DISEÑO** 2026-07-03 · **Pedido:** usuario, 2026-07-02.
> Evaluar un **bot de ayuda en el panel principal ANTES de loguearse**: un asistente interactivo que
> use el **grafo/info del juego** para orientar al visitante (qué es, cómo se juega), **no** para
> "thinking". Evaluar **Open WebUI** como base, y si conviene dejarlo **dentro** de este proyecto o
> como un **servicio genérico, parametrizable y plug-and-play** que este juego (y otros) consuman.
> Backends por **LiteLLM** → **Ollama** o **modelo RKNN de NPU**.
> **Relacionado:** [SDD 9 asistente](sdd-personal-assistant.md) (advisor post-login, grafo+RAG),
> [SDD 28 LiteLLM/GPU](sdd-llm-usage-metrics.md), [SDD 65 rutas/observabilidad LLM](sdd-npc-autonomous-intelligence.md),
> [[unified-graph-model-for-ai]], [[grafana-embed-admin-decision]] (lección: iframe cross-domain rompe
> login en Firefox). Endpoints públicos ya existentes: `/catalog`, `/catalog/graph`, `/catalog/tree`,
> `/catalog/graph/docs`, `/catalog/graph/search?q=&k=` (búsqueda semántica del grafo, **sin auth**).

## 1. Pedido (usuario, textual resumido)
- Bot de ayuda en el **panel principal antes de login**, para **cualquier juego o servicio**.
- Evaluar **Open WebUI** (openwebui.com / docs.openwebui.com / github) conectado usando **RKNN NPU** u
  **Ollama a través de LiteLLM**.
- Duda central: ¿mejor **dentro** de este proyecto, o **fuera**, como algo **genérico** que yo pueda
  integrar en mi web y **parametrizar todo** (qué modelo, para qué, qué contexto) → **plug-and-play**
  para otros proyectos? Asistente para **cosas de la web**, no para thinking; que use **todo el grafo/
  info de cada juego** y ayude de forma **interactiva**, para la persona **antes de loguearse**.
- Que se pueda **pasar a otro proyecto** y que este juego **lo consuma**.

## 2. Evaluación de Open WebUI (leída la doc, 2026-07-03)
Open WebUI es una **plataforma de chat LLM self-hosted completa** (Docker; backend Python + front
SvelteKit; SQLite/Postgres; RAG con ~9 vector DBs; búsqueda web; RBAC con **cuentas de usuario
obligatorias**; conecta a **Ollama y APIs OpenAI-compatibles** como LiteLLM; extensible con Filters/
Actions/Pipes/Tools + MCP/OpenAPI).
**Veredicto: NO encaja como widget de ayuda pre-login embebible.** Razones:
- **Requiere login/cuentas (RBAC)** → es lo contrario a "ayuda anónima antes de loguearse".
- **No es embebible como widget** (no hay iframe/script-widget); es una app standalone (`:8080`). Un
  iframe además choca con la lección [[grafana-embed-admin-decision]] (cross-domain rompe sesión).
- **Su RAG usa su propio vector store** → habría que **duplicar** el grafo del juego ahí y se
  **desincroniza** (rompe [[unified-graph-model-for-ai]]: el juego ya tiene RAG del grafo, `/catalog/
  graph/search`). Mantener dos fuentes de verdad es el anti-patrón que evitamos.
- Es **pesado** para "ayuda de la web, no thinking": traería vector DBs, auth, colas, para un chat
  chico anónimo.
**Dónde SÍ sirve Open WebUI:** como **playground/consola interna** para vos (power-user) contra el
mismo LiteLLM/GPU — opcional, standalone, **no** embebido en el landing. No es el asistente pre-login.

## 3. Recomendación: servicio GENÉRICO aparte (no dentro de este juego)
Coincide con tu intuición y con los principios del proyecto (API-first, clientes delgados, grafo
unificado). **Construir un microservicio propio y liviano: "prelogin-assistant-widget"**, en **otro
repo**, plug-and-play, y que **este juego lo consuma** apuntándolo a su grafo público. NO meter la
lógica en el core del juego.

### 3.1 Qué es el widget (genérico, parametrizable)
- **Front:** un `<script>` embebible (una burbuja de chat) — cero login, anónimo, rate-limit por IP.
  Se pega en el landing de **cualquier** sitio. Tematizable (colores, avatar, textos).
- **Backend:** FastAPI chico que por request (a) **recupera** el contexto relevante desde la **fuente
  de conocimiento configurada** del sitio (una URL que devuelve docs del grafo o un endpoint de
  búsqueda), y (b) llama a **LiteLLM**. Grounded, temp baja, respuestas cortas (patrón del advisor
  SDD 9): **ayuda, no thinking**.
- **Config por "sitio/tenant" (todo parametrizable):**
  ```yaml
  site: online-galaxy-war
  model: qwen2.5:7b          # resuelto por LiteLLM (Ollama/GPU/NPU)
  litellm_base_url: http://litellm.../v1
  purpose: "Ayudás a un visitante a entender el juego y cómo empezar. No inventes."
  knowledge:
    search_url: "https://<juego>/api/v1/catalog/graph/search?race=terran&planet=earth&q={q}&k=6"
    docs_url:   "https://<juego>/api/v1/catalog/graph/docs?race=terran&planet=earth"
  rate_limit_per_ip_per_day: 40
  lang_default: es
  ```
- **Modelos/NPU:** el widget habla **solo LiteLLM** (un contrato). LiteLLM rutea a **Ollama** (ya
  OpenAI-compat) o a un **RKNN-NPU**. RKNN **no es OpenAI-compat de fábrica** → hace falta un **shim**
  chico (FastAPI envolviendo `rkllm`) que exponga `/chat/completions` y **registrarlo como deployment
  en LiteLLM**. Con eso, el widget no cambia: elegís el modelo por config. (RKNN NPU = rápido/bajo
  consumo para modelos chicos en RK3588/RK1; ideal para "ayuda", no thinking.)

### 3.2 Cómo lo consume ESTE juego (mínimo, aditivo)
- El juego **ya expone** el grounding público: `/catalog/graph/search?q=&k=` (retrieval semántico) y
  `/catalog/graph/docs`. El widget se configura apuntando ahí → **cero cambios de backend** para
  groundear la ayuda pre-login.
- En el landing (`/game`) se agrega **una línea `<script src=".../widget.js" data-site="...">`**. Nada
  más. Si el widget-service está caído, el landing sigue funcionando (carga diferida, no bloqueante).
- (Opcional) exponer un `/catalog/graph/search` sin `race/planet` (genérico del juego) para la ayuda
  pre-login "general", ya que el visitante todavía no eligió raza. Es un pequeño add del juego, no del
  widget. Alternativa: default race/planet para la ayuda genérica.

## 4. Por qué separado y no adentro
- **Reuso real:** lo pedís para varios juegos/servicios; un servicio parametrizable se integra en
  cualquiera con una línea de `<script>` + una URL de conocimiento.
- **Aísla el costo/superficie de IA** del core del juego (que ya tiene su advisor post-login).
- **Un contrato** (LiteLLM) para todos los backends (Ollama/GPU/NPU) → operás la IA en un solo lugar.
- **Sin duplicar el grafo:** el widget lee el grafo del juego por HTTP; nunca hay una segunda copia.

## 5. Riesgos / decisiones abiertas
1. **Anti-abuso** (anónimo, pre-login): rate-limit por IP + presupuesto diario + captcha suave si hace
   falta; caer a respuestas deterministas (FAQ) cuando se agota el cupo (patrón SDD 9).
2. **Privacidad:** no logear PII; el visitante no está logueado. Métricas agregadas (reusar `game_llm_*`
   con `route`/tokens, SDD 65).
3. **RKNN shim:** ¿vale el esfuerzo del wrapper OpenAI-compat, o arrancamos con Ollama (ya integrado) y
   sumamos NPU después? — **propongo Ollama primero, NPU como optimización**.
4. **¿Open WebUI en algún lado?** Sí, como **consola interna opcional** (no embebida). No es el widget.
5. **Repo separado:** nombre tentativo `prelogin-assistant-widget`; este juego queda como **primer
   consumidor** (dogfooding). Definir si vive en la misma infra (k8s) con su propio deploy.

## 6. Conclusión (para decidir)
- **Open WebUI: descartado como widget pre-login** (auth obligatoria, no embebible, RAG duplicado).
  Útil solo como playground interno opcional.
- **Recomendado: microservicio genérico "prelogin-assistant-widget" en OTRO repo**, plug-and-play,
  parametrizable (modelo/propósito/fuente de conocimiento), backends por **LiteLLM (Ollama→NPU)**, que
  **este juego consume** apuntándolo a su `/catalog/graph/search` público con una línea de `<script>`.
- **Trabajo en este repo:** casi nulo (ya está el grounding público); a lo sumo un endpoint de búsqueda
  "genérico" para la ayuda pre-login. La construcción del widget va en el **otro proyecto**.
