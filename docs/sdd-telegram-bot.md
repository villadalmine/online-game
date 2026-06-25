# SDD 5 — Bot de Telegram (otro cliente sobre la misma API)

> **Estado:** **bloqueado** — necesita un TELEGRAM_BOT_TOKEN real
> verificar) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Ámbito:** un cliente nuevo, **consumidor delgado de `/api/v1`**. Sin reglas de juego nuevas.

## 1. Objetivo

Jugar y recibir notificaciones desde **Telegram**, cerrando la premisa multi-cliente (web + CLI
+ Telegram, todos sobre el mismo backend). El bot **no implementa lógica de juego**: traduce
mensajes de Telegram a llamadas HTTP a la API existente.

### Restricciones (del proyecto)
- **Sin dependencias nuevas / instalador único**: se habla con la **Bot API de Telegram por HTTP
  con `httpx`** (que ya usamos), por **long-polling** (`getUpdates`). Nada de `python-telegram-bot`.
- **Opt-in**: corre solo si hay `TELEGRAM_BOT_TOKEN`; sin token, no arranca (como el LLM).
- **API-first**: el bot llama a `/api/v1/...`; cero acceso directo a la DB.

## 2. Arquitectura

```
Telegram  ──getUpdates(long-poll)──>  app/services/telegram.py  ──httpx──>  /api/v1/* (mismo server)
          <──sendMessage────────────         (loop opt-in en el lifespan, como AUTO_TICK)
```

- **Transporte**: helpers `tg_get_updates(offset)` y `tg_send(chat_id, text)` sobre
  `https://api.telegram.org/bot<TOKEN>/...` con `httpx` (timeout largo para el long-poll).
- **Loop**: una tarea en el `lifespan` (igual que `AUTO_TICK_SECONDS`) que hace long-poll y
  despacha cada update a un **router de comandos**. Se activa solo con token presente.
- **Identidad**: un mapa `telegram_chat_id -> player` para no re-loguear en cada mensaje. Tabla
  nueva `TelegramLink(chat_id PK, player_id FK, token)` o reuso del JWT guardado por chat. El
  vínculo se crea con `/login <usuario> <password>` (o un `/link <token>` generado en la web).
- **Llamadas a la API**: el bot guarda el JWT del jugador por `chat_id` y lo manda como `Bearer`
  a los endpoints existentes (no hay API nueva salvo, opcional, generar un token de vínculo).

## 3. Comandos (v1)

| Comando | Llama a | Resultado |
|---|---|---|
| `/start` | — | ayuda + cómo vincularse |
| `/login <user> <pass>` | `POST /auth/login` | guarda el JWT para ese chat |
| `/me` | `GET /players/me` | energía, minerales, unidades, colas |
| `/build <edificio> [mineral]` | `POST /bases/{id}/build` | encola construcción |
| `/train <unidad> <n>` | `POST /bases/{id}/train` | entrena |
| `/attack <base> <fuerza>` | `POST /combat/attack` | lanza flota |
| `/research <tech>` | `POST /research` | investiga |
| `/help` | — | lista de comandos |

Idioma: respeta `lang` del jugador / `/lang en|es` (reusa el catálogo localizado del SDD 4).

## 4. Notificaciones push
El bot puede **empujar** notificaciones a Telegram: un consumidor que, por cada jugador vinculado,
sigue su feed (`GET /notifications?unread=true` o el SSE interno) y manda `sendMessage`, marcando
leídas. v1 simple: poll cada N s junto al loop de updates. (Mismo contenido que la web/SSE.)

## 5. Config (Helm + .env)
- `TELEGRAM_BOT_TOKEN` (Secret), `TELEGRAM_ENABLED` (default off), `TELEGRAM_POLL_SECONDS`.
- En Helm: knob `telegram.botToken` → Secret, igual patrón que `llm.apiKey`. El chart **no**
  levanta nada externo; solo pasa el token.

## 6. Plan de tests (regla del proyecto)
Como no podemos hablar con Telegram real en CI, se testea el **router de comandos** con el
transporte **mockeado** (igual que el LLM): inyectar un fake de `tg_send`/`tg_get_updates`.
- `/login` ok → guarda sesión; credenciales inválidas → mensaje de error.
- `/me` tras login → texto con energía/minerales (mockear la API o usar el client e2e in-process).
- `/build` inválido → propaga el error 4xx como texto claro.
- parsing de comandos (args faltantes → ayuda).
- (e2e) si se expone `/auth/link-token`, su happy path + error en `tests/test_api_e2e.py`.

## 7. Riesgos / decisiones
- **Verificación real**: requiere un `TELEGRAM_BOT_TOKEN` (de @BotFather). La lógica se prueba con
  mocks; el smoke real lo hace el usuario con su token. **Por eso la implementación está bloqueada
  hasta tener token.**
- **Long-poll vs webhook**: v1 long-poll (simple, sin exponer URL pública). Webhook = follow-up
  cuando haya deploy con TLS (ver SDD de "Deploy online real").
- **Una sola réplica** debe correr el loop (como el AUTO_TICK); en multi-réplica, separar en un
  proceso/worker dedicado.
- **Seguridad**: el JWT por chat vive en memoria/DB del server; `/login` por chat es cómodo pero
  expone credenciales en el historial de Telegram → preferir `/link <token>` generado en la web.
