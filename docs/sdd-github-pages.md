# SDD 18 — GitHub Pages del juego, auto-generado desde los SDDs

> **Estado:** propuesto · **Fecha:** 2026-06-23 · **Autor:** equipo online-game
> **Relacionado:** todos los `docs/sdd-*.md`, `ROADMAP.md`, `CHANGELOG.md`, [SDD 12 showcase](sdd-player-metrics-public.md).

## 1. Objetivo

Publicar una **landing page del juego en GitHub Pages** (sitio estático servido por el propio repo)
con la info importante, **generada automáticamente leyendo los SDDs + ROADMAP + CHANGELOG**. Así es
**auto-actualizable**: cada push a `main` regenera el sitio desde la fuente de verdad (los SDDs), sin
mantener un HTML a mano.

## 2. Principios

- **Data-driven** (como el resto del proyecto): el contenido sale de archivos versionados (los SDDs),
  no se duplica. Un SDD nuevo o un cambio de estado se refleja solo en el sitio.
- **Sin secretos / sin infra**: el generador lee SOLO docs públicos commiteados (que ya mantenemos
  limpios: sin dominio/IPs/emails/keys — esos viven en `.env`/`values-*.yaml` gitignored). El sitio
  **no** debe exponer datos de infra. La URL pública del juego se inyecta por **variable de repo**
  (`vars.GAME_URL`), no hardcodeada.
- **Sin dependencias pesadas**: generador en **Python stdlib** (parseo de markdown propio y mínimo),
  fiel a "single installer / no nuevas deps". (Alternativa: Jekyll nativo de Pages, pero no agrega el
  agregado/extracción que queremos.)

## 3. De dónde sale cada cosa (extracción)

Cada `docs/sdd-*.md` ya tiene una estructura estable que el generador parsea:
- **Título**: el `# ` (H1) — ej. "SDD 14 — Alta moderada…".
- **Estado + Fecha**: la línea `> **Estado:** … · **Fecha:** …` (blockquote del encabezado).
- **Objetivo**: el primer párrafo bajo `## 1. Objetivo` (resumen de una o dos líneas).
- **Implementado vs diseñado**: del marcador en `ROADMAP.md` (🟢/✅ = hecho, 📝 = diseñado) cruzando
  por número de SDD, o de una sección "Estado de implementación" dentro del SDD si existe.

Además:
- **Novedades**: las últimas N entradas de `CHANGELOG.md` (sección `[Unreleased]` / por fecha).
- **Cómo jugar**: link a `vars.GAME_URL` (si está seteada) + breve "pedí acceso" (allowlist, SDD 14).
- **Showcase opcional (futuro)**: el sitio podría consumir los endpoints públicos `/public/*`
  (SDD 12) por JS para mostrar stats/leaderboard en vivo (sin auth, sin email).

## 4. Estructura propuesta

```
scripts/build_site.py        # generador (stdlib): lee docs/ + ROADMAP + CHANGELOG -> site/
site/                        # salida generada (o publicada por el Action sin commitear)
  index.html                 # landing: pitch + tabla de features/estado + novedades + cómo jugar
  style.css
.github/workflows/pages.yml  # build + deploy a GitHub Pages en cada push a main
```

`build_site.py` (boceto):
1. Glob `docs/sdd-*.md` → por cada uno extrae {num, título, estado, fecha, objetivo}.
2. Parsea `ROADMAP.md` para el flag hecho/diseñado por SDD.
3. Toma las últimas entradas de `CHANGELOG.md`.
4. Renderiza `site/index.html` desde una plantilla simple (f-strings/`string.Template`), con:
   - hero (nombre del juego, una línea de pitch, botón "Jugar" → `GAME_URL`),
   - **tabla de features** (cada SDD: título + estado + objetivo),
   - **novedades** (changelog),
   - footer con link al repo y licencia.

## 5. GitHub Pages: cómo se publica

- **Pages con GitHub Actions** (recomendado, no necesita branch `gh-pages`):
  `.github/workflows/pages.yml` corre en `push` a `main`: ejecuta `python scripts/build_site.py`,
  sube `site/` como artifact y `actions/deploy-pages@v4` lo publica. Habilitar Pages → "GitHub
  Actions" en Settings.
- **Variable de repo** `GAME_URL` (Settings → Secrets and variables → Actions → Variables) con la URL
  pública; el Action la pasa como env al generador. Así el dominio **no** queda en el repo.
- URL del sitio: `https://<user>.github.io/<repo>/` (o dominio propio vía `CNAME` si se quiere — ese
  CNAME sí sería público, decisión del usuario).

## 6. Auto-actualización

- Disparador: `on: push: branches: [main]` (+ `workflow_dispatch` manual). Cada merge a `main`
  regenera el sitio desde los SDDs → siempre refleja el estado real, cero mantenimiento de HTML.
- Determinístico: misma entrada (docs) → misma salida; el sitio es un reflejo, no una fuente.

## 7. Privacidad / seguridad

- El generador **falla** (o filtra) si detecta en la salida patrones sensibles (emails, IPs privadas,
  `sk-...`) — un guard simple de regex sobre el HTML generado antes de publicar, como el `scan` que
  usamos en los commits. Defensa en profundidad por si un SDD futuro filtra algo.
- Solo se publican `docs/`, `ROADMAP`, `CHANGELOG` (públicos). Nunca `.env`, `values-*.yaml`,
  `acme-dns-account.json` (gitignored).

## 8. Validación / tests

- Test del generador (`tests/test_site.py`): dado un `docs/` de muestra, el HTML contiene el título
  de cada SDD y su estado; el guard de privacidad rechaza una entrada con un email/IP de prueba.
- El Action corre el generador en CI; si falla el guard, no publica.

## 9. Follow-up / ideas

- Showcase en vivo (stats/leaderboard) vía `/public/*` (SDD 12) con fetch JS.
- i18n del sitio (ES/EN) reusando el criterio de contenido (SDD 4).
- Página por SDD (render del markdown completo) además del índice.
