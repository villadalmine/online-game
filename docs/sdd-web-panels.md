# SDD 3 — Paneles de la web colapsables (más espacio, ver lo que querés)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Ámbito:** SOLO cliente web (`web/index.html`). **Sin cambios de API ni de backend.**

## 1. Objetivo

La web amontona ~15 cards en 3 columnas; en pantallas chicas hay que scrollear mucho. Queremos
que **cada panel se pueda plegar a su título** (colapsar/expandir) para ganar espacio y ver solo
lo que interesa, y que **ese estado se recuerde** entre recargas.

Coherente con API-first: el cliente es un consumidor delgado; esto es **pura presentación**, no
toca reglas de juego ni endpoints. El estado de plegado vive en `localStorage` (como ya hacemos
con el sonido y el último usuario).

### No-objetivos
- No reordenar/arrastrar paneles ni columnas redimensionables con el mouse (posible follow-up;
  ver §7). No drag-and-drop. No backend/persistencia por servidor.

## 2. Diseño

### 2.1 Marcado: id estable por panel
Cada `<div class="card">` recibe un **`data-panel="<id>"`** estable (no derivado del texto del
título, para sobrevivir a i18n y reescrituras). Ej.: `data-panel="acciones"`, `"atacar"`,
`"investigacion"`, `"alianzas"`, `"chat"`, `"galaxias"`, `"transitos"`, `"imperio"`, `"bases"`,
`"colas"`, `"ranking"`, `"notis"`, `"mundo"`, `"asistente"`, `"guia"`.

### 2.2 Colapso por CSS (sin reestructurar cada card)
Los cards son `h2` + contenido hermano. En vez de envolver el cuerpo de cada uno, colapsamos con
una regla CSS que oculta **todo menos el `h2`** cuando el card tiene la clase `.collapsed`:

```css
.card > h2 { cursor: pointer; user-select: none; }
.card > h2::before { content: "▾ "; opacity: .6; font-size: 11px; }
.card.collapsed > h2::before { content: "▸ "; }
.card.collapsed > *:not(h2) { display: none; }
```

Un clic en el `h2` alterna `.collapsed`. El caret (▾/▸) indica el estado. Cero cambios al HTML
interno de cada card.

> Cuidado con reglas existentes que usan `display` con `!important` o IDs internos: como
> ocultamos a nivel de hijos directos del card, los modales/popovers globales (fuera del card)
> no se ven afectados.

### 2.3 Persistencia
- Clave `localStorage["panels.collapsed"]` = JSON array de ids colapsados.
- Al iniciar (tras render del `#game`), `applyPanels()` agrega `.collapsed` a los cards cuyo
  `data-panel` esté en la lista.
- Al togglear, se actualiza el array y se guarda. Helper:

```js
function togglePanel(h2){ const card=h2.closest('.card'); card.classList.toggle('collapsed');
  const set=new Set(JSON.parse(localStorage.getItem('panels.collapsed')||'[]'));
  const id=card.dataset.panel; card.classList.contains('collapsed')?set.add(id):set.delete(id);
  localStorage.setItem('panels.collapsed', JSON.stringify([...set])); }
function applyPanels(){ const set=new Set(JSON.parse(localStorage.getItem('panels.collapsed')||'[]'));
  document.querySelectorAll('.card[data-panel]').forEach(c=>c.classList.toggle('collapsed', set.has(c.dataset.panel))); }
```

El binding del clic: delegación en `main#game` (`addEventListener('click', e=>{ const h=e.target.closest('.card>h2'); if(h) togglePanel(h); })`) para no tocar cada `h2`. Ojo: algunos
`h2` tienen controles dentro (no es el caso hoy; los botones viven en `.row` debajo), así que el
clic en el título es seguro.

### 2.4 "Colapsar/expandir todo" (barra fina, opcional pero barato)
Dos botones chiquitos en el header global: **⊟ plegar todo** / **⊞ expandir todo** que setean
todos los `data-panel` y guardan. Mejora directa del objetivo "ver solo lo que quiero".

## 3. Accesibilidad / UX
- `h2` con `role="button"`, `tabindex="0"`, y toggle con Enter/Espacio.
- El caret comunica el estado; el clic en cualquier parte del título alterna.
- Colapsar no destruye estado (sigue refrescándose por debajo; solo está oculto por CSS), así que
  expandir muestra datos al día sin recargar.

## 4. Plan de tests (regla del proyecto)
**Browser (Playwright)** en `tests/browser/test_ui.py`:
- Click en el `h2` de un card lo colapsa → su cuerpo (un `#id` interno conocido, p.ej. `#world`)
  queda **oculto**; el `h2` sigue visible.
- Recargar la página mantiene el card colapsado (persistencia en `localStorage`).
- Volver a clickear lo expande → cuerpo visible de nuevo.
- "plegar todo" colapsa varios; "expandir todo" los abre.

(No hay e2e HTTP porque no hay endpoint nuevo; es front puro. Igual entra con su test de
navegador + entrada en CHANGELOG.)

## 5. Riesgos
- **Selector `*:not(h2)`**: si algún card tuviera más de un `h2`, ocultaría el segundo. Hoy cada
  card tiene un solo `h2`; se respeta la convención.
- **Colisión de `data-panel`**: ids únicos, revisados a mano (lista en §2.1).

## 6. Impacto
- Archivos: solo `web/index.html` (CSS + ~15 atributos `data-panel` + 3 funciones JS + binding).
- Sin migraciones, sin API, sin deps.

## 7. Follow-ups (fuera de alcance)
- Columnas redimensibles (arrastrar el borde) y reordenar paneles por drag-and-drop, también
  persistidos en `localStorage`. Requeriría su propio SDD.
