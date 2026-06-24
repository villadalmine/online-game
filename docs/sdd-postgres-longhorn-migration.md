# SDD 32 — Plan de migración del Postgres del juego a Longhorn (opción A, ejecutable)

> **Estado:** plan a ejecutar (runbook) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 30 mantenimiento](sdd-maintenance-resilience.md), [SDD 10 backup/restore](sdd-durability-backup-restore.md),
> `deploy/helm/templates/datastores.yaml`, `deploy/helm/values.yaml` (`postgres.persistence.storageClass`).

## 1. Objetivo
Mover el PVC de `galaxy-postgres` de **`local-path`** (node-local, hoy en `srv-t7910`) a **Longhorn**
(replicado en los RK1) → al apagar/perder el fierro GPU, **Postgres reagenda a otro nodo y el juego
sigue** (SDD 30). Es la opción **simple y suficiente** (sin operador; CNPG = SDD 31 para HA real).

## 2. Por qué hay que recrear (no es un toggle)
El `storageClassName` de un `volumeClaimTemplate` de un StatefulSet es **inmutable**. Cambiar
`postgres.persistence.storageClass` y hacer `helm upgrade` **no** migra el PVC existente. Hay que:
**backup → borrar el StatefulSet y el PVC viejo → recrear con Longhorn → restore.** Por eso requiere
una **ventana corta** (el juego no escribe durante la migración).

## 3. Pre-requisitos
- Longhorn sano (`kubectl -n longhorn-system get nodes.longhorn.io`); SC `longhorn` o `longhorn-nvme`.
- Espacio en los discos NVMe de los RK1 (la DB es chica, 8Gi).
- Ventana de mantenimiento avisada (downtime ~5-15 min).
- Acceso a `kubectl` + el chart local (`deploy/helm`).

## 4. Runbook (paso a paso)
> Variables: `NS=online-game`, `STS=galaxy-postgres`, `PVC=data-galaxy-postgres-0`. DB/credenciales
> salen del Secret del release (no reproducir valores acá).

**1) Backup lógico (imprescindible).**
```
kubectl exec -n $NS $STS-0 -- sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > galaxy-$(date +%F).sql
test -s galaxy-*.sql && echo "backup OK ($(wc -c < galaxy-*.sql) bytes)"   # verificar que NO está vacío
```
(o usar el CronJob de backup de SDD 10). **No seguir si el dump está vacío.**

**2) Frenar escrituras (ventana).**
```
kubectl scale deploy/galaxy-api -n $NS --replicas=0          # API abajo
kubectl patch cronjob galaxy-tick -n $NS -p '{"spec":{"suspend":true}}'   # tick (NPCs) abajo
```

**3) Red de seguridad: retener el dato viejo por las dudas.**
```
PV=$(kubectl get pvc $PVC -n $NS -o jsonpath='{.spec.volumeName}')
kubectl patch pv "$PV" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'  # no se borra al borrar el PVC
```

**4) Borrar StatefulSet + PVC viejo (el dato viejo queda en el PV retenido + en el dump).**
```
kubectl delete statefulset $STS -n $NS --cascade=foreground
kubectl delete pvc $PVC -n $NS
```

**5) Recrear en Longhorn (helm).** En `values-local.yaml`:
```yaml
postgres:
  persistence:
    storageClass: longhorn        # (o longhorn-nvme)
```
```
helm upgrade galaxy deploy/helm -n $NS -f deploy/helm/values-local.yaml --atomic --set image.tag=<tag>
kubectl rollout status statefulset/$STS -n $NS --timeout=300s   # nuevo pod con PVC Longhorn (vacío)
```

**6) Restore.**
```
kubectl exec -i -n $NS $STS-0 -- sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < galaxy-*.sql
```

**7) Verificar.**
```
kubectl exec -n $NS $STS-0 -- sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"'   # tablas
kubectl get pvc $PVC -n $NS -o jsonpath='{.spec.storageClassName}{"\n"}'   # debe decir longhorn
kubectl get pod $STS-0 -n $NS -o wide   # nodo (puede ser cualquiera, ya no clavado a srv-t7910)
```

