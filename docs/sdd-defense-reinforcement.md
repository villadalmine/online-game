# SDD 79 — Reforzar defensa (que no te goleen las colonias)

## Problema (recurrente del usuario)
El usuario pierde colonias porque una base queda **sin torretas** y no lo nota / le cuesta defenderla
(las torretas defienden SOLO su base, SDD 54). Preguntó incluso si "las torretas son solo aéreas" (NO:
suman defensa contra todo) y por qué #9 (orbital) tiene 🛡3 (porque no tiene torretas ahí).

## v1 (HECHO) — botón "Fortificar todas"
- **`bases.fortify_undefended(session, player)`**: construye una torreta en CADA base sin edificio
  defensivo activo, en UNA acción. Devuelve `{fortified:[base_ids], skipped:[{base_id,planet,reason}]}`.
  Reusa `start_build` → respeta requisitos y material; las que no puede (falta lab/tech/material) van a
  `skipped` con el motivo.
- **`POST /bases/fortify-all`** + botón **🔫 Fortificar todas las bases sin defensa (N)** en el panel
  🚨 Alertas (aparece cuando hay ≥1 base indefensa). El toast dice cuántas fortificó y cuáles no (motivo).
- Aclarado en el reporte de combate (SDD, ya vivo): torretas por base + aviso de goleada.

## Follow-ups (v2) — decisión de balance del usuario
- **Accesibilidad de la torreta**: hoy la torreta pide `research_lab` activo EN la base + tech `weapons`.
  Eso hace difícil defender bases chicas/orbitales (#9). Propuesta: que la torreta pida solo el HQ +
  `weapons` (una tech global) → podés fortificar cualquier base. Es cambio de balance (data-driven, 1
  línea) → confirmar con el usuario.
- **Defensa mínima por base**: un piso chico de defensa por base no frena un ataque grande (411 vs 3+piso)
  → poco útil; mejor la accesibilidad de la torreta.
- **Fortify que complete la cadena** (como el hack): si a la base le falta el lab, construirlo también.
