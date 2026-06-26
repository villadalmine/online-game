# SDD 45 — Gate de tests antes del deploy: e2e (API) + Chrome (UI), in-cluster y offline

> **Estado:** **F1 implementado + F2/F3 manifiestos listos (falta 1ª corrida live)** · **Fecha:**
> 2026-06-26 · **Autor:** equipo online-game
> **Relacionado:** [SDD 44 CD in-cluster](sdd-cicd-in-cluster.md), [SDD 15 build Kaniko](sdd-image-build-kaniko.md),
> [SDD 17 runbook](sdd-deploy-upgrade.md), [SDD 22 helm test](sdd-deploy-testing.md), `tests/`,
> `deploy/build/`.

## 1. Problema (por qué existe este SDD)

Esta semana se **deployaron bugs a producción** que un test hubiera atrapado: 500 en mercado/hub al
comprar/vender, 500 al entrenar en modo dibujos, deslogueo por error transitorio. La causa raíz **no
es cada bug**: es que **se puede deployar sin que los tests verifiquen el juego entero**, y que los
tests de UI (browser) no corrían en el pipeline. La regla nueva es simple y dura:

> **Si no pasan los tests, el build NO se deploya.** Y los tests prueban **todo el juego**: cada
> acción **por API** (e2e) y **por la UI** (Chrome/Playwright), contra una instancia **real
> desplegada**, **todo in-cluster y sin internet**.

## 2. Principios
- **Gate duro:** el deploy a prod (`galaxy`) depende de que los pasos de test terminen `Succeeded`.
  Si fallan, el Workflow corta y prod queda intacto.
- **Probar el juego real, no solo unidades:** los tests corren contra una **instancia desplegada**
  (`galaxy-dt`, *deploy de testing*), misma imagen y mismo chart que prod → si anda ahí, anda en prod.
- **Offline / in-cluster:** nada sale a internet. Imagen de test con Chromium **horneado** y subido
  al **registry interno**; el código sale del workspace ya clonado (build), no se baja nada más.
- **Cobertura de TODAS las acciones:** un catálogo de acciones (build, train, research, market/hub
  buy/sell, blackmarket, transport, colonize, attack, spy, expedición) ejercitado por API y por UI.
- **Espejo local:** el mismo flujo se puede correr en la laptop (`make test`, `make test-ui`,
  `make e2e-local`) — lo que corre el cluster es lo mismo que corre el dev.

## 3. Arquitectura del pipeline (un Workflow, etapas con dependencias)

`deploy/build/online-game-cicd.yaml` (SDD 44) se extiende a un DAG con **gate**:

```
  build ──▶ deploy-dt ──▶ ┌── e2e-api ──┐
                          │             ├──▶ promote-prod   (helm upgrade galaxy)
                          └── e2e-chrome┘
   (si e2e-api O e2e-chrome fallan → NO se ejecuta promote-prod; prod intacto)
```

1. **build** (Kaniko): imagen `online-game:<tag>` al registry interno (SDD 15).
2. **deploy-dt**: `helm upgrade --install galaxy-dt` (mismo chart, **release distinto**) con la
   imagen recién buildeada, en el **namespace de testing** (`online-game-dt`), **SQLite efímero** y
   sin dependencias externas (sin OpenRouter: `NPC_BRAIN=rules`; sin SSE externo). Es **efímero**:
   se borra al final (éxito) o se retiene para debug (fallo).
3. **e2e-api**: corre `pytest` (suite completa **menos** browser) contra `galaxy-dt` — y/o la suite
   in-process. Usa la **imagen de test** (`online-game-test:<tag>`, §4).
4. **e2e-chrome**: corre `pytest -m chrome` (Playwright) **contra la URL de `galaxy-dt`**, con el
   Chromium horneado en la imagen de test. Verifica la UI real (modo dibujos, comprar/vender,
   entrenar, no-deslogueo).
5. **promote-prod**: solo si 3 y 4 pasaron → `helm upgrade galaxy --reuse-values --set image.tag`
   (SDD 44). Si no, el Workflow queda `Failed` y prod no se toca.
6. **cleanup**: `helm uninstall galaxy-dt` + borra el ns/PVC efímero (en éxito; en fallo se retiene).

> **Variante "dos workflows" (como se pidió):** `e2e-api` y `e2e-chrome` son **WorkflowTemplates**
> reutilizables (`deploy/build/wt-e2e-api.yaml`, `wt-e2e-chrome.yaml`) que el pipeline invoca y que
> también se pueden correr sueltas (`argo submit wt-e2e-chrome.yaml -p target_url=…`).

## 4. Imagen de test (offline, con Chromium)

`deploy/Dockerfile.test` (FROM la imagen del juego) agrega **dev+ui extras** (`pytest`,
`playwright`, `pytest-playwright`) y **hornea Chromium** (`playwright install --with-deps chromium`).
Se buildea con Kaniko al registry interno (`online-game-test:<tag>`) **una vez por release** (o solo
cuando cambian deps). Así los pasos de test **no bajan nada de internet**: ni browsers ni paquetes.

- arm64 (los nodos del juego son arm64); Playwright trae Chromium arm64.
- Reusa la capa de deps del juego → el build de test es incremental y rápido.

## 5. Instancia de testing `galaxy-dt` (misma receta, otro nombre)

