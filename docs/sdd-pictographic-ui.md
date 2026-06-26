# SDD 43 — Modo pictográfico de la UI (jugar sin leer)

> **Estado:** **F1 + F2 (parcial) + TTS implementado** (en producción). Paneles ya pictografiados:
> `acciones`, `imperio`, `mercado`, `hub`, `transitos`, `alianzas`, **`combate`, `investigacion`,
> `colas`, `bases`, `galaxias`** (botones como íconos; tech/edificio/unidad/planeta/luna como ícono;
> investigación con 🔒 de prerequisito; colas con ícono+tiempo; bases con stock como chips). Se agregó
> `icon:` a **planetas** (`content/planets.yaml`) y **lunas** (`content/gods.yaml`), expuestos por
> `/catalog`. · **⏳ PENDIENTE:** `atacar`, `eventos`, `temporada`, `ranking`, `meta`, `universos`,
> `notis/anuncios`, `perfil`, `guia` (como leyenda) + fallback TTS de servidor. · **Fecha:**
> 2026-06-26 · **Autor:** equipo
> **Ámbito:** principalmente cliente web (`web/index.html`) + un campo **aditivo** `icon:` en
> `content/*.yaml` expuesto por `/catalog`. **Sin cambios de reglas de juego ni de modelos/DB.**

## 1. Objetivo

Hoy casi todo es **texto**: los menús de unidades/edificios, los costos ("iron 30"), los avisos de
"te falta: iron". Eso deja afuera a quien **no lee** (chicos chicos, personas que recién aprenden a
leer) y a quien no domina el idioma del juego. Queremos un **modo pictográfico**: un botón que hace
que **todo lo que dice texto se muestre como dibujo/ícono**, manteniendo al menos un **número o una
letra** para las cantidades de material.

**Premisa del usuario (clave):** el juego tiene que ser jugable por alguien que **no sabe leer
nada**, pero que **sí sabe relacionar tres cosas: números, íconos y la letra/símbolo del material**
(`Fe`, `Si`, `Ti`…). Por eso el "vocabulario" de este modo es exactamente ese trío —
**ícono + letra + número** — y **TODOS los paneles** (no solo construir/entrenar) deben hablarlo;
ver la **cobertura panel por panel** en §3.

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

> **Invariante (no negociable):** este modo **no puede romper la UI actual**. Es **aditivo** y viene
> **apagado por default**. Con el modo **desactivado** (global o por panel), **todo queda
> exactamente como hoy** — mismo HTML, mismas funciones, mismos textos. La rama pictográfica solo se
> ejecuta cuando `isPicto(...)` es true; si se quita el modo, no queda ningún rastro. No se borra ni
> se reemplaza ningún render existente: se **agrega** una rama paralela.

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

**El "chip de material" (unidad atómica del modo):** se compone de **ícono + letra + número** y es
la pieza que se reutiliza en TODOS los paneles (costos, stocks, faltantes, botín, premios, intel):

```
🔩 Fe 30        (ícono hierro · símbolo · cantidad)
⚡ 12           (energía: ícono + número)
⏱ 45s          (tiempo)
🔩 Fe ❌ −12    (faltan 12 de hierro)
```

La **letra/símbolo** del mineral (`Fe`, `Si`, `Ti`, `Al`, `S`, `Mg`, `He3`…) **siempre acompaña** al
ícono (no es solo fallback): el usuario las relaciona aunque no lea palabras, y desambigua dos
íconos parecidos. Es un campo del catálogo (`symbol:` por mineral; ver §4). El **número** se muestra
siempre (los dígitos se reconocen temprano); como refuerzo para cantidades chicas (≤5) se pueden
mostrar **pips** (`●●●`).

### 2.6 Selects → grilla de botones-ícono
Los `<select>` nativos (elegir unidad/edificio/luna) son **solo texto**. En pictomode se renderiza,
**encima del select (que queda oculto)**, una **grilla de botones-ícono**: un botón por opción con su
**dibujo + costo en íconos + ✓/❌**. Al tocar un botón se setea el `value` del `<select>` y se dispara
su `change` → **reusa toda la lógica actual** (sin duplicar reglas). Fuera de pictomode, el `<select>`
normal vuelve a verse.

### 2.7 Estados como íconos (vocabulario común)
Un set chico y consistente, ya parcialmente en uso: `✓` alcanza/listo · `❌` falta · `−N` faltante ·
`⏳`/`⏱` en curso/tiempo · `🔒` bloqueado (requiere) · `⚠` atención · `⚡` energía · `📍` lugar/planeta.

## 3. Cobertura por panel (TODOS)
La regla es **cobertura total**: cada panel debe poder jugarse con **ícono + letra + número**. Abajo,
los 25 paneles (`data-panel`) y cómo hablan el modo. Todos reusan el **chip de material** (§2.5),
`ico()` (§2.4) y los estados (§2.7).

