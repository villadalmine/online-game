# SDD 33 — Seguridad: pods sin root + RBAC/sandbox + defensa contra exploits vía la IA

> **Estado:** propuesto · **Fecha:** 2026-06-24
> **Relacionado:** SDD 9 (LLM), SDD 28 (métricas/rate-limit LLM), SDD 2 (asistente/hack), SDD 14
> (allowlist), `deploy/Dockerfile`, `deploy/helm/templates/`, `app/services/{advisor,npc,llm}.py`,
> `web/index.html`.

## 1. Objetivo y modelo de amenaza
Endurecer el juego ante: (a) **compromiso de un pod** (que NO corra como root, que no pueda pivotar);
(b) **abuso/inyección de prompt vía la IA** — un jugador "habla con el asistente" e intenta un exploit;
(c) **movimiento lateral** en el cluster. Minimizar el blast-radius con defensa en profundidad.

## 2. Estado actual (verificado 2026-06-24)
- **Pods como root:** el `Dockerfile` **no** define `USER` → corre como **root**. Los manifests **no**
  tienen `securityContext` (ni `runAsNonRoot`, ni drop de capabilities, ni `seccomp`). ⚠️
- **Sin NetworkPolicy** → los pods pueden hablar con cualquier cosa (lateral movement). ⚠️
- **ServiceAccount:** la API usa la `default` con token automontado, aunque **no habla con la API de
  k8s**. El único RBAC legítimo es el Job que parchea el listener del Gateway (ya scoped). ⚠️ (token de más)
- **Bueno ya:** la salida del asistente se renderiza con **`textContent`** (no `innerHTML`) → **no hay
  XSS** desde el texto del LLM. Las acciones de NPC se **validan/chequean factibilidad** antes de
  ejecutar (mismas reglas que un humano). El "hack" del asistente está **capeado (3/día)** y hay
  **rate-limit** del asistente por jugador (SDD 9/28). Secretos fuertes en prod ya forzados al arranque.

## 3. Superficie de ataque de la IA (el miedo: "que hablen con la IA y me hagan un exploit")
**Clave: la IA del juego NO es un agente con herramientas sobre el cluster.** Es una llamada HTTP a
LiteLLM que devuelve **texto** (asistente) o **JSON de acción** (NPC). Análisis del blast-radius:

- **Asistente (input del jugador → LLM):** su contexto es el **grafo del juego (RAG)**, no secretos. Su
  salida es **texto** que se muestra (con `textContent` → sin XSS) **+** una única acción mutante: el
  **hack** (otorga material faltante), **capeado a 3/día y enforced en código** (no por el LLM). →
  una inyección de prompt **no puede** exceder el cap, ejecutar acciones de juego arbitrarias, ni leer
  datos de otros (el contexto se arma server-side por jugador).
- **NPC (LLM → acción):** la salida JSON se **parsea + valida + chequea factibilidad** contra las mismas
  reglas/recursos que un humano antes de `dispatch_action` → una respuesta "envenenada" **no** hace
  trampa ni acciones ilegales (a lo sumo cae a reglas).
- **Pivote al cluster:** imposible desde el prompt — el LLM **no tiene tools** (no MCP, no kubectl); es
  un endpoint OpenAI. El pod del juego, además, no debería tener credenciales de k8s (ver §4b).
- **Abuso de costo/recursos:** rate-limit del asistente por jugador + **métricas de uso por
  `player:<id>`** (SDD 28) → acotado y visible (alertable).
- **Distinción importante:** los **agentes de ops** (hermes/holmes con MCP `kubernetes`/`kagent`) **sí**
  tienen poder sobre el cluster → ésos necesitan su propio hardening (RBAC del agente, **aprobación
  humana para writes** — ya tienen "debate con Tito" obligatorio). **No son parte del juego** (viven en
  `ai`/infra-ai), pero comparten el LiteLLM → no exponer ese poder al juego.

→ **Conclusión:** el riesgo de "hablar con la IA del juego" es **bajo** (texto + hack capeado, sin
tools, sin cluster). Las estrategias de abajo lo reducen aún más y blindan el pod por si algo falla.

## 4. Estrategias (defensa en profundidad)

