# SDD 15 — Build de la imagen (Kaniko + Argo Workflows, in-cluster, arm64)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-23 · **Autor:** equipo online-game
> **Relacionado:** `deploy/Dockerfile`, `deploy/build/online-game-kaniko.yaml`, deploy del chart.

## 1. Objetivo

Construir la imagen del juego **dentro del cluster** (sin Docker local) y empujarla al **registry
interno** `registry.registry:5000`, en **arm64** (los nodos del juego son arm64). Reproducible:
un manifiesto versionado, no pasos a mano. Adaptado del patrón de `infra-ai`
(`roles/install-leloir-image`): Argo Workflows clona el repo y **Kaniko** buildea desde el
`Dockerfile`.

## 2. Por qué Kaniko + Argo (y no `docker build`)

- **No hay Docker host** a mano; el build corre como un Pod en k8s (Kaniko no necesita daemon).
- **Arch correcta**: el Workflow se fija al nodo `srv-rk1-nvme-01` (**arm64**), igual que el nodo
  donde corre el juego (`srv-super6c-01-nvme`) → la imagen es nativa, sin emulación.
- **Reproducible**: el código sale de `git` (rama `main` del repo público), no del disco local.
- **Empuja al registry interno** con `--insecure --skip-tls-verify` (registry HTTP in-cluster).

## 3. Cómo se hace

1. **Asegurar que `main` está pusheado** (Kaniko clona desde GitHub, no desde el disco):
   ```sh
   git push origin main
   ```
2. **Editar el tag** en `deploy/build/online-game-kaniko.yaml` (`--destination=...:<tag>`).
3. **Disparar el build**:
   ```sh
   kubectl create -f deploy/build/online-game-kaniko.yaml
   ```
4. **Seguir / esperar**:
   ```sh
   kubectl logs -l app=online-game-build -n kaniko -f
   kubectl wait workflow -l app=online-game-build -n kaniko \
     --for=jsonpath='{.status.phase}'=Succeeded --timeout=900s
   ```
5. **Desplegar la imagen nueva** (chart):
   ```sh
   helm upgrade galaxy deploy/helm -n online-game -f <values-local> \
     --set image.tag=<tag>
   ```
6. **Limpiar el build** (cuando el deploy verificó OK): borrar el Workflow/pod de Kaniko para no
   dejar basura en `kaniko` (el TTL igual los limpia ~1h, pero lo hacemos explícito):
   ```sh
   kubectl delete workflow -n kaniko -l app=online-game-build
   ```
   (Solo después de confirmar que la imagen anda; si falló, dejarlo para debug — el TTL de fallo
   retiene 24h.)

## 4. Anatomía del Workflow (`deploy/build/online-game-kaniko.yaml`)

- `inputs.artifacts.git` clona `https://github.com/villadalmine/online-game.git@main` (depth 1) en
  `/workspace/source`.
- Kaniko: `--dockerfile=/workspace/source/deploy/Dockerfile --context=dir:///workspace/source`
  (el Dockerfile copia desde la raíz del repo: `pyproject.toml`, `app/`, `content/`, `migrations/`,
  `web/`, `alembic.ini`).
- `--destination=registry.registry:5000/online-game:<tag>` `--insecure --skip-tls-verify`.
- `nodeSelector: srv-rk1-nvme-01` (arm64); `volumeClaimTemplates` workspace efímero (`longhorn-nvme`,
  TTL limpia 1h post-éxito, retiene 24h si falla).

## 5. Prerequisitos (ya provistos por infra-ai)

- Namespace `kaniko` + **Argo Workflows** instalado (CRD `workflows.argoproj.io`) con el RBAC
  `argo-workflow-runner` (lo aplica `make argo-workflows` en infra-ai).
- Registry interno `registry.registry:5000` accesible desde el cluster.

## 6. Notas / decisiones

- **Tag inmutable por release** (`0.2.0`, `0.3.0`, …) en vez de `latest` → el rollout es explícito
  y `helm upgrade --set image.tag=` fuerza la actualización del Deployment.
- **Sin caché** en v1 (simple, sin PVC de caché pre-creada). Si el build se vuelve lento, agregar
  un PVC `online-game-kaniko-cache` + `--cache=true --cache-dir=/cache` (como leloir).
- **Build remoto (offload a GitHub Actions)**: existe el patrón `run-remote-build` en infra-ai si
  alguna vez se quiere buildear fuera del cluster y sincronizar con skopeo. No es necesario hoy.