**8) Reanudar.**
```
kubectl patch cronjob galaxy-tick -n $NS -p '{"spec":{"suspend":false}}'
kubectl scale deploy/galaxy-api -n $NS --replicas=1
# smoke: /health 200, login, ver datos del jugador
```

**9) Limpieza (cuando esté todo verificado, días después).**
```
kubectl delete pv "$PV"     # libera el dato viejo retenido (local-path en srv-t7910)
```

## 5. Rollback
Si algo falla en el restore/verify:
- El **dump** (`galaxy-*.sql`) es la fuente; reintentar el restore.
- Último recurso: el **PV viejo retenido** (paso 3) tiene el dato local-path → recrear el PVC ligado a
  ese PV / revertir `storageClass` a `""` y reapuntar. Por eso el paso 3 es obligatorio.

## 6. Persistir el cambio (que no se revierta)
- Dejar `postgres.persistence.storageClass: longhorn` en `values-local.yaml` (ya gitignored) y, si se
  quiere por default en el chart, evaluar cambiar `values.yaml` (hoy `""`). 
- Quitar cualquier pin a `srv-t7910` (el chart usa `nodeSelector: {}` global → ya no fija; con
  Longhorn el pod puede ir a cualquier nodo).

## 7. Post-condición (lo que logra)
- Apagar/perder `srv-t7910` ⇒ **Postgres reagenda a otro nodo** (volumen Longhorn replicado) ⇒ el
  juego sigue; sólo la IA degrada a OpenRouter free (SDD 30). Downtime de reagende ~1-3 min, **sin
  pérdida de datos**.
- Para failover en **segundos** (sin reagende), el siguiente paso es **CNPG** (SDD 31).

## 7.bis Registro de ejecución (2026-06-24)
Ejecutado en prod con verificación previa (sin pérdida de datos):
1. Baseline: `players=10`, `tablas=22`, `alembic=916dc21e5905`.
2. `pg_dump` (87 KB) **verificado** (22 CREATE TABLE, COPY players, alembic_version, cierre).
3. **Dry-run**: restauré el dump en un **Postgres Longhorn descartable** (`pgtest`) → 10/22 OK
   **antes de tocar la base real**.
4. Migración: suspendí tick + API→0; PV viejo a `Retain`; borré STS+PVC; `helm` con
   `storageClass: longhorn` y API en 0; `DROP SCHEMA`+restore; verificado 10/22/head; API/tick arriba.
5. **Hallazgo CRÍTICO en el drill de resiliencia:** al borrar el pod de Postgres, el scheduler lo
   puso en **`srv-super6c-05` (nodo SIN Longhorn)** → `AttachVolume` falló (`node.longhorn.io ... not
   found`) → `ContainerCreating` colgado. **Causa:** con storageClass Longhorn, el pod **sólo** puede
   agendar en nodos que corren Longhorn (label `storage=rk1-longhorn`: los 4 RK1 + srv-t7910). **Fix:**
   `postgres.nodeSelector: {storage: rk1-longhorn}` agregado al chart (`datastores.yaml`/`values.yaml`).
6. **Drill OK tras el fix:** `cordon srv-t7910` + borrar pod → Postgres reagenda a **`srv-rk1-nvme-02`**
   (Longhorn RK1), Ready en ~40 s, **datos intactos (players=10)**. `/health` y `/public/online` OK.
- **Estado final:** Postgres en `storageClass=longhorn`, `nodeSelector=storage=rk1-longhorn`,
  corriendo en un RK1. Redes de seguridad: dump + PV viejo retenido (`pvc-b23ba706…`, Released/Retain).
- **Lección:** un PVC Longhorn **siempre** necesita `nodeSelector` a nodos Longhorn; si no, reagenda a
  un nodo sin Longhorn y cuelga. (Igual aplicaría a cualquier StatefulSet sobre Longhorn.)

## 8. Validación / tests
- **Drill en staging** antes de prod: correr este runbook end-to-end y luego `drain srv-t7910` →
  confirmar reagende de Postgres + juego OK + IA en nube.
- Verificar `storageClassName=longhorn` en el PVC nuevo y que el pod **no** quedó en srv-t7910.