| Panel (`data-panel`) | En pictomode |
|---|---|
| `acciones` (construir/entrenar/expedición) | grilla de botones-ícono (§2.6); costo y faltante como chips; `🔒`+ícono de requisito |
| `atacar` | selección de unidades como íconos con su número; ⚔ poder propio vs objetivo en número; `⚡`/`✓`/`❌` |
| `combate` | resultados como íconos: unidades perdidas/sobrevivientes (ícono + número), botín como chips de material |
| `investigacion` | tecnologías como íconos; costo en chips; `🔒`+íconos de prerequisito; `⏳` en curso con número de tiempo |
| `bases` | cada base = ícono de planeta + íconos de edificios (con nivel/número); base orbital `🛰`, lunar `🌙` |
| `imperio` | totales de stock como chips de material; energía `⚡`+número; unidades como íconos+número |
| `colas` | cada ítem en cola = ícono de lo que se hace + `⏳`+número de tiempo restante (build/train/research/transporte/espía) |
| `transitos` | misiones en viaje = ícono (ataque/transporte/expedición) + origen→destino con íconos de planeta + `⏱` |
| `mercado` / `hub` | minerales como chips (ícono+letra); precio compra/venta en número; `🛰`naves y `🏴‍☠️`riesgo % ya son ícono+número |
| `galaxias` | galaxias/planetas como íconos; abundancias destacadas como chips de material |
| `mundo` (modal planeta) | atributos como íconos (`🌡`temp+número, `🪨`gravedad, `💧`agua sí/no); colonizar con costo en chips (ya en SDD 37 v1.6) |
| `eventos` | cada evento = su ícono + efecto como `×N`; estado `🟢`activo / `⏳`/ `🔮` |
| `temporada` | progreso/ranking de temporada como íconos + número; premios como chips |
| `ranking` | posición como número grande + medalla (`🥇🥈🥉`); puntaje en número |
| `meta` | tasas como `%`/número + flechas `▲▼`; "qué ataque gana" con íconos de unidad |
| `alianzas` | miembros como avatares/íconos; beneficios como `×N`; acciones como botones-ícono |
| `universos` | cada universo como ícono/emblema + número de jugadores |
| `notis` / `anuncios` | cada aviso con un **ícono de tipo** (⚔ ataque, 🛡 defensa, 🔬 research, 🏪 mercado, 📣 release) + número; el cuerpo es texto → ver "texto irreducible" abajo |
| `perfil` | acciones como botones-ícono; energía de nivelado `⚡`+número; estado de cuenta como ícono (`✓`/`⏳`/`🚫`) |
| `guia` | ya es visual; en pictomode prioriza la fila de íconos con su significado (es la **leyenda** del modo) |
| `asistente` / `chat` / `admin` | **texto por naturaleza** (lenguaje libre / gestión). No se pictografían los mensajes; se aplican íconos solo a sus **controles** (enviar, modo, aprobar `✓`/rechazar `❌`). Ver abajo. |

**Texto irreducible.** Hay contenido que es lenguaje libre (chat, respuestas del asistente, cuerpo de
una noticia, gestión de cuentas del admin). No se "dibuja"; el modo:
1. pictografía **todo lo accionable y numérico** alrededor (botones, costos, estados, tipos);
2. deja un **ícono de tipo** + el número/fecha para reconocer "qué es" sin leer el cuerpo;
3. (F3) ofrece **lectura en voz alta** (TTS) de ese texto al tocarlo, para el no-lector total.

La **`guia`** funciona como **leyenda**: en pictomode muestra el diccionario ícono↔cosa, así el
jugador aprende el vocabulario del juego sin depender de palabras.

## 3.bis Mapa de íconos propuesto (punto de partida, data-driven)
Va como `icon:` en cada YAML; ajustable sin tocar código.

- **Minerales (ícono + símbolo):** hierro `🔩 Fe`, silicio `🪟 Si`, aluminio `🥫 Al`, titanio `🛠 Ti`,
  azufre `🧪 S`, magnesio `✨ Mg`, basalto `🪨 Ba`, helio-3 `⚛ He3`, tierras raras `💎 RE`,
  hielo de agua `🧊 H₂O`. El **símbolo siempre se muestra** junto al ícono (no es solo fallback).
- **Unidades:** trabajador `👷`, militar `💂`, científico `🔬`, tanque `🛡`, barco `🚢`, avión `✈`,
  transbordador `🚀`, espía `🕵`, nave de carga `🛰`. (Fallback unidad: `🪖`.)
- **Edificios:** base central `🏛`, mina `⛏`, planta de energía `⚡`, fábrica `🏭`, laboratorio `🔭`,
  torreta `🛡`, hangar `🚀`, mercado `🏪`, contraespionaje `🛰`. (Fallback edificio: `🏗`.)
