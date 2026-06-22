# SDD 6 — Login para producción (email + código OTP)

> **Estado:** propuesto · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Motivación:** dejar el login listo **antes de publicar**. Hoy es usuario+contraseña; para
> abrir al público queremos un login **passwordless por email + código** (OTP), más simple y
> seguro de operar (no guardamos contraseñas de usuarios casuales).

## 1. Contexto y estado actual

Hoy (`app/api/v1/auth.py` + `app/core/security.py`):
- `POST /auth/register` y `POST /auth/login` con **username + password** (PBKDF2-SHA256, stdlib).
- JWT HS256 (`create_access_token`/`decode_token`), `JWT_SECRET` por env.
- El modelo `Player` **no tiene email**.

Limitaciones para publicar: contraseñas de usuarios = superficie de soporte/seguridad
(reset, fugas), y no hay forma de contactar/recuperar la cuenta. Un **código por email** resuelve
identidad + recuperación con una sola primitiva.

## 2. Investigación: reuso de `bot-telegram`

`bot-telegram/src/otp.py` implementa OTP por email muy bien:
- **Código** de 6 dígitos con **CSPRNG** (`secrets.choice`, no `random`).
- Se guarda **HMAC-SHA256(code, salt)** (nunca en claro), con **TTL 10 min** y **máx intentos** (5).
- Verificación **constant-time** (`hmac.compare_digest`).
- **Respuestas uniformes** (no confirma si el identificador existe → anti-enumeración).
- Mailer agnóstico: **SMTP (aiosmtplib)** o **Resend (HTTP)**; valida email anti CRLF-injection.

**Qué reusamos:** el **patrón y los helpers puros** (generación CSPRNG, hash HMAC, TTL, intentos,
compare constant-time, validación de email, respuestas uniformes).
**Qué NO copiamos:** su persistencia (SQLite **crudo**) y su atadura a `dni`/`telegram_id`. El
juego usa **SQLAlchemy async** y la identidad es `Player`. Tampoco sumamos `aiosmtplib`
(dependencia nueva): mandamos email con **`smtplib` (stdlib)** o **Resend vía `httpx`** (ya es
dep), eligiendo por config — mismo espíritu "agnóstico + sin deps" del LLM.

## 3. Diseño

### 3.1 Identidad: email passwordless (primario)
- `Player` gana **`email`** (único, indexado, nullable para cuentas legacy). El `username` sigue
  existiendo (display name); para cuentas nuevas se puede derivar del email o pedirlo en el primer
  onboarding.
- **Login = pedir código + verificar**. No hay contraseña para cuentas nuevas. Las cuentas
  username+password actuales **siguen funcionando** (`/auth/login` legacy) — extender, no romper.

### 3.2 Flujo
```
POST /auth/request-code { email }
  → SIEMPRE 200 {"sent": true} (uniforme, no revela si el email existe)
  → genera OTP de 6 dígitos, guarda HMAC+TTL, manda el email (o lo loguea en dev)

POST /auth/verify-code { email, code }
  → 200 { access_token } si OK: crea el Player si es nuevo (signup = login), o entra si existe
  → 401 uniforme si inválido/expirado/sin pendiente; cuenta intentos; al 5º invalida
```
- **Registro y login son el mismo flujo**: si el email no tiene cuenta, verificar el código la
  crea (con onboarding pendiente). Menos fricción para publicar.

### 3.3 Modelo de datos (SQLAlchemy async)
- `Player.email: str | None` (unique, index).
- Tabla **`EmailOtp`**: `email PK`, `code_hash`, `attempts`, `expires_at`, `created_at`,
  `last_sent_at`. `email` como PK ⇒ pedir un código nuevo **reemplaza** el anterior (como el
  `INSERT OR REPLACE` del bot). Migración Alembic **aditiva** (con `server_default` donde haga
  falta; ojo SQLite, ver CLAUDE.md).

### 3.4 Servicio `app/services/auth_otp.py` (adaptado del patrón)
Helpers puros (portados/adaptados de `otp.py`): `generate_code()`, `hash_code(code)` =
HMAC-SHA256 con **`OTP_SECRET`** (env; fail-fast en prod), `verify(...)` con TTL + intentos +
`compare_digest`. Persistencia con la sesión async. Reusa `create_access_token` existente.

### 3.5 Envío de email (agnóstico, sin deps nuevas)
`app/services/mailer.py`:
- **Backends**: `MAIL_BACKEND` ∈ {`console`,`smtp`,`resend`}. Default **`console`** (loguea el
  código) para que **local/dev/tests funcionen sin SMTP** — igual patrón "fallback" del proyecto.
- `smtp`: `smtplib` stdlib (en `asyncio.to_thread`) con `SMTP_HOST/PORT/USER/PASSWORD/FROM/STARTTLS`.
- `resend`: POST a la API de Resend con `httpx` (ya es dep) usando `RESEND_API_KEY`.
- Validación de email anti CRLF-injection (regex del bot). Plantilla del código **i18n** (ES/EN,
  según `lang` del request / `Accept-Language` — reusa el criterio del SDD 4).

### 3.6 Rate limiting & abuso (clave para publicar)
- **`request-code`**: cooldown por email (p.ej. 60 s entre envíos) + tope por email/IP por hora.
  Reusar `app/core/redis.py:rate_limited` (degradable) y/o `last_sent_at` en `EmailOtp` (lazy, sin
  Redis). 
