# SDD 52 — Resiliencia de almacenamiento/disco del CD (no llenar el nodo, no pinear)

> **Estado:** **parcial implementado** (lo urgente) + **diseño** (lo que falta iterar) · **Fecha:** 2026-06-28
> **Relacionado:** SDD 15-17 (Kaniko/Argo), SDD 44/45 (gate de tests), SDD 32 (Longhorn), incidente
> 2026-06-28. Archivos: `deploy/build/online-game-cicd.yaml`, StorageClasses del cluster.

## 1. Problema (incidente 2026-06-28)
El pipeline de CD (Argo Workflow: build Kaniko + gates e2e + promote) **se trabó** y/o falló por disco:
- **Pineado a UN nodo** (`nodeSelector: kubernetes.io/hostname: srv-rk1-nvme-01`): cuando ese nodo
  entró en **DiskPressure** (taint `node.kubernetes.io/disk-pressure:NoSchedule`), los pods quedaron
  **Pending para siempre** (1 nodo matchea el selector y estaba tainteado; los otros no matcheaban).
- **Disco del nodo lleno** pese a usar una PVC para el scratch. Causas (claves, ver §3):
  - **PVC Longhorn replica ×3**: la PVC del workspace (20Gi, `longhorn-nvme`) guarda el volumen **+ 3
    réplicas** en `/var/lib/longhorn` en el disco de los nodos rk1-nvme → hasta 60Gi de disco de NODO
    por workflow. Con varias corridas/día sin limpiar → se apilan (eran 5 PVCs = ~80-300Gi).
  - **Imágenes de contenedor**: containerd guarda cada imagen en el *image fs* del nodo (no en la PVC).
    Reusar/churnear tags + imágenes de test pesadas (Chromium/Playwright) → llena imagefs.
- **Bonus** (no de disco pero del mismo día): reusar el MISMO tag de imagen + `imagePullPolicy`
  default `IfNotPresent` → el nodo corría una imagen de test **cacheada/stale** (gate corría tests
  viejos). Fix: `imagePullPolicy: Always`.

## 2. Por qué una PVC NO evita el disco del nodo (k8s)
La pregunta "¿que el pod entero use una PVC en vez de disco interno?" — **no se puede**:
- El **rootfs del contenedor** viene de las capas de la **imagen**, almacenadas por el runtime en el
  *image filesystem* del **nodo** (nivel-nodo, lo limpia el kubelet con image-GC). No es montable como
  PVC. *(k8s: "Garbage collection of images", "Node-pressure eviction".)*
- La **capa escribible + `/tmp` + emptyDir + logs** = *local ephemeral storage* del nodo: todo lo que
  se escribe FUERA de un `volumeMount` va al disco del nodo. *(k8s: "Local ephemeral storage".)*
- Solo se pueden **montar directorios puntuales** en volúmenes (ya hicimos `TMPDIR=/workspace` → PVC).
- Y la PVC, si es Longhorn, **igual consume disco de nodo** (réplicas en `/var/lib/longhorn`).

## 3. Implementado (lo urgente, ya en `online-game-cicd.yaml`)
- **Pool de nodos**: `nodeSelector: storage: rk1-longhorn` (rk1-nvme 01-04, arm64 + Longhorn-NVMe) en
  vez de pinear a uno → si un nodo está en DiskPressure, el scheduler usa otro del pool.
- **ttl corto**: `secondsAfterSuccess: 600` / `secondsAfterFailure: 1800` → borra el Workflow **y su
  PVC** (y los pods, por podGC) rápido, no en horas.
- **`podGC: OnWorkflowSuccess`**: limpia pods al salir bien; deja los fallidos para leer logs (no hay
  artifact repo). El ttl evita que se apilen.
- **`imagePullPolicy: Always`** en los pods de test → nunca correr imagen stale por reusar tag.
- **Operación**: NO reusar tags (bumpear versión en cada deploy). Limpiar workflows fallidos viejos.

## 4. A iterar (diseño)
1. **StorageClass efímera de 1 réplica** para el workspace del CD: `longhorn-nvme-ephemeral` con
   `numberOfReplicas: "1"` + `reclaimPolicy: Delete` → **3× menos disco de nodo** (el scratch del
   build es descartable, no necesita replicación/HA). Apuntar el `volumeClaimTemplate` ahí.
2. **PVC más chica** (20Gi → ~10Gi) si el build entra.
3. **¿emptyDir en vez de PVC?** Trade-off: emptyDir auto-limpia con el pod y no replica, pero usa el
   *ephemeral storage* del nodo (cuenta para eviction). En nodos rk1-**nvme** podría alcanzar y ser más
   simple que Longhorn. Evaluar (el motivo original de la PVC fue sacar el scratch del SD/eMMC interno;
   en rk1-nvme el disco YA es NVMe → emptyDir iría a NVMe igual).
4. **Image GC del kubelet**: bajar `--image-gc-high-threshold` o asegurar que GCea las imágenes de
   test viejas; o usar tags por commit + limpieza periódica del registry/nodos.
5. **Artifact repository de Argo (MinIO)**: archivar logs de los pasos → poder volver a `podGC:
   OnWorkflowCompletion` (aún más limpio) sin perder los logs de fallos. (SDD 17 follow-up.)
6. **Alertas** (SDD pendiente): ServiceMonitor + PrometheusRule sobre DiskPressure de los nodos del
   pool y sobre Workflows fallidos → enterarse antes de que trabe el CD.

## 5. Validación
- Forzar DiskPressure en un nodo del pool → el CD agenda en otro (no Pending eterno).
- Tras N deploys, contar PVCs `cicd-*-workspace` → deben tender a ≤1-2 (ttl las limpia).
- `imagePullPolicy: Always` → re-deploy del mismo tag corre la imagen nueva (no stale).