### 4a. Pods sin root + sandbox del contenedor
- **Dockerfile:** crear usuario no-root y `USER 10001` (app no necesita root).
- **`securityContext`** (pod + container) en api/worker/postgres/redis:
  ```yaml
  securityContext:                 # pod
    runAsNonRoot: true
    runAsUser: 10001
    fsGroup: 10001                 # para PVC (postgres/redis)
    seccompProfile: { type: RuntimeDefault }
  # container:
    allowPrivilegeEscalation: false
    capabilities: { drop: ["ALL"] }
    readOnlyRootFilesystem: true   # + emptyDir para /tmp (sqlite dev, caches)
  ```
  Postgres/redis: corren como su propio uid; usar `fsGroup` para el PVC; `readOnlyRootFilesystem`
  puede requerir montar los dirs de datos (ya en PVC) y `/tmp`/run en emptyDir.

### 4b. RBAC mínimo / menor privilegio
- La API **no habla con k8s** → `automountServiceAccountToken: false` en el deploy + SA dedicada **sin
  Role/Binding**. (El único RBAC necesario es el Job de gateway-listener, ya acotado a ese verbo/recurso.)

### 4c. NetworkPolicy (limitar movimiento lateral)
- **default-deny** ingress+egress en `online-game`, y permitir sólo:
  - ingress: desde el **Gateway** (Cilium) al `galaxy-api:80`.
  - egress: a `galaxy-postgres:5432`, `galaxy-redis:6379`, `litellm-proxy.ai:4000`, DNS, y salida a
    internet **sólo** para el LLM hosted (si aplica) / mailer. Nada más.
- Con Cilium se puede usar `CiliumNetworkPolicy` (identidad por label) para algo más fino.

### 4d. Aislamiento fuerte (futuro)
- Correr el juego en **su propio vCluster** (ya planeado, SDD 30/tech) → API/RBAC/CRDs propios →
  un compromiso del juego **no** ve el cluster anfitrión. Es el sandbox más fuerte.

### 4e. Hardening de la IA (prompt + salida)
- Tratar el **input del jugador como no confiable**: delimitarlo en el prompt; el system prompt ya
  acota ("conocimiento SOLO el grafo; no inventes recursos/reglas").
- **Nunca** poner secretos/PII en prompts; el `end_user` es nick, no email (SDD 20/28).
- **No dar tools** al LLM del juego (mantenerlo como texto/JSON validado).
- Mantener: hack **capeado**, **validación** de acción NPC, **rate-limit** del asistente, salida con
  **`textContent`** (revisar también `msg()`/cualquier render para no usar `innerHTML` con texto del LLM).
- (Opcional) un filtro de moderación barato sobre la salida del asistente si preocupa contenido tóxico.

## 5. Validación / tests
- **Pod no-root:** el pod arranca con `runAsUser != 0`; falla si alguien mete `runAsNonRoot:false`.
- **RBAC:** sin token de SA montado en la API; el SA no puede listar/crear nada (negado).
- **NetworkPolicy:** desde el pod del juego, conexión a otro ns (que no sea pg/redis/litellm) **falla**.
- **IA:** e2e de inyección — un mensaje malicioso al asistente **no** excede el cap de hack, **no**
  dispara acciones, y la respuesta se renderiza como texto (no ejecuta HTML/JS). NPC con JSON
  "envenenado" → cae a reglas, no hace trampa (ya cubierto por tests de SDD 9).

## 6. Riesgos / decisiones
- **`readOnlyRootFilesystem`** puede romper si la app escribe fuera del PVC (sqlite local de dev,
  caches) → montar `emptyDir` en `/tmp` y los paths necesarios; probar en staging.
- **Imágenes de terceros** (postgres/redis/ollama) ya corren como usuarios no-root propios; ajustar
  `fsGroup`, no forzar `runAsUser` que rompa su entrypoint.
- **NetworkPolicy** mal armada puede cortar el juego → empezar en modo "log/audit" o aplicar primero en
  staging; permitir DNS explícito.
- **Orden sugerido:** (1) Dockerfile USER + securityContext api/worker (bajo riesgo) → (2)
  `automountServiceAccountToken:false` → (3) securityContext de pg/redis con fsGroup → (4)
  NetworkPolicy (con cuidado) → (5) vCluster (proyecto).