- **`verify-code`**: máx 5 intentos por código (lo trae el patrón) + tope por IP.
- **Respuestas uniformes y timing**: no distinguir "email no existe" de "código inválido";
  pequeño jitter opcional como en el bot.

### 3.7 Relación con Telegram (SDD 5) y JWT
- El mismo `Player.email`/JWT sirve para todos los clientes. El bot de Telegram puede vincular con
  un **código emitido por este flujo** (en vez de `/login user pass` en el chat) → más seguro.
- JWT sin cambios; antes de publicar: **`JWT_SECRET` fuerte** y **`OTP_SECRET`** fuerte (Secret en
  Helm, nunca al repo).

## 4. API (full-API, versionada)
```
POST /api/v1/auth/request-code   { email }                  -> 200 {sent:true}   (uniforme)
POST /api/v1/auth/verify-code    { email, code }            -> 200 {access_token} | 401
POST /api/v1/auth/login          { username, password }     -> legacy, se mantiene
```
`/auth/register` (password) queda **deprecado** para público (se puede gatear con un flag), pero no
se elimina (extender, no romper; útil para tests/NPC/CLI).

## 5. Plan de tests (regla del proyecto)
**Servicio** (`tests/test_auth_otp.py`): genera código (6 díg, CSPRNG), `verify` ok/expirado/
inválido/max-intentos/sin-pendiente; hash nunca en claro; `MAIL_BACKEND=console` captura el código.
**E2E** (`tests/test_api_e2e.py`): `request-code` siempre 200 (email existente o no);
`verify-code` con el código capturado en consola → token y crea Player; código malo → 401;
cooldown/rate-limit → 429; el JWT abre `/players/me`.
**i18n**: el email respeta `lang`.

## 6. Riesgos / decisiones
- **Entrega real de email** necesita SMTP/Resend reales → se verifica en deploy; en CI va
  `console`. (Como el token de Telegram, el smoke real lo hace el operador.)
- **Migración de cuentas password→email**: opcional, no bloqueante; conviven.
- **Enumeración/abuso**: mitigado con respuestas uniformes + rate-limit + TTL + intentos.
- **Sin deps nuevas**: `smtplib`/`httpx`/`hmac`/`secrets` ya disponibles.

## 6.bis Decisiones e implementación (2026-06-22)

**Decisiones del usuario:**
- **Modelo: passwordless (código siempre).** Cada login nuevo manda un código; el **JWT mantiene
  la sesión** (`jwt_expire_minutes`, ~7 días) → no pide código en cada visita, solo cuando no hay
  token válido (dispositivo nuevo, expirado, logout). No es "solo el primer login".
- **Dev/testing: no se fuerza OTP.** Se mantiene el login **usuario+contraseña** (`/auth/login`,
  `/auth/register`) para dev/CLI/tests/NPC, y `MAIL_BACKEND=console` loguea el código local (sin
  SMTP). No se agregó "código fijo" (se descartó para no arrastrar un bypass a prod).

**Implementado:**
- `Player.email` (unique, nullable) + tabla `EmailOtp` (email PK) + migración aditiva.
- `app/services/auth_otp.py`: `generate_code` (CSPRNG), `hash_code` (HMAC-SHA256 con `OTP_SECRET`),
  `request_code` (uniforme + cooldown por `last_sent_at`), `verify_code` (TTL + intentos +
  `compare_digest`; **signup = login**: crea el `Player` si el email es nuevo, con contraseña
  inutilizable). Errores **uniformes 401** (anti-enumeración); email inválido → 422.
- `app/services/mailer.py`: backends `console` (default) / `smtp` (stdlib) / `resend` (httpx),
  validación anti CRLF. Email del código **i18n** (ES/EN por `?lang`/`Accept-Language`).
- Endpoints `POST /auth/request-code`, `POST /auth/verify-code` (`app/api/v1/auth.py`).
- Web: en la card de login, sección "Entrar con email (sin contraseña)" (pedir código → verificar).
- Config (`OTP_SECRET`, `OTP_TTL_MINUTES`, `OTP_MAX_ATTEMPTS`, `OTP_RESEND_COOLDOWN_SECONDS`,
  `MAIL_BACKEND`, `SMTP_*`, `RESEND_API_KEY`, `MAIL_FROM`).
- Tests: `tests/test_auth_otp.py` (7 servicio) + 3 e2e + 1 browser.

**Pendiente (follow-up):** rate-limit por IP (hoy hay cooldown por email); entrega real de email
en deploy (SMTP/Resend); `OTP_SECRET` fuerte como Secret en Helm; vincular Telegram con código
emitido por este flujo (SDD 5).

## 7. Checklist pre-publicación (gating)
- [ ] `JWT_SECRET` y `OTP_SECRET` fuertes (Secret), no defaults.
- [ ] `MAIL_BACKEND` real (smtp/resend) configurado y probado (smoke).
- [ ] Rate-limit de `request-code`/`verify-code` activos (Redis recomendado en prod).
- [ ] HTTPS/TLS en el borde (ver SDD de "Deploy online real").
- [ ] Política de expiración de JWT revisada (`jwt_expire_minutes`).
