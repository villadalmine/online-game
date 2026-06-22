# SDD 10 — Durabilidad: que un pod muera y nadie pierda datos (backup / restore)

> **Estado:** propuesto · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Relacionado:** [SDD 7 — Capacidad](sdd-capacity-autoscaling.md), `deploy/helm/templates/`.
> **🔴 Hallazgo bloqueante para publicar:** el Postgres del chart **no tiene volumen persistente**.

## 1. Objetivo

Garantizar que **si un pod muere, los jugadores no pierden datos**, y definir **backup + restore**
(con RPO/RTO claros y un runbook probado) antes de abrir al público.

## 2. Cómo es hoy (qué ya está bien y qué está roto)

**Ya es crash-safe a nivel app (bien):**
- La **API es stateless**: el estado no vive en memoria del pod. Si una réplica muere, otra atiende.
- **Estado lazy por timestamp** (`services/state.py:advance`): energía/producción/colas se
  **reconstruyen** desde `*_updated_at` al leer. Un pod que muere a mitad de cálculo no corrompe
  nada: nada se "perdió", se recalcula en la próxima lectura.
- **Transacciones atómicas**: cada acción hace `commit` (build/train/tick/advance). Un crash a
  mitad de request pierde solo **esa** transacción no confirmada → el usuario reintenta. Sin estado
  parcial.
- **Redis es cache reconstruible** (catálogo, rate-limit): si se cae, se degrada y se repuebla. No
  es fuente de verdad.
- **NPC memory** y todo lo demás viven en columnas de la DB, no en RAM.

⇒ La durabilidad depende **enteramente de Postgres**. Y ahí está el problema:

**🔴 Roto (data loss real):** `deploy/helm/templates/datastores.yaml` corre Postgres como un
**`Deployment` sin `PersistentVolumeClaim`** ni `volumeMounts`. `PGDATA` queda en el **filesystem
efímero del contenedor** → si el pod se reinicia/reprograma, **se pierde toda la base**. Idem Redis
(menos grave: es cache). **Esto hay que arreglarlo sí o sí antes de publicar.**

## 3. Diseño

### 3.1 Persistencia de Postgres (el fix base)
Dos caminos (elegir según destino del deploy):
- **A) In-chart, con estado real**: convertir el Postgres a **`StatefulSet` con
  `volumeClaimTemplates`** (PVC, `storageClassName`, tamaño configurable) montado en
  `/var/lib/postgresql/data`. `replicas: 1` (un escritor). Simple y suficiente para empezar.
- **B) Postgres gestionado/operador** (recomendado para prod seria): **CloudNativePG** o el
  operador de Zalando, o un Postgres **managed** del proveedor. Te da PVC + **PITR + réplicas +
  failover** casi gratis. El chart del juego solo necesita `DATABASE_URL` apuntando ahí
  (`postgres.enabled=false`).

Decisión: **values.postgres.persistence** (enabled/size/storageClass) para el camino A; y soportar
**`postgres.enabled=false` + `DATABASE_URL` externo** para el camino B. Aditivo, no rompe dev/SQLite.

### 3.2 Backups
- **Lógico (base, simple)**: **CronJob** `pg_dump` (formato `custom`/`-Fc`) cada N horas →
  **almacenamiento offsite** (S3/MinIO/bucket), **cifrado** y con **retención** (p.ej. 7 diarios +
  4 semanales). Knobs en values: `backup.enabled/schedule/retention/destination`.
- **PITR (RPO bajo, opcional)**: WAL archiving continuo (vía operador del 3.1-B o `wal-g`/`pgBackRest`)
  → recuperar a un punto en el tiempo (minutos de RPO) en vez de a la última foto.
- **Dev (SQLite)**: la "base" es `game.db` (archivo, ignorado por git). Backup = copiar el archivo;
  no aplica a prod.

### 3.3 Restore (runbook, no improvisar)
Documentar y **probar** en `docs/RUNBOOK` (o sección del README de deploy):
1. Escalar la API a 0 (o modo mantenimiento) para que no escriba.
2. Restaurar el dump: `pg_restore -Fc --clean --if-exists -d $DATABASE_URL backup.dump` (o PITR al
   timestamp objetivo con el operador/`wal-g`).
3. Verificar: `tests/test_migrations.py` (esquema completo) + smoke `GET /players/me` de una cuenta.
4. Reabrir la API.
- **Migraciones**: se aplican solas al arrancar (`run_migrations`). Política: **backup ANTES de
  cada deploy** que traiga migración (la migración es el momento más riesgoso). Las migraciones ya
  son aditivas (extender, no romper), lo que facilita el rollback.