Mismo `deploy/helm`, **release `galaxy-dt`** en ns `online-game-dt`, con `values-dt.yaml`:
- `nameOverride`/`fullnameOverride` → recursos `galaxy-dt-*` (label e ingress separados).
- `DATABASE_URL` SQLite en un PVC efímero (o un Postgres efímero del mismo chart) — **datos
  desechables**, se crea y se borra por corrida.
- `NPC_BRAIN=rules`, sin `OPENROUTER_*`, `AUTO_TICK_SECONDS` chico para e2e deterministas.
- `ALLOWED_EMAILS=""` (registro abierto para que los tests creen usuarios) y
  `signup_requires_approval=false`.
- Sin Gateway público (Service ClusterIP); los tests le pegan por DNS interno
  `galaxy-dt-api.online-game-dt.svc`.
- **Sin límites para probar funcionalidad de UI (clave):** para verificar que *cada acción de la web
  funciona* (no el balance), el entorno de test **no debe frenar por recursos ni accesos**. El
  fixture de test **siembra** al usuario con **energía altísima**, **naves de carga**, **escolta**,
  **stock de minerales** y los **edificios/tecnologías** necesarios — así el test puede tocar
  comprar/vender/entrenar/construir/colonizar y llegar al resultado, sin chocar con "energía
  insuficiente". (El **balance** y la **economía real** se prueban aparte, con sus propios e2e de
  servicio; y las partes con **costo/acceso externo** —LLM/OpenRouter— se prueban distinto: en el
  gate el asistente va en `NPC_BRAIN=rules`, sin gastar créditos.)

`make dt-up` / `make dt-down` lo levantan/bajan localmente contra el cluster para debug manual.

## 6. Catálogo de acciones a cubrir (la "prueba de todo")

Tabla viva; cada acción tiene su **e2e API** (en `tests/test_api_e2e.py`) y, las accionables desde
pantalla, su **paso Chrome** (en `tests/test_web_smoke.py`):

| Acción | API e2e | Chrome (UI) |
|---|---|---|
| onboarding (galaxia/planeta/raza) | ✅ | ✅ (carga + juego visible) |
| construir edificio (incl. orbital) | ✅ | ✅ (grilla ícono, costo) |
| entrenar unidad (worker/soldier/…) | ✅ | ✅ (modo dibujos no rompe) |
| investigar tecnología | ✅ | — |
| mercado planetario buy/sell | ✅ | ✅ |
| hub buy/sell (con/ sin nave+escolta) | ✅ | ✅ |
| mercado negro (trueque) | ✅ | — |
| transporte entre planetas | ✅ | — |
| colonizar (superficie/orbital/lunar) | ✅ | ✅ (modal planeta) |
| atacar / reportes de combate | ✅ | ✅ (force-picker) |
| espiar / intel | ✅ | — |
| expedición a luna | ✅ | — |
| **sesión resiliente** (503 no desloguea) | — | ✅ |
| **sin errores JS** en cada panel | — | ✅ (captura console.error) |

La fila clave nueva: **"sin errores JS en cada panel"** — el test Chrome abre cada panel en modo
normal y en modo dibujos y **falla si hay un `console.error` o `pageerror`**. Eso atrapa los 500/JS
que se escaparon.

## 7. Espejo local (sin cluster)
- `make test` → suite API (rápida, in-process, SQLite).
- `make test-ui` → tests Chrome con Playwright local (levanta uvicorn efímero, `ALLOWED_EMAILS=""`).
- `make e2e-local` → corre **todo** (API + Chrome) como lo haría el gate, contra un uvicorn local.
Todo offline: usa SQLite y Chromium ya instalado (`playwright install chromium`, una vez).

## 8. Fases de implementación
- **F1 (base del gate) — HECHO:** marker `chrome` (pyproject); `tests/test_web_smoke.py` (Playwright)
  cubre **todos los paneles sin errores JS** (normal + dibujos, usuario sembrado sin límites vía
  `_seed_unlimited`) + resiliencia 503/401. `make test` (API, `-m "not chrome"`), `make test-ui`
  (Chrome), `make e2e-local` (gate completo local).
- **F2 (test image + workflows) — HECHO (manifiestos):** `deploy/Dockerfile.test` (imagen con
  Chromium horneado) + `deploy/helm/examples/values-dt.yaml` (instancia `galaxy-dt`, `make dt-up/dt-down`).
  `deploy/build/online-game-cicd.yaml` extendido a DAG con **gate**: `build` + `build-test` →
  `e2e-api` + `e2e-chrome` → `promote-prod` (solo si los gates pasan). Validado por `helm template`
  y `kubectl --dry-run=server`. **Falta la 1ª corrida live** (buildea la imagen de test la 1ª vez).
- **F3 (gate efectivo) — HECHO:** `make deploy` dispara el pipeline con gate; `make deploy-force`
  queda como salida de emergencia (sin gate), documentada.

## 9. Riesgos / decisiones
- **Costo/tiempo del gate:** el browser test agrega ~1-2 min; aceptable (corre solo en release).
- **`galaxy-dt` consume recursos:** efímero + límites chicos; se borra al terminar.
- **Determinismo:** `NPC_BRAIN=rules`, `AUTO_TICK` controlado y DB fresca por corrida → tests estables.
- **Offline:** todo lo que el pipeline necesita (imagen de test con Chromium, paquetes) vive en el
  **registry interno**; el único `git clone` es del repo público en el step de build (igual que hoy).
- **Fallback:** `make deploy-force` (deploy directo sin gate) queda documentado para incidentes, con
  la advertencia de que saltea la red de seguridad.
