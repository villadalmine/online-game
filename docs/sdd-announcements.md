# SDD 27 — Anuncios / "Lo que viene" (sección de novedades en la página)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 24 landing /game](sdd-landing-page.md), [SDD 4 i18n](sdd-i18n.md),
> [SDD 26 universos spin-off](sdd-spinoff-universes.md), [SDD 11 temporadas](sdd-game-lifecycle.md),
> `CHANGELOG.md`, `ROADMAP.md`.

## 0. Cómo usar este SDD
Este documento **es la fuente de verdad del diseño**. Los anuncios viven como **datos tipados**
(`content/announcements.yaml`), no en el front. Para cambiar/añadir un anuncio se edita el YAML (o
este SDD primero, si cambia el modelo). Todo **data-as-code, tipado y bilingüe** (ES default + `*_en`).

## 1. Objetivo
Una sección **"📣 Anuncios / Lo que viene"** en la página pública (landing `/game`, SDD 24, y/o el
cliente web) que muestre, **categorizadas**, las novedades del juego: lo **ya disponible**, lo **que
viene** y los **universos spin-off** (explicando qué trae cada uno y en qué **difiere del estándar**).
API-first (un endpoint sirve a web/CLI/futuros clientes), bilingüe, sin auth (es contenido público).

## 2. Categorías (tipos de anuncio)
Campo `category` (extensible vía YAML):
- **`release`** — novedad **ya jugable** (espejo curado del CHANGELOG; ej. "Multiplicadores físicos").
- **`incoming`** — **lo que viene** (espejo curado del ROADMAP; ej. "Bot de Telegram").
- **`spinoff`** — **universo** ([SDD 26](sdd-spinoff-universes.md)); explica qué trae y su **diferencia
  con el estándar** (universo hard-real).
- **`season`** — temporadas / eventos ([SDD 11](sdd-game-lifecycle.md)): apertura/cierre, Hall of Fame.
- **`maintenance`** — ventanas de mantenimiento / cambios operativos.

Campo `status` (independiente de la categoría): **`live`** (disponible) · **`coming`** (en desarrollo)
· **`planned`** (en diseño). La UI puede agrupar por `category` y ordenar por `status`/`date`.

## 3. Modelo de objetos (tipado, i18n — `content/announcements.yaml`)
```yaml
announcements:
  - key: physics-multipliers          # estable, único (kebab-case)
    category: release
    status: live
    date: 2026-06-24                   # ISO; orden cronológico
    title: "Multiplicadores físicos"
    title_en: "Physical multipliers"
    summary: "La gravedad afecta el tiempo de construcción; la insolación y la temperatura, la energía."
    summary_en: "Gravity affects build time; insolation and temperature affect energy."
    tags: [gameplay, ciencia]
    link: "docs/sdd-scientific-accuracy.md"   # opcional (SDD/CHANGELOG/externo)

  - key: telegram-bot
    category: incoming
    status: planned
    title: "Bot de Telegram"
    title_en: "Telegram bot"
    summary: "Jugar y recibir notificaciones desde Telegram (mismo backend)."
    summary_en: "Play and get notifications from Telegram (same backend)."
    tags: [clientes]
    link: "docs/sdd-telegram-bot.md"
```

