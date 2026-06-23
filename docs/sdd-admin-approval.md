# SDD 14 — Alta con aprobación de admin (invitación) + panel de admin

> **Estado:** propuesto (en cola) · **Fecha:** 2026-06-23 · **Autor:** equipo online-game
> **Relacionado:** [SDD 6 — Login email+OTP](sdd-auth-login.md) (el alta), [SDD 7 — Capacidad](sdd-capacity-autoscaling.md)
> y `deploy/gateway-tls/` (exposición/red), [SDD 12](sdd-player-metrics-public.md) (no filtrar email).

## 1. Objetivo

Que el alta de jugadores sea **moderada por el admin** (vos): una persona se registra y valida su
email con el código OTP (SDD 6), pero la cuenta queda **pendiente**; al admin le **llega un email**
con un link, hace clic, **se autentica** y **activa** la cuenta vía API. Todo desde un **panel de
admin**. Por ahora el panel/endpoints de admin son **solo de LAN** (estás en la misma red); el
diseño deja la puerta para **acceso remoto** seguro más adelante.

Cierra además un agujero actual: `/admin/*` (`tick`, `season/close`) hoy lo puede llamar
**cualquier jugador autenticado** — este SDD agrega el gate de admin real.

## 2. Estado actual (qué hay y qué falta)

- `verify_code` (SDD 6) crea el `Player` **activo de una** (signup=login). No hay estado de cuenta.
- `Player` tiene `email`, `is_npc`; **no** tiene `is_admin` ni `status` de cuenta.
- `app/api/v1/admin.py` usa `get_current_player` (cualquiera autenticado) → **sin gate de admin**.
- Mailer agnóstico ya existe (`app/services/mailer.py`: console/SMTP/Resend) — reutilizable para
  el aviso al admin.

## 3. Diseño

### 3.1 Ciclo de vida de la cuenta
Nuevo `Player.status`: **`pending` → `active`** (+ `suspended` para banear, `rejected` opcional).
- `verify_code` deja al jugador en `pending` (en vez de jugable de una). El JWT se puede emitir
  igual, pero el jugador **no puede onboardear/jugar** hasta `active`: los endpoints de juego
  rechazan `status != active` con un mensaje claro ("Tu cuenta espera aprobación del admin").
- Campos aditivos: `status` (default `active` para **no romper** cuentas/tests existentes — las
  nuevas altas por OTP nacen `pending`), `approved_at`, `approved_by` (id del admin).

### 3.2 Invitación (dos modos, data/config-driven)
- **Modo aprobación** (default, lo que pediste): cualquiera puede registrarse → queda `pending` →
  admin aprueba.
- **Modo invite-only** (opt-in `INVITE_ONLY=true`): solo se puede registrar quien tiene un
  **código/links de invitación** que el admin genera (tabla `Invite`: `code_hash`, `email_opcional`,
  `expires_at`, `used_by`). La validación OTP sigue igual; el invite gatea el `request-code`.
- Ambos terminan en el mismo gate de activación; arrancamos con **aprobación** e invite-only queda
  detrás de un flag.

### 3.3 Aviso al admin + link de activación
- Al quedar una cuenta `pending`, se **notifica al admin** (email vía mailer a `ADMIN_EMAIL`, y
  además una `Notification` in-app para el admin). El email trae un **link al panel** con el id del
  pendiente, p.ej. `https://<host>/admin?pending=<id>&t=<token-firmado>`.
- El `token-firmado` (HMAC + TTL, como el OTP) **identifica** la solicitud pero **no autoriza** por
  sí solo: al hacer clic, el panel **exige sesión de admin**; el token solo pre-rellena la UI
  (evita "click = activa" para cualquiera que tenga el link). La activación real es
  `POST /admin/players/{id}/approve` **con auth de admin**.

### 3.4 Autenticación del admin
- `Player.is_admin` (bool). Se **siembra** un admin inicial por env (`ADMIN_EMAIL`): al validar su
  OTP, ese email nace `is_admin=true` y `active`. Sin hardcodear credenciales.
- Dependencia `get_current_admin` (sobre `get_current_player` + `is_admin`), aplicada a **todo**
  `/api/v1/admin/*`. 403 si no es admin. Esto también blinda `tick`/`season/close`.
- Futuro remoto: agregar **2FA TOTP** para el admin y/o passkey antes de exponer fuera de la LAN.

### 3.5 Endpoints (full-API, e2e-testeable)
- `GET  /admin/players?status=pending` — lista de pendientes (con email, **solo admin**).
- `POST /admin/players/{id}/approve` — activa (`status=active`, `approved_at/by`, protección de
  novato SDD 11 al activar) + notifica al jugador.
- `POST /admin/players/{id}/reject` y `/suspend` — moderación.
- `POST /admin/invites` / `GET /admin/invites` — (modo invite-only) crear/listar invitaciones.
- Todos bajo `get_current_admin`. El panel web es un **cliente delgado** de estos endpoints
  (API-first), no mete lógica.