### 3.4 Objetivos (acordar)
- **RPO** (cuánto se puede perder): con solo `pg_dump` cada 6 h ⇒ hasta 6 h. Con PITR ⇒ minutos.
- **RTO** (cuánto tarda volver): restore de dump = minutos–decenas según tamaño; documentado y
  cronometrado en el drill.
- Backups **offsite** y **cifrados**; el bucket no en el mismo dominio de falla que el cluster.

## 4. Resiliencia operativa (complementos)
- **PodDisruptionBudget** + readiness (ya hay) para que un drain no tire todo a la vez (ver SDD 7).
- Postgres: `PersistentVolume` con `Retain` reclaim policy (no borrar el disco al borrar el PVC).
- **Probar de verdad**: *chaos drill* — matar el pod de Postgres y confirmar que **con PVC** los
  datos siguen; sin PVC se pierden (demuestra el fix). Restore drill periódico (un backup que no se
  probó restaurar **no es** un backup).

## 5. Plan de tests / verificación (regla del proyecto)
- **App crash-safety (automatizable)**: e2e que (a) hace una acción y commitea, (b) **descarta la
  sesión / reinstancia** el app contra la **misma** DB, (c) `GET /players/me` devuelve el estado →
  prueba que nada vive en memoria del proceso. (Ya tenemos el patrón de manipular la DB por
  `client.session_maker` en `tests/test_api_e2e.py`.)
- **Helm**: `helm template` con `postgres.persistence.enabled=true` rinde un `StatefulSet` con
  `volumeClaimTemplates`; con `postgres.enabled=false` no rinde Postgres y usa `DATABASE_URL`.
- **Backup/restore**: script de drill en `tests/ops/` (manual, no CI): dump → drop → restore →
  `test_migrations` + smoke. Cronometrar RTO.

## 5.bis Estado de implementación (2026-06-22)

**Hecho (este commit):**
- 🟢 **Postgres con persistencia**: pasó de `Deployment` sin volumen a **`StatefulSet` con
  `volumeClaimTemplates` (PVC)** montado en `/var/lib/postgresql/data`, con `PGDATA` en el subdir
  `…/pgdata` (evita el problema de `lost+found` en PVs nuevos) + `readinessProbe` con `pg_isready`.
  El **PVC sobrevive a que el pod muera/reprograme** → fin del data-loss. (`datastores.yaml`)
- 🟢 **Knobs** (`values.yaml`): `postgres.persistence.{enabled,size,storageClass}`
  (default `enabled:true`, `8Gi`, StorageClass default). `persistence.enabled=false` → `emptyDir`
  (solo pruebas).
- 🟢 **Postgres externo** (managed/operador): `postgres.externalUrl` + `postgres.enabled=false`;
  `dbUrl` lo honra (`_helpers.tpl`). Camino recomendado para PITR/failover (CloudNativePG, etc.).
- 🟢 **Backup opt-in**: `backup.enabled` → **CronJob `pg_dump -Fc`** a un **PVC** con **retención**
  por días (`postgres-backup-cronjob.yaml`, `values.backup.*`, default off).
- ✅ Verificado con `helm lint` + `helm template` en 4 escenarios (persistente / `emptyDir` / DB
  externa / backup on).

**Pendiente (follow-up, documentado):**
- 🟡 Backup **offsite + cifrado** (hoy el dump queda en un PVC local del cluster) → subir a object
  storage (S3/MinIO) con credenciales en Secret.
- 🟡 **PITR / WAL archiving** y réplica/failover → vía operador (camino 3.1-B).
- 🟡 **Runbook de restore** versionado + **restore drill** periódico cronometrado (RTO).
- 🟡 `PersistentVolume` reclaim `Retain` (depende de la StorageClass del cluster).

## 6. Riesgos / decisiones
- **Sin PVC = pérdida total**: es el riesgo #1; el resto del SDD no sirve sin esto.
- **Un solo Postgres** (un escritor) = SPOF de escritura. Mitiga el operador (3.1-B) con
  réplica/failover; para empezar, PVC + backups + restore probado es aceptable.
- **Backups sin probar**: política de restore drill obligatoria.
- **Redis**: efímero está OK (cache); no backupear, solo asegurar degradación (ya soportada).
- **Secretos** (`JWT_SECRET`/DB pass) fuera del backup de datos y versionados aparte (ver SDD 6).
