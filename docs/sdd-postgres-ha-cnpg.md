# SDD 31 — Postgres HA con CloudNativePG (CNPG) — opción "pro" (proyecto)

> **Estado:** **pendiente** (infra/proyecto, no urgente) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 30 mantenimiento/resiliencia](sdd-maintenance-resilience.md),
> [SDD 10 durabilidad/backup](sdd-durability-backup-restore.md), `deploy/helm/values.yaml`
> (`postgres.enabled`/`postgres.externalUrl`), repo `infra-ai/infra`.

## 1. Objetivo
HA **real** de Postgres: **primary + standby(s)** con streaming replication en **nodos distintos** y
**failover automático (segundos)**, en vez de depender de reagendar 1 instancia (SDD 30 opción A).
Cierra de paso los follow-ups de durabilidad (**backups + PITR a object storage**) de SDD 10.

## 2. Por qué CNPG
- **CloudNativePG** es el operador Postgres **k8s-native** moderno (CNCF): `Cluster` CR con N
  instancias, replicación, failover/switchover automático, rolling minor/major upgrades, **backups y
  PITR a S3-compatible** integrados, métricas Prometheus. Más simple/operable que Zalando (Patroni) o
  Bitnami HA para la mayoría de los casos.
- **No hay operador hoy** (juego/tenants/leloir son StatefulSets de 1 instancia) → instalarlo
  **estandariza** Postgres en todo el homelab.

## 3. Arquitectura
```
                CNPG operator (ns cnpg-system)
                        │ gestiona
   ┌────────────────────▼─────────────────────┐
   │ Cluster "galaxy-pg" (ns online-game)      │
   │  primary (nodo A) ──stream──> replica (B) │  + replica (C)  ← en RK1 distintos
   │  Services: galaxy-pg-rw (primary)         │
   │            galaxy-pg-ro (réplicas)        │
   └───────────────────────────────────────────┘
        backups + WAL → object storage (PITR)
juego → DATABASE_URL = postgres-rw Service (failover transparente)
```
- **Storage de cada instancia:** Longhorn (`longhorn-nvme`) en su nodo → réplica de datos a nivel
  Postgres **+** durabilidad del volumen. Anti-affinity → 1 instancia por nodo.
- **Failover:** si cae el primary (o su nodo), CNPG **promueve** una réplica y reapunta el Service
  `-rw`. El juego (conexión al `-rw`) reconecta solo.

## 4. Integración con el juego (cero código)
El chart ya soporta DB externa:
```yaml
# values-local.yaml
postgres:
  enabled: false                  # no desplegar el StatefulSet propio
  externalUrl: "postgresql+asyncpg://<user>:<pass>@galaxy-pg-rw.online-game.svc:5432/galaxy"
```
Las migraciones (initContainer `migrate`) corren igual contra el Service `-rw`. La credencial sale de
un Secret que genera CNPG.

## 5. Implementación (en `infra-ai`, idempotente — Ansible, como el resto)
1. **Operador:** rol `install-cnpg` → `helm`/manifests del operador CNPG (ns `cnpg-system`),
   ServiceMonitor para sus métricas. Target `make cnpg`.
2. **Cluster CR del juego:** `Cluster` `galaxy-pg` (3 instancias, `storageClass: longhorn-nvme`,
   anti-affinity por nodo, `monitoring.enablePodMonitor: true`).
3. **Backups/PITR:** `barmanObjectStore` apuntando a un bucket S3-compatible (MinIO local o externo) →
   base backups + WAL continuo → **restore a un punto en el tiempo**.
4. **Migrar datos** del Postgres actual (ver SDD 32 para el `pg_dump`/restore; acá el restore va al
   Cluster CNPG) → luego `postgres.enabled=false` + `externalUrl` al `-rw`.

## 6. Failover / mantenimiento
- **Apagar un nodo** (SDD 30): si tenía el primary → CNPG promueve réplica (~segundos) → juego sigue.
  Si tenía réplica → nada. **Cero ventana** para el juego.
- **Switchover planeado:** `kubectl cnpg promote` / drenar el nodo → CNPG mueve el primary antes.

## 7. Tests / drills
- **Failover drill (staging):** matar el pod primary → verificar promoción y que el juego sigue
  escribiendo (reconexión al `-rw`).
- **Restore drill (PITR):** restaurar a T-5min en un Cluster nuevo y validar datos.
- **Node drain:** `drain` del nodo del primary → promoción + juego OK.

## 8. Riesgos / decisiones
- **Complejidad:** un operador + CR + object storage para backups. Justificado si se quiere HA real y
  estandarizar Postgres del homelab; **overkill** si sólo se busca sobrevivir un apagado puntual
  (para eso, SDD 32 / Longhorn alcanza).
- **Recursos:** 3 instancias Postgres consumen más RAM/CPU/almacenamiento que 1.
- **Object storage:** PITR necesita un bucket; si no hay, quedarse con base backups (SDD 10).
- **Orden recomendado:** primero SDD 32 (Longhorn, rápido y suficiente); CNPG cuando se quiera el
  salto a HA real / multi-tenant Postgres.
