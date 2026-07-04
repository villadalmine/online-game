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

## v2 (HECHO) — el fortify ARMA LA CADENA (decisión del usuario)
- El usuario eligió: mantener el requisito de la torreta pero que "fortificar todas" **construya el lab
  que falte y después la torreta**, como el hack. `fortify_undefended` ahora, por cada base indefensa:
  arma `_requires_chain("turret")` (= `[research_lab]`), construye los prereqs que falten y los deja
  **ACTIVOS al instante**, y después la torreta. Si falta la tech `weapons` o material → va a `skipped`
  con el motivo (la tech es una decisión deliberada, no se auto-investiga). Así defendés cualquier base
  (incluida #9 orbital) de un clic, pagando el material.

## Follow-ups
- Auto-investigar `weapons` desde el fortify (hoy no; se reporta como skip).
- Defensa por soldados (garrison) para bases donde no conviene lab+torreta.
