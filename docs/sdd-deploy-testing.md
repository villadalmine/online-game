# SDD 22 — Tests del deploy: gate pre-rollout + `helm test` (no publicar una imagen que falla)

> **Estado:** propuesto · **Fecha:** 2026-06-24 · **Autor:** equipo online-game
> **Relacionado:** [SDD 15 build Kaniko](sdd-image-build-kaniko.md), [SDD 16 migraciones](sdd-migrations-deploy.md),
> [SDD 17 runbook upgrade](sdd-deploy-upgrade.md), `tests/`, `deploy/helm`.

## 1. Objetivo

Que **no se sirva una versión rota**: validar con tests **antes** y **durante** el rollout, y poder
**revertir solo** si algo falla. Tres capas, de "barato y temprano" a "última línea":
1. **Pre-imagen (CI/build)** — no construir/etiquetar una imagen que no pasa la suite.
2. **At-rollout (initContainer smoke)** — el pod nuevo no queda Ready si un smoke falla → el rollout
   se frena solo y los pods viejos siguen sirviendo.
3. **Post-deploy (`helm test`)** — e2e contra la release viva; con `--atomic` revierte automático.

## 2. Capa 1 — tests antes de construir la imagen (lo más importante)
La suite (`make test`: 180 unit/e2e + browser) ya corre local/CI. **Regla**: el build (SDD 15) solo
debe producir una imagen si la suite pasó. Opciones:
- **CI (GitHub Actions)**: job `pytest` que gatea el push del tag (si usás el offload remoto).
- **Kaniko/Argo (in-cluster)**: agregar un **step previo** al build en el Workflow
  (`deploy/build/online-game-kaniko.yaml`): un contenedor que `pip install .[dev] && pytest -q`
  sobre el repo clonado; si falla, el Workflow falla y **no se llega al paso Kaniko** → no hay
  imagen nueva. (Trade-off: agrega minutos al build; cachear deps.)
- **HECHO (2026-06-24)**: el **`Dockerfile` es multi-stage con un gate de tests** — un stage `test`
  corre `pip install .[dev] && pytest -q` (browser excluido por `addopts`) y el stage `runtime`
  **depende** de él (`COPY --from=test`). Kaniko siempre construye el runtime → ejecuta el gate;
  si un test falla, el `RUN` falla y **no se produce imagen**. Portable (Kaniko/docker/cualquiera),
  sin reescribir el Workflow. Trade-off: +1-2 min por build (instala dev-deps + corre la suite).

## 3. Capa 2 — smoke en initContainer (gate automático del rollout)
Agregar al Deployment un initContainer **`smoke`** (después de `migrate`) que corre un chequeo
**rápido** del CÓDIGO de la imagen nueva, en proceso, contra SQLite efímero (no toca Postgres):
import de la app + migraciones + un puñado de endpoints (health/catalog/register/login). Si falla,
el initContainer sale ≠0 → el pod no arranca → **el rollout queda frenado** (Deployment no progresa,
los viejos siguen). Es la red de seguridad si algo se coló al build.
- Implementación: `python scripts/smoke.py --selftest` (levanta la app en TestClient/SQLite y pega
  a los endpoints) o `pytest -m smoke` (subconjunto marcado). Liviano (segundos), no la suite entera.
- Opt-in `api.smokeInit.enabled` para no penalizar arranques si no se quiere.

## 4. Capa 3 — `helm test` (e2e contra la release viva)
Hook `helm.sh/hook: test`: un Pod que pega a los **endpoints reales** del Service de la release
(`scripts/smoke.py http://<release>-api`): `/health`, `/catalog`, alta+login happy-path, `/metrics`.
- Uso: `helm test galaxy -n online-game` después del upgrade.
- **Auto-rollback**: `helm upgrade --atomic --timeout 5m` → si los hooks/health fallan, Helm
  **revierte** a la revisión anterior solo. Combinado con la Capa 2, un deploy malo no queda vivo.

## 5. Qué testear (alcance)
- **Smoke (siempre)**: health, migraciones aplicadas, `/catalog`, register+login, `/metrics`,
  `/public/online`. Es lo que prueba que "arranca y responde lo básico".
- **Suite completa**: en CI/build (Capa 1), no en cada pod (pesada, necesita dev-deps).
- **"Lo que cambió el CHANGELOG"**: tentador, pero derivarlo automático es frágil. Mejor: smoke fijo
  + suite completa en CI. (El CHANGELOG documenta; los tests por-feature ya existen, regla del proyecto.)

## 6. Implementación en este repo (v1)
- `scripts/smoke.py` (stdlib + httpx): `smoke(base_url)` → health/catalog/register+login; sale ≠0 si
  algo falla. Modo `--selftest` levanta la app en SQLite efímero (para la Capa 2).
- `COPY scripts ./scripts` en el `Dockerfile` (que la imagen lleve el smoke).
- `deploy/helm/templates/tests/smoke.yaml` (`helm.sh/hook: test`) → `helm test`.
- Follow-up: step de pytest previo al build en el Workflow de Kaniko (Capa 1) + initContainer smoke
  opt-in (Capa 2) + `--atomic` en el runbook (SDD 17).

## 7. Validación
- `helm test galaxy` pasa contra una release sana y **falla** si se rompe un endpoint (probar
  apuntando a un Service caído). El smoke local (`python scripts/smoke.py URL`) idem.
- El initContainer smoke (cuando se active) bloquea el rollout ante un fallo (chaos: meter un import
  roto → el pod no llega a Ready).

## 8. Riesgos / decisiones
- **Peso**: no correr la suite entera en cada pod; smoke liviano en cluster, suite en CI.
- **Dev-deps en la imagen**: el smoke usa solo runtime (httpx); el `pytest` completo queda en CI.
- **Falsos verdes**: el smoke no reemplaza la suite; es una red, no la cobertura.
