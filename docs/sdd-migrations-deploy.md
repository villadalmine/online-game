# SDD 16 — Migraciones de base de datos en build/deploy (qué pasa al rebuild/upgrade)

> **Estado:** implementado (describe el comportamiento vigente) · **Fecha:** 2026-06-23
> **Relacionado:** `migrations/`, `app/core/db.py:run_migrations`, `deploy/helm/templates/api.yaml`
> (initContainer `migrate`), [SDD 10 durabilidad](sdd-durability-backup-restore.md),
> [SDD 15 build Kaniko](sdd-image-build-kaniko.md).

## 1. Objetivo

Dejar claro **cómo se aplican las migraciones** cuando rebuildeás la imagen y hacés `helm upgrade`,
y qué pasa **si el esquema cambió** vs. **si no cambió nada**. Regla de oro: **los datos no se
pierden** — las migraciones son aditivas y se aplican solas; el PVC de Postgres persiste (SDD 10).

## 2. Cómo se aplican hoy (dos capas, idempotentes)

1. **initContainer `migrate`** en el Deployment de la API (`deploy/helm/templates/api.yaml`):
   corre **`alembic upgrade head`** ANTES de que el pod nuevo sirva tráfico. Reintenta (restart del
   pod) hasta que Postgres responde. Es el punto de verdad en k8s.
2. **`run_migrations()` en el lifespan** de la app (`app/core/db.py`): también aplica `upgrade head`
   al arrancar (cubre dev/local y es red de seguridad).

Ambas son **idempotentes**: si ya está en `head`, son **no-op**. Las migraciones viajan **dentro de
la imagen** (el `Dockerfile` hace `COPY migrations ./migrations`), así que la imagen y su esquema van
siempre juntos.

## 3. Flujo según el caso

### A) Cambiaste modelos (hay esquema nuevo)
1. Editás `app/models/…`.
2. Generás la migración: **`make migration m="descripcion"`** → crea un archivo en
   `migrations/versions/`. **Revisalo** (SQLite: columnas `NOT NULL` nuevas necesitan
   `server_default`; FKs en `batch_alter_table` necesitan nombre — ver SDD/CLAUDE.md).
3. **Commit + push** del modelo **y** la migración juntos.
4. **Rebuild de imagen** (SDD 15) con un tag nuevo → la migración queda dentro de la imagen.
5. **`helm upgrade --set image.tag=<nuevo>`**: el initContainer corre `alembic upgrade head` →
   **aplica solo las migraciones pendientes** sobre la DB existente. **No borra datos.** Recién
   después arrancan los pods nuevos.
6. Hay un test (`tests/test_migrations.py`) que falla si una migración no crea todas las tablas del
   modelo → no se te escapa una migración faltante.

### B) No cambiaste el esquema (solo código)
- No generás migración. Rebuild + `helm upgrade`: el initContainer corre `alembic upgrade head` y es
  **no-op** (ya está en head). Solo rola los pods con el código nuevo. DB intacta.

### C) `helm upgrade` de imagen nueva SIN migraciones nuevas
- Igual que (B): no pasa nada con la DB. El `upgrade head` no encuentra revisiones pendientes.

## 4. Orden y seguridad en el rollout

- El initContainer corre **antes** del contenedor de la API → no hay pods sirviendo con un esquema
  que todavía no migró.
- **Migraciones aditivas (expand/contract)**: para no romper durante el rolling update (conviven pod
  viejo y nuevo unos segundos), preferí cambios **compatibles hacia atrás** (agregar columnas
  nullable / con `server_default`; renombrar en dos pasos). Evitá `DROP`/`NOT NULL` duro en el mismo
  release que despliega el código que aún no lo usa.
- **Réplicas**: aunque haya varias réplicas de la API, todas corren el mismo initContainer; Alembic
  toma el lock de versión → no hay doble aplicación.

## 5. Rollback

- **Datos**: el PVC de Postgres persiste (SDD 10); volver la imagen atrás **no** borra datos.
- **Esquema**: Alembic **no** hace downgrade automático. Si volvés a una imagen vieja cuyo código
  espera un esquema anterior, puede romper si la migración fue destructiva. Por eso (4) recomienda
  migraciones expand/contract: el código viejo sigue funcionando con el esquema nuevo.
- Downgrade manual (excepcional): `alembic downgrade <rev>` (con backup previo — SDD 10).

## 6. Dev vs prod

- **Dev (SQLite)**: `run_migrations()` al arrancar (`make run`) aplica todo solo; `make db-reset`
  solo si querés empezar de cero. Tests usan `init_models()` (crean tablas directo, sin Alembic).
- **Prod (Postgres)**: el initContainer es el camino; nunca `db-reset`. Backup antes de releases con
  migraciones grandes (SDD 10).

## 7. Checklist al publicar un release con cambios de modelo
1. `make migration m="…"` + revisar el archivo. 2. `make test` (incluye `test_migrations`).
3. Commit+push modelo+migración. 4. Rebuild imagen (SDD 15) con tag nuevo. 5. `helm upgrade
--set image.tag=`. 6. Verificar `kubectl logs` del initContainer `migrate` (aplicó / no-op).
