# SDD 48 — Concurrencia de acciones: no saturar la API al spamear (cola del cliente)

> **Estado:** **diseño** (no implementado) · **Fecha:** 2026-06-27
> **Relacionado:** SDD 1/2 (asistente), `app/api/deps.py` (`lock_current_player`),
> `app/core/redis.py` (`player_lock`), `app/services/{economy,training,research,market}.py`,
> `web/index.html` (acciones de UI).

## 1. Problema (reportado)
Si el jugador **clickea muchas veces** "comprar"/"construir"/"entrenar" muy rápido, la API responde
feo: **409 "Ya tenés una acción en curso, reintentá."** o, a veces, **500 internal error**. Queremos
**mitigar la saturación** sin romper la consistencia (sin doble-gasto), y decidir si conviene una
**cola de acciones** — sabiendo que una cola difiere la validación y una acción puede **fallar después
por falta de material** ("cómo se maneja eso").

## 2. Estado actual (verificado 2026-06-27)
- **Serialización por jugador (correcta):** las rutas mutantes usan `lock_current_player`
  (`deps.py`) → `player_lock` (Redis, `SET nx px=10s`). Si llega un **segundo** request del mismo
  jugador mientras el primero corre ⇒ **409**. Esto **evita doble-gasto** y es deseable.
- **El 500 aparece sin Redis (dev/SQLite):** `player_lock` **degrada a no-op** si Redis está ausente
  o falla (`yield True`). Entonces dos requests concurrentes del mismo jugador **corren en paralelo**
  sobre SQLite → `database is locked` / `IntegrityError` → **500**. En prod con Redis esto **no**
  pasa (da 409 limpio), pero el 500 sí se ve en local.
- **Modelo de recursos:** build/train/research **gastan los recursos al encolar** (no diferido): cada
  request valida y descuenta **en el momento**. → No hay "validación diferida" hoy; el problema es
  **concurrencia/UX**, no falta de cola.

## 3. Diagnóstico
Dos cosas distintas, dos arreglos distintos:
1. **UX de spam (lo principal):** el 409 es *correcto* pero se muestra como **error**. El usuario no
   debería ni generar el segundo request: la UI tiene que **bloquear el botón mientras hay uno en
   vuelo**.
2. **500 en dev:** falta serialización cuando no hay Redis. Hay que **serializar igual** (lock
   in-process) y **no devolver 500** ante errores transitorios de DB.

## 4. Diseño (en capas, de lo barato a lo pesado)

### 4.1 Frontend: deshabilitar la acción mientras está en vuelo (arreglo inmediato)
- Wrapper `submitAction(btn, fn)`: deshabilita el botón + spinner, `await fn()`, lo rehabilita en
  `finally`. **Ignora clicks** mientras hay uno en curso para esa acción. Mata el 90% de los
  dobles-disparos accidentales (clickear como loco). Cambio chico, sin server.
- Para acciones repetibles a propósito (comprar N veces): ver **cola del cliente** (§4.3).

### 4.2 Backend: serializar siempre + degradar elegante (saca el 500)
- **Lock in-process de respaldo:** cuando Redis no está, usar un `asyncio.Lock` por `player_id`
  (dict en memoria del proceso) para serializar dentro del worker. En dev (1 proceso) **elimina la
  carrera de SQLite**; en prod Redis sigue siendo el lock distribuido (multi-réplica).
- **409 en vez de 500 ante contención:** si igual hay colisión, devolver **409** (reintentable),
  nunca 500. Envolver las rutas mutantes para mapear `OperationalError("database is locked")` /
  `IntegrityError` transitorio → **409** con `Retry-After` corto.
- **Idempotencia opcional:** aceptar un header `Idempotency-Key` por acción → si llega repetido
  (doble submit), devolver el resultado previo en vez de re-ejecutar. (Útil para botones de pago/compra.)

### 4.3 Cola de acciones — **del lado del cliente** (recomendado), no del server
La forma simple de "encolar muchos clicks" **sin** los problemas de una cola server-side diferida:
- El cliente mantiene una **cola FIFO** y dispara los requests **de a uno** (`await` de cada uno
  antes del siguiente). Así nunca hay dos en vuelo → **nunca 409**, y el servidor valida cada acción
  **en el momento de enviarla** (no diferido).
- **"¿Y si no tenés material?"** → como cada acción se valida **al enviarse** (no al encolarse), si una
  falla por falta de recursos, **esa** muestra un toast de error claro ("faltan 20 de hierro") y la
  cola **sigue con las demás** (o se corta, configurable). El usuario ve exactamente cuál falló y por
  qué. Nada de "se gastó algo raro": el estado siempre refleja lo que sí se pudo hacer.
- La UI muestra la cola ("3 acciones en curso…") y permite cancelar las pendientes.
- **Por qué cliente y no server:** una cola server-side **diferida** reabre el problema que el usuario
  teme (validar tarde, fallar por material, estado intermedio raro) y agrega persistencia/worker. La
  cola del cliente da el mismo "puedo clickear muchas veces" con **validación inmediata y errores por
  acción**. Si en el futuro se quiere una cola server-side (p.ej. macros/automatización), se diseña
  como SDD aparte con **reserva de recursos al encolar** (no diferida).

## 5. Recomendación / orden
1. **4.1 (frontend disable-in-flight)** — arreglo inmediato del spam accidental.
2. **4.2 (lock in-process + 409 en vez de 500)** — saca el 500 de dev y endurece prod.
3. **4.3 (cola FIFO del cliente)** — para el caso "quiero hacer N seguidas a propósito", con errores
   por acción. Sin cola server-side diferida (evita el problema de validar tarde).

## 6. Tests / validación
- **Concurrencia:** dos requests mutantes simultáneos del mismo jugador ⇒ uno OK, el otro **409**
  (nunca 500), sin doble-gasto (e2e con `asyncio.gather`).
- **Sin Redis:** misma prueba con Redis deshabilitado ⇒ serializa (lock in-process), no 500.
- **Cola cliente:** N compras encoladas ⇒ se aplican en orden; si una no tiene material, esa falla con
  toast y las demás siguen (test de front / integración).
- **Idempotencia (si se hace):** mismo `Idempotency-Key` dos veces ⇒ un solo efecto.

## 7. Riesgos / decisiones
- **No romper la serialización:** el lock por jugador es lo que evita el doble-gasto; cualquier cambio
  debe mantenerlo (Redis en prod, in-process en dev).
- **No cola diferida server-side:** explícitamente descartada en v1 por el problema de validación
  tardía que el propio usuario señaló.
- **UX honesta:** un 409 nunca debe verse como "error" al usuario; es "esperá, ya estoy procesando".
