# SDD 58 — Builds multi-arch del CD (cluster mixto arm64/amd64)

> **Estado:** **diseño** (workaround ya aplicado) · **Fecha:** 2026-06-29
> **Relacionado:** [SDD 16 build con Kaniko](sdd-image-build-kaniko.md),
> [SDD 44/45 test-gate CD](sdd-test-gate-cicd.md), [SDD 52 disco del CD](sdd-cicd-storage-resilience.md),
> `deploy/build/online-game-cicd.yaml`, `deploy/helm/examples/values-prod.yaml`.

## 1. Incidente (2026-06-29)
El cluster es **mixto**: prod corre en nodos **arm64** (super6c + rk1-nvme), pero se sumó un nodo
**amd64** (`srv-t7910`) con la label `storage=rk1-longhorn` (el pool que usa el CD para disco). Kaniko
buildea para **la arquitectura del nodo donde corre** (no es multi-arch). El build de 1.105.0 cayó en
`srv-t7910` → imagen **amd64** → en prod (arm64) el pod falló en el init con
**`exec /usr/local/bin/python: exec format error`** → rollout trabado (prod siguió sano en 1.104.4).

## 2. Workaround aplicado (ya en repo)
- **CD pineado a arm64**: `online-game-cicd.yaml` nodeSelector `storage=rk1-longhorn` **+
  `kubernetes.io/arch: arm64`** → buildea solo en los rk1-nvme arm (que igual tienen Longhorn).
- **Runtime pineado a arm64**: `values-prod.yaml` `nodeSelector.kubernetes.io/arch=arm64` → la imagen
  arm nunca se agenda en el nodo amd64.
- Costo: el nodo amd64 (más potente) queda **sin usarse** para el juego.

## 3. Diseño (fix real, para iterar)
Hacer **builds multi-arch** (manifest list arm64+amd64) para aprovechar TODOS los nodos:
- Kaniko **no** hace multi-arch nativo en un solo run. Opciones:
  1. **Dos builds Kaniko** (uno por arch, cada uno con su nodeSelector) + un paso que arma el
     **manifest list** (`crane`/`manifest-tool`/`docker buildx imagetools`) → un tag que sirve ambas.
  2. Migrar el build a **BuildKit/buildx** con QEMU (multi-arch en un paso; más pesado en ARM).
- Con manifest list, runtime y CD dejan de necesitar el pin de arch (cada nodo baja su variante).
- Validar que los **gates** corran en la arch de prod (o en ambas) para no promover algo que falla en arm.

## 4. Tests / validación
- Smoke post-deploy: el init `smoke` (ya existe) corre en prod y atrapa el `exec format error`.
- (multi-arch) verificar que `docker manifest inspect`/`crane manifest` del tag liste arm64 **y** amd64.

## 5. Rollout / riesgos
- El workaround es seguro y mínimo (solo nodeSelectors). El multi-arch es más infra → iterar luego.
- Riesgo del workaround: si algún día se quitan los nodos arm del pool del CD, el build queda Pending
  (mitiga: hay 4 rk1-nvme arm). Riesgo multi-arch: builds más lentos/pesados en ARM (QEMU).