- **Recursos/estado:** energía `⚡`, tiempo `⏱`, alcanza `✓`, falta `❌`, bloqueado `🔒`.

## 4. Datos / API
- **Aditivo:** campo `icon:` opcional en `minerals/units/buildings/technologies/moons/races` y
  `symbol:` opcional en `minerals` (la **letra**: `Fe`, `Si`, `He3`…). El loader/registry los pasa
  tal cual; `/catalog?lang=` los expone **sin localizar** (ícono y símbolo son universales).
- **Cache:** `/catalog` está cacheado 300s (memoria de proyecto) → tras deploy, los íconos nuevos
  tardan ≤5 min en verse. Sin migraciones, sin cambios de modelos.

## 4.bis Estado de implementación (2026-06-26) — F1 + TTS
- **Datos/API (hecho):** `icon:` en `minerals/units/buildings`, `symbol:` en `minerals`
  (`content/*.yaml`). Fluyen por `/catalog` sin localizar (el `localize` mantiene las claves no-`_en`;
  no hubo cambios de registry/DB). e2e `test_catalog_pictographic_icons` (icon/symbol presentes e
  iguales en es/en).
- **Front (hecho):** botón header **🔤/🖼**, `localStorage["ui.pictographic"]`, clase `body.pictomode`,
  helpers `isPicto()`/`ico()`/`mchip()`. Rama pictográfica en `costStr`/`affordText`/`reqLock` (panel
  `acciones`) y en los chips de minerales/unidades del panel `imperio`. Con el modo **off**, render
  idéntico a hoy (invariante).
- **TTS (hecho, adelantado de F3):** en `pictomode`, un clic en cualquier `.ico` lo **lee en voz
  alta** (Web Speech API `speechSynthesis`, voz por idioma es/en, sin infra). Resuelve "lo difícil de
  representar": tocás y escuchás qué es. Fallback de servidor (proxy espeak-ng, como en el repo
  `shooter`) queda pendiente para navegadores sin voces (Chromium/Linux).
- **F2 (parcial, hecho):** **grilla de botones-ícono** para los `<select>` de Acciones
  (construir/entrenar/expedición) con marca `✓`/`❌`/`🔒` por opción (los selects se ocultan en
  pictomode y los botones setean su `value`); **toggle por panel** (botón 🔤/🖼 en cada `h2`,
  override en `localStorage["ui.picto.panels"]`); chips de mineral (ícono+letra) en **mercado** y
  **hub**.
- **F2 cont. (hecho):** chip/íconos en `atacar` (force-picker con íconos + ✓/❌ de energía),
  `combate` (unidades perdidas y botín como íconos/chips) y `eventos` (ícono grande + ⏱, nombre por
  TTS). `transitos` ya era icónico.
- **Tests de frontend (nuevos):** `tests/test_web_smoke.py` (Playwright + Chromium) levanta un server
  real y verifica que el modo dibujos renderiza **sin errores de JS** y que la sesión es resiliente
  (un 503 transitorio NO desloguea; un 401 sí). Se saltea si no hay Chromium.
- **Pendiente (F2 resto):** grilla de botones a los selects de mercado/hub/transporte/alianzas; `meta`.

## 5. Alcance incremental (fases)
- **F1 — base:** `icon:`/`symbol:` en YAML + toggle global + `ico()` + chip de material + ramas
  pictográficas en `costStr`/`affordText`/`reqLock` (costos y faltantes con ícono+letra+número). Cubre
  el pedido central de construir/entrenar/colas.
- **F2 — cobertura total + navegación sin leer:** grilla de botones-ícono para los `<select>`,
  toggle **por panel**, y aplicar el chip/íconos al **resto de los paneles** del §3 (atacar, combate,
  imperio, transitos, mercado/hub, eventos, etc.).
- **F3 — no-lectores totales (opcional):** sprite **SVG** propio (consistencia entre SO) y
  **lectura en voz alta (TTS)** al tocar un ícono (`speechSynthesis` con el `name` del catálogo,
  respetando el idioma) — para quien no lee **nada**, no solo "menos texto".

## 6. Tests (cuando se implemente)
- **e2e:** `/catalog` devuelve `icon` para minerales/unidades/edificios; alta de feature con happy
  path + un caso de error (ítem sin `icon` cae al fallback) — regla del proyecto.
- **front:** `node --check` de los `<script>`; el toggle persiste en `localStorage`; `affordText`
  pictográfico muestra el faltante numérico correcto; pictomode **no altera** qué se puede/no comprar
  (solo presentación).
- **regresión (invariante):** con el modo **apagado**, el DOM/textos de cada panel son **idénticos**
  a hoy (snapshot antes/después); apagar el modo tras usarlo **revierte** todo sin recargar.

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
