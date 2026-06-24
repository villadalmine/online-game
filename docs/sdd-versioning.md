# SDD 23 — Estrategia de versionado (SemVer) y releases

> **Estado:** propuesto · **Fecha:** 2026-06-24 · **Autor:** equipo online-game
> **Relacionado:** [SDD 15 build](sdd-image-build-kaniko.md), [SDD 17 runbook](sdd-deploy-upgrade.md),
> [SDD 22 tests del deploy](sdd-deploy-testing.md), `deploy/build/online-game-kaniko.yaml`, `Chart.yaml`.

## 1. Problema

Veníamos subiendo el tag de imagen **por cada cambio** (0.2.0 → … → 1.2.3 en una tarde), sin
significado semántico y con un build (que ahora corre la suite, ~3 min) por cada micro-cambio. Hace
falta una disciplina: **qué número subir, cuándo, y qué NO requiere versión**.

## 2. SemVer: MAJOR.MINOR.PATCH

- **MAJOR** (`X.0.0`): cambio **incompatible** del contrato (API `/api/v1` rompe clientes, formato de
  datos, etc.). Raro; idealmente versionar la API antes (`/api/v2`).
- **MINOR** (`x.Y.0`): **feature** nueva compatible hacia atrás (endpoint nuevo, métrica nueva, etc.).
- **PATCH** (`x.y.Z`): **bugfix** / cambios internos sin tocar el contrato.
- Estamos **post-1.0** (publicado). Versión real actual: **1.2.3**.

## 3. Reglas (lo que arregla el churn)

1. **Versión por RELEASE, no por commit.** Acumulá commits en `CHANGELOG [Unreleased]`; cuando
   decidís desplegar un conjunto, **cortás UNA versión**. No un tag por fix.
2. **Cambios de SOLO config/env NO llevan versión ni rebuild.** Agregar un email a `ALLOWED_EMAILS`,
   cambiar `STREAM_INTERVAL`, etc. = `helm upgrade -f values-local.yaml` (rola pods con la **misma
   imagen**). Esto solo ya elimina la mayoría de los bumps. *(Solo necesita imagen nueva lo que
   cambia CÓDIGO.)*
3. **El tag de imagen = la versión del release.** Fuente única: `Chart.yaml: appVersion` espejado al
   `--destination` del build y a `image.tag`. Hoy se setea a mano en
   `deploy/build/online-game-kaniko.yaml` + values; unificar en un solo lugar.
4. **Cómo elegir el bump**: mirar `CHANGELOG [Unreleased]` → si hay `feat` → MINOR; solo `fix` →
   PATCH; `BREAKING` → MAJOR. (Se puede automatizar con prefijos conventional-commits.)
5. **Al cortar el release**: renombrar `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`, **git tag `vX.Y.Z`**,
   buildear con ese tag, desplegar con `--atomic` + `helm test` (SDD 22).

## 4. Flujo propuesto

```
trabajás → commits → CHANGELOG [Unreleased] crece   (NO build por commit)
            │
   ¿es solo env/config? → helm upgrade (misma imagen, sin versión)
            │ hay código nuevo y querés desplegar
   cortar release X.Y.Z:
     - mover [Unreleased] → [X.Y.Z] - fecha; git tag vX.Y.Z
     - build (gate de tests, SDD 22 capa 1) con tag X.Y.Z
     - helm upgrade --atomic --set image.tag=X.Y.Z ; helm test
```

## 5. Implementación sugerida (follow-up, opcional)
- `make release V=X.Y.Z`: valida limpio, mueve la sección del CHANGELOG, setea `Chart.appVersion`
  + el tag del build manifest, `git tag vX.Y.Z`, push. Un solo comando, una sola fuente del número.
- (Más adelante) derivar X.Y.Z de conventional-commits / `git describe` para automatizar el bump.
- Mantener `Chart.yaml version` (del chart) separado de `appVersion` (de la app/imagen); hoy el
  chart está fijo en 0.1.0 — subirlo cuando cambie el chart en sí.

## 6. Decisiones
- **Post-1.0**: cuidamos compatibilidad de `/api/v1`; un cambio que rompa clientes → `/api/v2`, no
  MAJOR sorpresivo.
- **No re-versionar el pasado**: la disciplina aplica de acá en más (la ráfaga 0.x→1.2.3 fue el
  período de arranque/publicación).
- **Hotfix**: PATCH sobre el último release.
