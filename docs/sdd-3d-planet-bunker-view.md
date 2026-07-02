# SDD 70 — Vista 3D: el planeta que gira (bases escaneadas) + búnker bonito

> **Estado:** **DISEÑO** 2026-07-02 · **Pedido:** usuario, 2026-07-02.
> Capa **visual** sobre datos que YA existen. Hoy la vista de planeta (SDD 68) es un **modal plano**:
> tus bases + las enemigas solo si las escaneaste (satélites, `enemy_maps`) o 🌫 niebla. El usuario
> quiere subirla a un **globo 3D que gira**: click en el planeta → se abre una esfera rotando donde se
> ven las bases (las tuyas siempre; las enemigas solo si escaneaste), con **render rápido/eficaz y con
> detalle**; y además una **vista del búnker más bonita** (hoy es una grilla de celdas).
> **Relacionado:** [SDD 68 vista de planeta/niebla](sdd-planet-view-scan.md) (datos + fog ya listos),
> [SDD 61 satélites](sdd-satellites-recon.md) (`enemy_maps`), [SDD 64 búnker](sdd-atomic-bunkers.md)
> (grilla de salas), [SDD 43 pictográfico](sdd-play-without-reading.md), `web/index.html`
> (`openPlanet`/`renderMap`/`renderBunker`). **Sin cambios de backend** — puro front sobre el snapshot.

## 1. Pedido (usuario, 2026-07-02)
- Una **vista del mundo que gira** y ver **las bases de los demás si las escaneamos**.
- Una **vista de nuestro búnker más bonita**.
- Quizás **click en el planeta** → abre algo **que gira** y se puede ver, con **render bueno, rápido,
  eficaz y con detalle**.

## 2. Alcance (solo visual; los datos ya están)
- Reusar `enemy_maps` (SDD 61) + bases por planeta + `bunkers`/`rooms` (SDD 64) del snapshot. NADA de
  backend nuevo. La niebla/escaneo ya la resuelve SDD 68 (tus bases siempre; enemigas si `pct>0`).
- **No romper:** la vista actual (modal plano) queda como fallback si el navegador no soporta WebGL o
  si el usuario prefiere "modo simple" (accesibilidad + máquinas lentas). El 3D es un realce opt-in.

## 3. Decisión técnica: cómo renderizar (rápido/eficaz, sin build step)
El front es **un solo `web/index.html` sin bundler** (principio del proyecto: clientes delgados). Un
motor 3D pesado choca con eso. Opciones (elegir con el usuario):
1. **Canvas 2D con esfera "fake-3D"** (rotación por proyección + sombreado): 0 dependencias, liviano,
   corre en cualquier lado. Detalle medio (marcadores de base que orbitan con el globo). **Recomendado
   para v1** por costo/beneficio y por respetar "rápido/eficaz".
2. **WebGL a mano** (shaders propios, sin lib): más detalle (textura de planeta real, iluminación),
   más código y riesgo. Sin dependencia externa.
3. **three.js por CDN** (una `<script>`): el mejor detalle con menos código propio, pero suma una
   dependencia CDN (~600 KB) y va contra "front delgado/sin build". Sólo si el usuario prioriza detalle.
- **Rendimiento:** dibujar solo con el modal abierto (pausar `requestAnimationFrame` al cerrar y con
  `document.hidden`, como ya hacemos con el polling); marcadores de base = sprites baratos; degradar a
  la vista plana si el FPS cae. Texturas de planeta por `planet_key` (data-driven, cae a color liso).

## 4. Vista del planeta 3D (funcional)
- **Click en el planeta** (en el mapa/galaxia o en el panel del imperio) → abre el globo girando.
- **Tus bases**: siempre visibles, como marcadores sobre la esfera (icono por tipo: superficie/orbital/
  lunar), con su nombre al hover.
- **Bases enemigas**: solo si `enemy_maps[rival].pct>0`; a más % descubierto, más nítidas (de sombra a
  marcador con datos). Sin escaneo → 🌫 no aparecen (niebla, SDD 68).
- **Interacción**: arrastrar para rotar manual, auto-rotación lenta si no interactúas, click en una base
  → su panel (reusa lo de SDD 60/68).

## 5. Vista del búnker "bonita"
- Hoy `renderBunker` es una grilla NxN de celdas. Subir a un **corte lateral subterráneo**: túneles y
  salas dibujadas con su icono, medidores (comida/agua/gente/💾) como barras integradas, salas en obra
  con progreso. Mismo Canvas 2D. Al expandir el búnker (SDD 69 Fase 2) el corte "crece hacia abajo".
- Mantener los botones/acciones actuales (construir sala, sabotaje, repoblación) — solo cambia el lienzo.

## 6. Tests
- Es front sin backend nuevo → **web smoke** (que el modal 3D abre, dibuja sin error de consola, y
  cae al modal plano si `WebGLRenderingContext`/canvas no está). No hay e2e de API nuevo (sin endpoint
  nuevo); se cubre con el smoke de chrome existente. Si algo del snapshot cambiara, e2e correspondiente.

## 7. Preguntas abiertas para el usuario
1. **Motor de render (§3):** ¿Canvas 2D fake-3D (v1 liviano, recomendado), WebGL a mano (más detalle),
   o three.js por CDN (máximo detalle, suma dependencia)?
2. **Prioridad:** ¿esto va antes o después de SDD 69 (búnker civilización de reserva)? Hoy el foco es
   SDD 69 Fase 1.
3. ¿Texturas "reales" de planeta (Tierra/Marte/Venus) o estilizadas/pictográficas (coherente con SDD 43)?