### 3.1 Anuncio de **spin-off** (categoría `spinoff`) — campos extra
Liga a [SDD 26](sdd-spinoff-universes.md) por `universe` y lista **qué trae** y la **diferencia con el
estándar** (universo hard-real: Sistema Solar + exosistemas reales):
```yaml
  - key: spinoff-star-wars
    category: spinoff
    status: planned
    title: "Universo: Star Wars"
    title_en: "Universe: Star Wars"
    summary: "Una partida ambientada en una galaxia muy, muy lejana."
    summary_en: "A game set in a galaxy far, far away."
    universe: star_wars               # = pack de SDD 26
    canon: fiction
    standard_baseline: "Universo estándar: planetas y materiales reales (Sistema Solar/exosistemas)."
    standard_baseline_en: "Standard universe: real planets and materials (Solar System/exosystems)."
    differences:                      # qué CAMBIA respecto del estándar
      - "Mundos del lore: Tatooine (desierto, 2 soles), Hoth (helado), Coruscant (ciudad-planeta)."
      - "Naves con hiperimpulsor: X-wing, Caza TIE, Destructor Estelar, Estación de batalla."
      - "Materiales nuevos: cristal kyber (armamento) y beskar (blindaje)."
      - "Facciones: rebeldes vs. Imperio (sabor; mapeo de razas a futuro)."
    differences_en:
      - "Lore worlds: Tatooine (desert, twin suns), Hoth (frozen), Coruscant (city-planet)."
      - "Hyperdrive ships: X-wing, TIE fighter, Star Destroyer, battle station."
      - "New materials: kyber crystal (weaponry) and beskar (armor)."
      - "Factions: Rebels vs. Empire (flavor; race mapping later)."
    licensing: fan-noncommercial      # ⚠️ ver SDD 26 §2 (IP de terceros)
    link: "docs/sdd-spinoff-universes.md"
```
> Habría un anuncio `spinoff` por pack (`star_trek`, `bsg`, `star_wars`), cada uno con su
> `differences`/`differences_en`. El bloque **`differences`** es lo que el usuario pidió: explicar
> **cada cosa nueva** que trae y **en qué se diferencia del estándar**.

## 4. API (cuando se implemente)
- `GET /announcements` — público, sin auth. Query: `?lang=` (SDD 4), `?category=`, `?status=`.
  Devuelve la lista **localizada** (swap `*_en`, drop helpers — `registry.localize*`), ordenada por
  `date` desc dentro de cada categoría. Cacheable (Redis, SDD 7) por ser público y estable.
- `GET /announcements/{key}` — detalle de uno (para deep-link/compartir).
- (Opcional) `category` y `status` como enums validados; `key` único.

## 5. Web (cuando se implemente)
- Sección **"📣 Anuncios / Lo que viene"** en la landing `/game` (SDD 24) y/o card colapsable en el
  cliente (SDD web-panels). Filtros/tabs por `category`; badge por `status` (Disponible / En camino /
  En diseño). Toggle 🌐 ES/EN ya existente. Cada card: título, fecha, resumen, tags, link.
- Cards `spinoff`: muestran `standard_baseline` + lista `differences` (qué cambia vs el estándar) y la
  nota de licencia (fan/no-comercial, SDD 26 §2).
- Open Graph (SDD 24) para compartir un anuncio en redes (deep-link por `key`).

## 6. Fuente de verdad / mantenimiento
- **Curado** en `content/announcements.yaml` (control editorial; no se filtra nada privado/infra).
- Coherencia: `release` debe reflejar entradas reales del **CHANGELOG**; `incoming` del **ROADMAP**.
  Opcional a futuro: script que **proponga** borradores de anuncios desde CHANGELOG/ROADMAP (no
  auto-publica; alguien edita el copy y traduce). Mantiene una sola fuente sin duplicar a mano.

## 7. Validación / tests (regla del proyecto, al implementar)
- **Contenido**: cada anuncio tiene `key` único, `category`/`status` válidos, `date` ISO, `title`; los
  `spinoff` tienen `universe` (existente en SDD 26), `differences` y `licensing`. `*_en` presentes o
  cae a ES (SDD 4).
- **E2E**: `GET /announcements` (200, lista localizada), `?category=spinoff` filtra, `?lang=en`
  localiza, `GET /announcements/{key}` 200 y 404 para clave inexistente.
- **Browser**: la sección aparece en `/game`, filtra por categoría, muestra `differences` en spin-offs.

## 8. Riesgos / decisiones
- **IP de spin-offs**: los anuncios `spinoff` heredan el caveat de [SDD 26 §2](sdd-spinoff-universes.md)
  (marcas de terceros → fan/no-comercial; modo genérico recomendado para publicar).
- **No duplicar la fuente**: el YAML es curado; los espejos de CHANGELOG/ROADMAP son **resúmenes**
  editoriales, no copias automáticas (evita desincronización y filtraciones).
- **Alcance v1 sugerido**: endpoint + YAML con unos pocos anuncios reales (físicos, catch-up, login
  OTP) + 3 `spinoff` (uno por pack) + 2 `incoming`. Crecer editando el YAML.
- **NO implementación todavía** — este SDD es la especificación.