### 3.6 Exposición / red (tu pregunta: ¿expongo mucho?)
Riesgo real: un panel de admin público es superficie de ataque y maneja **PII (emails)**. Defensa
en capas, **LAN-only ahora**:
1. **No rutear `/admin/*` por el Gateway público.** El HTTPRoute público (SDD 7/`gateway-tls`)
   expone solo el juego; el admin se sirve por una ruta **interna** — opciones:
   - `kubectl port-forward` / `Service ClusterIP` (acceso solo desde la LAN/VPN), **o**
   - un HTTPRoute aparte en un hostname interno (`admin.<algo>.cluster.home`) en el listener
     `*.cluster.home` (no sale a internet), separado del hostname público.
2. **App-level allowlist** opt-in: `ADMIN_ALLOWED_CIDRS` (p.ej. `192.168.0.0/16`) chequeado en
   `get_current_admin`. Ojo: detrás de proxy TCP/SNI-passthrough hay que preservar la **IP de
   origen** (Cilium puede) o leer `X-Forwarded-For` confiable; si no es fiable, NO confiar en IP y
   apoyarse en (1) + auth.
3. **Auth fuerte + auditoría**: `is_admin` + (futuro) 2FA; **audit log** de toda acción de admin
   (quién aprobó/rechazó a quién, cuándo); rate-limit (patrón `core/redis.py`).
4. **Futuro remoto**: flip `admin.expose=true` → rutea `/admin` por el Gateway público **pero**
   exigiendo 2FA + allowlist + (ideal) mTLS o un proxy con SSO. Hasta entonces, **interno**.

## 4. Cómo afecta lo existente (extender, no romper)
- Migración aditiva (`status`/`is_admin`/`approved_*` con `server_default`). Cuentas viejas y los
  tests siguen `active`. Solo las altas nuevas por OTP nacen `pending`.
- `get_current_admin` cierra el gate de `/admin/*` (hoy abierto) — ajustar los tests que llaman
  `tick`/`season/close` para usar un admin.

## 4.bis Estado de implementación (2026-06-23) — v1 (variante simple: allowlist passwordless)
Por decisión del usuario, v1 NO trae panel/aprobación; usa el camino **más simple y rápido**:
- **Allowlist por env** `ALLOWED_EMAILS` (lista separada por coma; `config.allowed_email_set`).
  Vacío ⇒ registro abierto (comportamiento actual, no rompe nada). Cambiarla = redeploy/restart.
- **Gate en `request_code`** (`app/services/auth_otp.py`): si hay allowlist, solo emails
  autorizados —o jugadores ya existentes— reciben código. Salida **uniforme** (no envía pero
  responde igual) → no revela la lista (anti-enumeración). Sigue passwordless (no hay claves que
  repartir): el admin agrega el email y la persona entra con su código.
- Tests: `tests/test_auth_otp.py` (3 servicio: bloquea no-listado, permite listado, no bloquea a
  existente) + 1 e2e (`test_otp_allowlist_gates_signup`). Fixture autouse `_open_registration` en
  `conftest.py` aísla los tests del `.env` local. **162 unit/e2e verdes.**
- Operación: los emails reales van en `.env` (local) / `deploy/helm/values-local.yaml` (gitignored)
  / `--set`, **nunca** en `values.yaml` (repo público).

**Pendiente (este SDD completo, si se quiere más adelante):** `is_admin` + `get_current_admin`
(cerrar el gate abierto de `/admin/*`), estado de cuenta `pending`, panel de admin, aviso por
email + link, modo invite-only, 2FA para exposición remota.

## 5. Validación / tests (regla del proyecto)
- **Servicio**: `verify_code` deja `pending`; un jugador `pending` no puede onboardear; `approve`
  pasa a `active` y dispara protección de novato; `get_current_admin` rechaza no-admin (403).
- **E2E** (`tests/test_api_e2e.py`): flujo feliz (registro→pending→admin approve→puede jugar) +
  errores (no-admin a `/admin/*` = 403; jugar estando pending = 403/409; doble approve idempotente).
- **i18n** (SDD 4): textos del email al admin/jugador y mensajes de estado en ES/EN.
- **Seguridad**: el listado de pendientes solo lo ve el admin; los endpoints públicos (SDD 12)
  **siguen sin filtrar email**.

## 6. Riesgos / decisiones
- **Fricción del alta**: cada jugador necesita tu OK → bien para arranque privado/beta; si crece,
  podés flipear a auto-aprobar (`AUTO_APPROVE=true`) o a invite-only con cupo.
- **Exposición del admin**: la decisión es **LAN-only ahora** (no rutear afuera) + auth; remoto
  recién con 2FA/allowlist/mTLS. No exponer el panel "por comodidad".
- **IP de origen detrás del proxy**: no confiar en allowlist por IP si el passthrough no preserva
  la src IP; la barrera primaria es no-rutear-afuera + auth de admin.
- **Token del link**: identifica, no autoriza (evita activación por quien tenga el link).

## 7. Decisiones pendientes (tuyas)
- `ADMIN_EMAIL` (tu email de admin) y si querés **invite-only** desde el día 1 o solo aprobación.
- Acceso al panel ahora: ¿port-forward/ClusterIP, o hostname interno `*.cluster.home`?
- ¿2FA del admin ya, o cuando se exponga remoto?
