# SDD 24 — Landing pública del juego en `/game` (bilingüe, para compartir en redes)

> **Estado:** propuesto · **Fecha:** 2026-06-24 · **Autor:** equipo online-game
> **Relacionado:** `web/`, `app/main.py` (rutas `/` y `/health`), [SDD 4 i18n](sdd-i18n.md),
> [SDD 18 GitHub Pages](sdd-github-pages.md), [SDD 11 lifecycle/monetización](sdd-game-lifecycle.md).

## 1. Objetivo

Una página **linda y compartible** en `https://<dominio>/game` que cuente **de qué se trata** el
juego, sus **features**, el **modelo** (free / paid / BYOD) y un CTA a **jugar**. **Bilingüe
(ES/EN)** y optimizada para **redes sociales** (Open Graph / Twitter Cards → preview con título,
descripción e imagen al pegar el link).

**Diferencia con SDD 18** (GitHub Pages): SDD 18 es **dev-facing** (estado del proyecto, auto-generado
desde los SDDs). SDD 24 es **player-facing** (marketing), servido **por la app** en `/game`. Públicos
y propósitos distintos; pueden compartir el banner/imagen.

## 2. Diseño

### 2.1 Ruta y entrega
- `@app.get("/game")` en `app/main.py` → `FileResponse(web/landing.html)`. No toca `/` (cliente de
  juego) ni `/health`. Estático, vanilla JS (como el cliente), sin build.
- Asset de imagen social servido estático: `GET /og-image.png` → `FileResponse(web/og-image.png)`.

### 2.2 Contenido (secciones)
- **Hero**: nombre + tagline de una línea + botón **Jugar / Play** (→ `/`).
- **De qué se trata**: estrategia espacial por turnos con **galaxias y planetas reales**.
- **Features** (íconos + 1 línea): galaxias/planetas/lunas reales, **combate con viaje de flotas**,
  **NPCs con IA (LLM)**, **asistente AI** que entiende el grafo del juego, alianzas, expediciones a
  lunas, investigación, **temporadas + Hall of Fame**, multi-cliente (web/CLI/…).
- **Modelo** (a confirmar con el usuario — §5):
  - **Free**: jugás gratis en la instancia pública (alta por invitación, SDD 14).
  - **BYOD / self-host**: es **open source (MIT)** → levantás **tu propia instancia** (Helm/k8s o
    docker) y, si querés IA, **traés tu propia API key de LLM** (OpenRouter/Ollama — provider-agnóstico).
  - **Paid**: por ahora **nada** (SDD 11: sin monetización); a futuro, cosmético/premium opcional.
- **Footer**: link al repo (MIT), créditos.

### 2.3 i18n (ES/EN)
- Mismo patrón que el cliente (SDD 4): un dict `{es,en}` + toggle 🌐, o render por `Accept-Language`.
  Default ES; persistir elección en `localStorage`. Todo el texto de la landing traducido.

### 2.4 Social share (Open Graph / Twitter)
- `<meta property="og:title|og:description|og:image|og:url|og:type=website">` +
  `<meta name="twitter:card" content="summary_large_image">`.
- `og:url` y `og:image` **absolutas** → necesitan el dominio público. Configurable por env
  `PUBLIC_URL` (ej. `https://<dominio>`), inyectada en el HTML (o un placeholder reemplazado al
  servir). Sin PUBLIC_URL, se omiten o usan relativas (preview pobre).
- `og:image`: **1200×630 PNG** (lo que piden FB/Twitter/LinkedIn). SVG no es confiable en redes.

### 2.5 Imagen social (`og-image.png`)
- **curl NO sirve** (no renderiza). Opciones:
  - **A — screenshot con Playwright** (ya hay harness `tests/browser`): un script carga el juego (o
    la propia landing) en Chromium y guarda `web/og-image.png` (1200×630). Reproducible.
  - **B — banner provisto** por el usuario (diseño propio) → se copia a `web/og-image.png`.
- v1: capturo un screenshot del juego con Playwright como og:image; el usuario puede reemplazarlo
  por un banner cuando quiera.

## 3. Implementación (v1)
- `web/landing.html` (bilingüe + OG tags), `web/og-image.png` (asset).
- Rutas `/game` y `/og-image.png` en `app/main.py`.
- `PUBLIC_URL` en config (para og:url/image absolutas) — opcional.
- El Dockerfile ya copia `web/` → el asset y el HTML viajan en la imagen.

## 4. Tests
- e2e: `GET /game` → 200 + contiene el pitch (ES y EN) y las meta `og:*`/`twitter:card`.
- e2e: `GET /og-image.png` → 200, `content-type: image/png`.
- (Opcional) browser test: la landing renderiza y el toggle 🌐 cambia el idioma.

## 5. Decisiones a confirmar (producto — no inventar)
- **Qué significa "BYOD"** exactamente: ¿*self-host* (traé tu propio deploy) y/o *bring-your-own-key*
  (tu propia API key de LLM)? La landing debe decirlo bien.
- **"Paid"**: ¿se anuncia "a futuro" o no se menciona por ahora? (SDD 11 = sin monetización hoy.)
- **og:image**: ¿screenshot del juego (lo saco con Playwright) o banner que pasás vos?

## 6. Follow-up
- Dominio propio / `og:url` por env; analytics (privacy-friendly); versión EN/ES por subpath o `?lang`;
  reutilizar el banner en SDD 18 (Pages).
