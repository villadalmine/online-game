# SDD 20 — Usuarios: qué es un usuario, qué campos tiene, identidad y privacidad

> **Estado:** propuesto (documenta el modelo vigente + reglas) · **Fecha:** 2026-06-23
> **Relacionado:** `app/models/__init__.py` (`Player`), [SDD 6 login OTP](sdd-auth-login.md),
> [SDD 14 allowlist/admin](sdd-admin-approval.md), [SDD 12 métricas/showcase](sdd-player-metrics-public.md).

## 1. Objetivo

Definir **qué es un usuario** en el juego, **qué campos** tiene y la **regla de identidad/privacidad**:
el usuario **entra por email** (login), pero **lo que se muestra es su nickname (username)** — el
email **nunca** se expone a otros jugadores.

## 2. Modelo `Player` (campos actuales)

| Campo | Tipo | Para qué |
|---|---|---|
| `id` | int PK | identificador interno (no se expone como identidad pública) |
| `username` | str único | **nickname público** — lo que ven los demás (ranking, alianzas, combate) |
| `password_hash` | str | login usuario+contraseña (dev/registro); en OTP es inutilizable |
| `email` | str único, nullable | **login** (OTP / registro invitado). **PRIVADO**: nunca a terceros |
| `is_npc` | bool | NPC controlado por IA |
| `is_admin` | bool | gate de `/admin/*` (SDD 14 v2); se siembra desde `ADMIN_EMAIL` |
| `galaxy_key`/`planet_key`/`race_key` | str nullable | onboarding (dónde y qué raza) |
| `galaxy_instance_id` | FK nullable | shard/instancia de galaxia (SDD 8) |
| `energy`/`energy_updated_at` | float/ts | energía lazy por timestamp |
| `protected_until` | ts nullable | escudo de novato (SDD 11) |
| `alliance_id` | FK nullable | una alianza a la vez |
| `assistant_hacks_used`/`_reset_at` | int/ts | presupuesto del asistente (SDD 2) |
| `created_at` | ts | alta |
| memoria NPC (JSON) | str | acciones recientes (solo NPC) |
| **PlayerStats** (tabla aparte) | — | contadores de por vida (SDD 12): batallas, construido, etc. |

## 3. Identidad pública vs. privada (regla central)

- **Identidad pública = `username` (nickname).** Todo lo que ve otro jugador o el público usa
  `username`: ranking, alianzas, combate, `/public/*` (SDD 12), showcase del login.
- **`email` es privado**: se usa solo para **autenticar** (OTP / registro invitado) y para el admin.
  **No** aparece en ningún endpoint hacia terceros. `/players/me` puede devolver el email **del
  propio** usuario (es suyo), nunca el de otros.
- **Regla de oro**: ningún payload público/agregado incluye `email` (ya garantizado en SDD 12).

## 4. Hueco a corregir (follow-up importante)

Hoy, en el **signup por OTP**, el `username` se deriva del **local-part del email**
(`_unique_username`: `nombre.apellido@correo.com` → `nombreapellido`). Eso **insinúa el email** en el
nickname público → contradice §3.
- **HECHO (2026-06-23)**: el alta por OTP genera un nick **neutro** (`comandante-<hex>`), ya **no
  deriva del email** (`auth_otp._unique_username`). Test `test_otp_username_is_neutral_not_from_email`.
- **Pendiente (follow-up)**: `PATCH /players/me/username` para que el usuario se renombre. Ojo: el
  JWT lleva `sub=username` → al renombrar hay que **re-emitir el token** (y actualizarlo en el
  cliente) o pasar el JWT a usar `player.id`. Por eso quedó para un cambio supervisado (toca auth+web).
- En el **registro invitado** (usuario+contraseña+email) el usuario **ya elige** username → ahí no
  hay leak; el problema es solo el camino OTP.

## 5. Ciclo de vida

- **Alta**: por **email invitado** (allowlist, SDD 14) — registro con username+password+email, o OTP
  (código por email). Sin allowlist (dev) el registro es abierto.
- **Sesión**: JWT (`sub = username`). El email no viaja en el token.
- **Roles**: `is_admin` (gate admin). Futuro: roles más finos / moderación (SDD 14 v2).
- **Baja/ban**: hoy no hay; follow-up (estado `suspended` en SDD 14 v2).

## 6. Validación / tests
- El email del usuario **propio** se ve en `/players/me`; **nunca** en `/players` ni `/public/*`
  (test que falle si aparece `email` en esos payloads).
- Unicidad de `username` y `email`; el cambio de nickname (si se implementa) valida unicidad.
- i18n de los textos de cuenta (SDD 4).

## 7. Follow-up
- Nickname editable + alta OTP con nickname neutro (no derivar del email). Avatares/perfil público
  (reusa `/public/players/{username}` de SDD 12). Roles/moderación (SDD 14 v2).
