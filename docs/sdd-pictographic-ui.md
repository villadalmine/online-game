# SDD 43 — Modo pictográfico de la UI (jugar sin leer)

> **Estado:** **diseño (NO implementado)** · **Fecha:** 2026-06-26 · **Autor:** equipo online-game
> **Ámbito:** principalmente cliente web (`web/index.html`) + un campo **aditivo** `icon:` en
> `content/*.yaml` expuesto por `/catalog`. **Sin cambios de reglas de juego ni de modelos/DB.**

## 1. Objetivo

Hoy casi todo es **texto**: los menús de unidades/edificios, los costos ("iron 30"), los avisos de
"te falta: iron". Eso deja afuera a quien **no lee** (chicos chicos, personas que recién aprenden a
leer) y a quien no domina el idioma del juego. Queremos un **modo pictográfico**: un botón que hace
que **todo lo que dice texto se muestre como dibujo/ícono**, manteniendo al menos un **número o una
letra** para las cantidades de material.

Concretamente, en este modo:
- Cada **unidad, edificio, mineral, tecnología, luna y raza** se muestra con su **ícono**.
- El **costo** se muestra como `🔩 30 · ⚡ 12 · ⏱ 45s` en vez de "iron 30 · ⚡12 · 45s".
- Lo que **falta** se señala con el **ícono del material + una marca y el faltante**:
  `🔩 ❌ −12` (te faltan 12 de hierro), `⚡ ❌ −40`. Lo que **alcanza** → `✓` verde.
- Cada **panel** lo respeta, y el jugador puede **activar/desactivar** el modo **global** o
  **por panel**.

No es "modo para niños tontos": es **accesibilidad + idioma-agnóstico**. El texto **no se pierde**:
sigue disponible como `title`/`aria-label` (tooltip + lectores de pantalla), así también **sirve para
aprender a leer** (toco el dibujo, veo/escucho la palabra).

### No-objetivos
- No quitar el texto para quien sí lee: es un **toggle**, el modo normal queda igual (default).
- No rehacer el motor ni los endpoints de juego (solo `icon:` aditivo en el catálogo).
- No es traducción: el ícono es **universal**, no se localiza (i18n sigue siendo §4 para el texto).
- **Audio/lectura en voz alta (TTS)** y assets SVG propios quedan para fases posteriores (§6).

## 2. Diseño

### 2.1 Íconos data-driven (aditivo, no rompe)
Cada entrada de contenido puede declarar un **`icon:`** (un emoji, p. ej. `icon: "🔩"`). Es
**opcional**: si falta, cae a un **default por categoría** (ver §3). `icon` **no se localiza** (es
universal) → se agrega a `registry.localize*` como campo passthrough y `/catalog?lang=` lo devuelve
igual en todo idioma. Esto es coherente con "data-driven: rebalancear/extender = editar YAML".

Ejemplo (`content/units.yaml`):
```yaml
  - key: worker
    name: "Trabajador"
    icon: "👷"
    ...
  - key: tank
    name: "Tanque"
    icon: "🛡"
```

> **Por qué emoji primero:** cero assets, multiplataforma, ya los usamos (🏗 🔬 ⚡ 🔒 ✓ ⚠). Un
> **sprite SVG** propio (íconos consistentes entre SO) es una mejora opcional de F3 — el campo
> `icon` puede luego apuntar a un id de sprite (`icon: "spr:tank"`) sin romper nada.

### 2.2 Toggle global
- Botón en el header (junto a sonido/idioma) con dos estados: **🔤 Texto** ⇄ **🖼 Dibujos**.
- Estado en `localStorage["ui.pictographic"]` (mismo patrón que `panels.collapsed` y el sonido).
- Al activar, se agrega la clase `pictomode` al `<body>`; los helpers de render (abajo) consultan
  `isPicto(panelId)` y dibujan íconos en vez de texto. Un re-render (`refresh()`/render de cada card)
  aplica el cambio sin recargar.

### 2.3 Toggle por panel
- Cada `<div class="card">` ya tiene **`data-panel="<id>"`** (SDD 3). Agregamos en su `h2` un
  mini-botón **🖼/🔤** que **fuerza** o **excluye** ese panel respecto del global.
- `localStorage["ui.picto.panels"]` = JSON `{ "<id>": true|false }` (override explícito por panel).
- Resolución: `isPicto(id)` = override del panel si existe, si no el global.

```js
function pictoGlobal(){ return localStorage.getItem('ui.pictographic')==='1'; }
function pictoOverrides(){ try{ return JSON.parse(localStorage.getItem('ui.picto.panels')||'{}'); }catch{ return {}; } }
function isPicto(panelId){ const o=pictoOverrides(); return (panelId in o)? o[panelId] : pictoGlobal(); }
```

### 2.4 Helper de ícono (texto siempre presente como aria-label/title)
Un único helper produce el ícono con su **nombre real** accesible — así el texto **se complementa**,
no se pierde (lectores de pantalla, hover para aprender):

```js
// kind: 'mineral'|'unit'|'build'|'tech'|'moon'|'race' ; key: clave de catálogo
function ico(kind, key){
  const it=lookup(kind,key);                 // del catálogo ya cargado
  const sym=(it&&it.icon)||ICON_FALLBACK[kind]||"•";
  const name=(it&&it.name)||key;
  return `<span class="ico" role="img" title="${esc(name)}" aria-label="${esc(name)}">${sym}</span>`;
}
```

### 2.5 Render: costos, faltantes y requisitos en íconos
Las funciones existentes ganan una rama pictográfica (ejemplos, no exhaustivo):

