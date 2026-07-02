# SDD 68 — Vista del planeta: zoom a un mundo, tus bases siempre, las enemigas solo si escaneaste

> **Estado:** **IMPLEMENTADO** 2026-07-02 (1.134.0, front): el modal de planeta (`openPlanet`) suma la
> visibilidad SATELITAL — por cada rival del planeta muestra 📡 % escaneado + bases/unidades (de
> `enemy_maps`, SDD 61) o 🌫 niebla si no lo mapeaste. · **Pedido:** usuario, 2026-07-02.
> **Relacionado:** [SDD 61 satélites](sdd-satellites-recon.md) (mapeo → `enemy_maps` con bases+unidades),
> [SDD 35 espionaje](sdd-espionage.md) (intel puntual), [SDD 60 paneles por planeta](sdd-collapsible-planet-panels.md),
> [SDD 43 pictográfico](sdd-play-without-reading.md), `web/index.html` (`renderMap`/`openPlanet`).

## 1. Pedido (usuario, 2026-07-02)
Una **vista del planeta**: al hacer **zoom** sobre un mundo se abre una **ventana** que muestra las
bases que hay ahí. **Lo que ves depende de tu intel:**
- **Tu planeta / tus bases:** siempre visibles (con su estado: edificios, vida, etc.).
- **Un planeta enemigo:** solo lo ves si lo **escaneaste con satélites** (SDD 61). Si no, en ese planeta
  solo ves **tu** base (o nada del rival) — niebla de guerra.

## 2. Diseño (front, reusa datos existentes)
- **Modal "planeta"** (extender `openPlanet(planet_key)` que ya existe): al hacer click/zoom en un
  planeta del mapa (🌌 Galaxias) se abre con:
  - **Tus bases en ese planeta** (de `state.bases`): edificios (agrupados, con condición SDD 66),
    medidores, defensas — ya lo tenemos por-planeta (SDD 60), reusar.
  - **Bases enemigas en ese planeta:** de `enemy_maps` (satélites). Se listan las bases de cada rival
    de ESE planeta con su **% descubierto**; con 100% se ven las unidades por base (ya viene en
    `enemy_maps[tid].bases`). Sin mapeo (pct=0) → "🌫 sin datos — mandá un satélite espía".
- **Niebla:** un rival del planeta que no mapeaste no aparece (o aparece como "?"). Nunca mostrar info
  que la intel no da (coherente con SDD 35/61: la intel es lo único que revela al enemigo).
- **Pictográfico/TTS (SDD 43):** íconos de base/edificio/% y lectura.

## 3. Datos (ya disponibles; poco/nada de backend)
- `state.bases` (tus bases + edificios con `condition`), `state.enemy_maps` ({target_id: {pct, bases:
  [{base_id, planet, units?}]}}). Falta, opcional: que `enemy_maps[].bases[]` traiga el `owner`
  (username) para agruparlo por rival en el modal — chico, en `satellites_state`.

## 4. Tests
- Web smoke: el modal de planeta abre sin errores; con `enemy_maps` muestra rivales del planeta; sin
  mapeo muestra la niebla. (Front; sin e2e de backend salvo el campo `owner` si se agrega.)

## 5. Rollout / riesgos
- Casi todo front (reusa `enemy_maps`/`bases`), aditivo. Riesgo: filtrar info sin intel → el gate es
  usar SOLO `enemy_maps` (que ya respeta el % de mapeo). Va por el pipeline.
