# SDD 4 — i18n del juego (ES/EN)

> **Estado:** **implementado** (en producción) · **Fecha:** 2026-06-22 · **Autor:** equipo online-game
> **Ámbito:** el **juego** (contenido visible + chrome del cliente web). **No** docs ni SDDs.

## 1. Objetivo

Que el juego se vea en **español o inglés**. Dos superficies:

1. **Contenido data-driven** (`content/*.yaml`): nombres y descripciones de minerales, planetas,
   galaxias, razas, edificios, unidades, lunas, tecnologías y tipos de alianza.
2. **Chrome del cliente web**: títulos de paneles, botones y etiquetas fijas.

Default **español** (lo que hay hoy). Aditivo y sin romper: el idioma actual sigue siendo el
fallback si falta una traducción.

### No-objetivos (follow-ups, cada uno con su SDD si se hace)
- Notificaciones / mensajes de combate / prosa del asistente (texto dinámico del server).
- CLI. La `personality`/`taunts` de las NPC (no son UI; son comportamiento del modelo).

## 2. Diseño

### 2.1 Contenido: campos `_en` aditivos
Cada objeto de `content/*.yaml` mantiene su `name`/`description`/`real` actuales **como ES
(default)** y suma variantes en inglés con sufijo **`_en`**:

```yaml
- key: mine
  name: "Mina"
  name_en: "Mine"
  description: "Extrae un mineral del planeta..."
  description_en: "Extracts a mineral from the planet..."
```

Regla de resolución: para `lang="en"`, usar `<campo>_en` si existe; si no, caer al campo base
(ES). Para `lang="es"` (o cualquier otro), usar el campo base. **Cambiar/añadir un idioma = editar
YAML**, fiel al principio data-driven.

### 2.2 Capa de localización (registry)
`app/content/registry.py` gana un helper **puro**:

```python
LOCALIZED_FIELDS = ("name", "description", "real")
def localize(obj: dict, lang: str) -> dict:
    """Shallow copy with localized fields swapped in for `lang`; drops the *_en helper keys."""
```

Y `localize_catalog(catalog: dict, lang)` que aplica `localize` a cada item de cada colección,
incluyendo los **planetas anidados** dentro de `galaxies`. Determinista, sin estado.

### 2.3 API: selección de idioma (full-API)
El catálogo es la superficie de contenido que el front renderiza. Se parametriza por idioma:

```
GET /api/v1/catalog?lang=en        # explícito (gana)
GET /api/v1/catalog                # usa Accept-Language; default es
```

- `lang` ∈ {`es`,`en`}; cualquier otro → `es`. Precedencia: `?lang=` > `Accept-Language` > `es`.
- **Cache Redis por idioma**: clave `catalog:v1:<lang>` (degradable si no hay Redis).
- El resto de endpoints no cambian (v1). El grafo/RAG siguen en su idioma base (consumo LLM).

### 2.4 Cliente web: toggle + chrome
- **Toggle 🌐 ES/EN** en el header, persistido en `localStorage["lang"]` (como sonido/paneles).
- Al cambiar: recarga el catálogo con `?lang=` (así todos los nombres/descripciones renderizados
  desde el catálogo cambian) y reaplica el chrome.
- **Chrome**: diccionario JS `I18N = { es:{...}, en:{...} }` para textos fijos. Los elementos
  fijos llevan `data-i18n="<clave>"`; `applyI18n()` setea su `textContent`. Cubre títulos de
  paneles y botones principales.

## 3. Plan de tests (regla del proyecto)
**E2E HTTP** (`tests/test_api_e2e.py`):
- `GET /catalog?lang=en` → nombres en inglés (p.ej. building `mine` → "Mine"); `?lang=es` y sin
  query → español; `lang` inválido → español.
- (unit) `registry.localize` cae al campo base cuando falta el `_en`.

**Browser** (`tests/browser/`):
- Toggle a EN: un título de panel y un nombre de catálogo aparecen en inglés; persiste tras
  recargar; volver a ES restaura.

## 4. Riesgos / decisiones
- **Cobertura parcial de traducción**: si falta un `_en`, se ve el ES (degradación visible pero
  no rota). Se completa editando YAML.
- **Texto dinámico del server** (notis/combate/asistente) queda en ES en v1 (follow-up). El
  asistente podría recibir el idioma como instrucción al LLM más adelante.
- **Cache**: por idioma; nunca depende de Redis para funcionar.

## 5. Impacto
- `content/*.yaml` (+ campos `_en`), `app/content/registry.py` (+`localize*`),
  `app/api/v1/catalog.py` (param `lang`), `web/index.html` (toggle + `data-i18n` + dict).
- Sin migraciones, sin modelos, sin deps nuevas.