- **`costStr(mc)`** (hoy `"iron 30, silicon 5"`) → en picto: `ico('mineral','iron')+" 30 · "+...`.
- **`affordText(mc, e, planet)`** (hoy `"⚠ te falta: iron"`) → en picto, por cada material que no
  alcanza: `ico('mineral',m)+' <span class="bad">❌ −'+short+'</span>'` (con el **faltante** real,
  no solo "falta"); si todo alcanza, `✓` verde. La energía: `⚡ ❌ −N`.
- **`reqLock(o, base)`** (hoy `"🔒 🏗 Fábrica + 🔬 Tech"`) → en picto: `🔒 ` + `ico('build',rb)` +
  `ico('tech',o.requires_tech)` (el candado ya es ícono; cae bien).
- **`renderTrainCost`/`renderCost`/`renderExpInfo`** usan los de arriba → quedan pictográficos solos.

**Cantidades:** siempre se muestra el **número** (los dígitos se reconocen antes que las letras).
Como refuerzo opcional para cantidades chicas (≤5), se pueden mostrar **pips** (`●●●`). La **letra**
del material (símbolo químico: `Fe`, `Si`, `Ti`) sirve de **fallback** cuando no hay ícono claro.

### 2.6 Selects → grilla de botones-ícono
Los `<select>` nativos (elegir unidad/edificio/luna) son **solo texto**. En pictomode se renderiza,
**encima del select (que queda oculto)**, una **grilla de botones-ícono**: un botón por opción con su
**dibujo + costo en íconos + ✓/❌**. Al tocar un botón se setea el `value` del `<select>` y se dispara
su `change` → **reusa toda la lógica actual** (sin duplicar reglas). Fuera de pictomode, el `<select>`
normal vuelve a verse.

### 2.7 Estados como íconos (vocabulario común)
Un set chico y consistente, ya parcialmente en uso: `✓` alcanza/listo · `❌` falta · `−N` faltante ·
`⏳`/`⏱` en curso/tiempo · `🔒` bloqueado (requiere) · `⚠` atención · `⚡` energía · `📍` lugar/planeta.

## 3. Mapa de íconos propuesto (punto de partida, data-driven)
Va como `icon:` en cada YAML; ajustable sin tocar código.

- **Minerales:** hierro `🔩`, silicio `🪟`, aluminio `🥫`, titanio `🛠`, azufre `🧪`, magnesio `✨`,
  basalto `🪨`, helio-3 `⚛`, tierras raras `💎`, hielo de agua `🧊`. (Fallback: `🪨` + símbolo `Fe/Si`.)
- **Unidades:** trabajador `👷`, militar `💂`, científico `🔬`, tanque `🛡`, barco `🚢`, avión `✈`,
  transbordador `🚀`, espía `🕵`, nave de carga `🛰`. (Fallback unidad: `🪖`.)
- **Edificios:** base central `🏛`, mina `⛏`, planta de energía `⚡`, fábrica `🏭`, laboratorio `🔭`,
  torreta `🛡`, hangar `🚀`, mercado `🏪`, contraespionaje `🛰`. (Fallback edificio: `🏗`.)
- **Recursos/estado:** energía `⚡`, tiempo `⏱`, alcanza `✓`, falta `❌`, bloqueado `🔒`.

## 4. Datos / API
- **Aditivo:** campo `icon:` opcional en `minerals/units/buildings/technologies/moons/races`. El
  loader/registry lo pasa tal cual; `/catalog?lang=` lo expone sin localizar.
- **Cache:** `/catalog` está cacheado 300s (memoria de proyecto) → tras deploy, los íconos nuevos
  tardan ≤5 min en verse. Sin migraciones, sin cambios de modelos.

## 5. Alcance incremental (fases)
- **F1 — base:** `icon:` en YAML + toggle global + `ico()` + ramas pictográficas en
  `costStr`/`affordText`/`reqLock` (costos y faltantes con íconos y número). Cubre el pedido central.
- **F2 — navegación sin leer:** grilla de botones-ícono para los `<select>` + toggle **por panel**.
- **F3 — no-lectores totales (opcional):** sprite **SVG** propio (consistencia entre SO) y
  **lectura en voz alta (TTS)** al tocar un ícono (`speechSynthesis` con el `name` del catálogo,
  respetando el idioma) — para quien no lee **nada**, no solo "menos texto".

## 6. Tests (cuando se implemente)
- **e2e:** `/catalog` devuelve `icon` para minerales/unidades/edificios; alta de feature con happy
  path + un caso de error (ítem sin `icon` cae al fallback) — regla del proyecto.
- **front:** `node --check` de los `<script>`; el toggle persiste en `localStorage`; `affordText`
  pictográfico muestra el faltante numérico correcto; pictomode **no altera** qué se puede/no comprar
  (solo presentación).

## 7. Riesgos / decisiones
- **Ambigüedad de un ícono:** se mitiga con **tooltip+nombre** (`title`/`aria-label`), el **número**
  siempre visible y, opcional, la **letra/símbolo**. El objetivo no es adivinar, es **reconocer**.
- **Emoji se ve distinto por SO/fuente:** aceptable en F1; F3 (SVG sprite) lo vuelve consistente.
- **No es "modo bobo":** se comunica como **🖼 Dibujos** (accesibilidad / idioma-agnóstico), no como
  "modo niño", para no estigmatizar; y es **reversible** y **por panel**.
- **Mantener una sola fuente de verdad:** los botones-ícono setean el `<select>` real y reusan la
  lógica → nunca se duplican reglas de costo/affordability.

## 8. Por qué encaja con los principios
- **API-first / cliente delgado:** la lógica no se toca; es presentación + un campo de catálogo.
- **Data-driven:** los íconos viven en YAML; cambiar un dibujo = editar un valor.
- **Extender, no romper:** `icon:` es aditivo y opcional (fallback); el modo normal es el default.
