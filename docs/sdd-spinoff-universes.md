# SDD 26 — Universos spin-off (Star Trek / Battlestar Galactica / Star Wars) como packs de datos

> **Estado:** propuesto (SOLO especificación de datos — NO implementar todavía) · **Fecha:** 2026-06-24
> **Relacionado:** [SDD 13 §3.9 universos](sdd-scientific-accuracy.md), [SDD 4 i18n](sdd-i18n.md),
> [SDD 8 galaxias](sdd-galaxy-limits.md), [SDD 11 temporadas](sdd-game-lifecycle.md),
> `content/{planets,units,minerals,buildings}.yaml`.

## 0. Cómo usar este SDD
Este documento **es la fuente de verdad de los datos** de los packs spin-off. **No se implementa
acá**: cuando quieras meterlos al juego, se traducen 1:1 a YAML siguiendo el modelo de objetos de
abajo. Si querés cambiar un dato, **se edita este SDD primero** y después el YAML. Todo
**data-as-code, tipado y human-readable** (mismo schema que el contenido vigente).

## 1. Objetivo
Permitir **universos seleccionables por partida** (galaxy instance / temporada, SDD 8/11) ambientados
en franquicias, con mundos, naves y unidades **fieles al canon** de cada una. El motor **no cambia**:
solo se agrega un pack de contenido. Todo tagueado `canon: fiction` + `universe: <nombre>` + `sources`
(wikis de la franquicia) — nunca se confunde con dato científico real.

## ⚠️ 2. Nota legal / IP (importante)
Star Trek, Battlestar Galactica y Star Wars son **marcas registradas de terceros** (Paramount,
Universal/NBCU, Lucasfilm/Disney). Este pack es **homenaje/fan content**: úsese solo en contexto
**no comercial** (coherente con SDD 11: sin monetización) o con permiso. Para publicar sin riesgo,
**modo "genérico"** recomendado: nombres alterados (p.ej. "Crucero de la Federación" en vez de "USS
Enterprise") manteniendo el espíritu. El pack se marca `licensing: fan-noncommercial`.

## 3. Modelo de objetos (idéntico al contenido vigente, + campos de universo)
Cada entidad reutiliza el schema actual y suma `universe`, `canon: fiction`, `sources` y (si es
inventado) `rationale`. i18n con `*_en` (SDD 4).

- **Mundo** (= `planets.yaml`): `key, name, name_en, system, universe, canon: fiction, sources,
  gravity_g, mean_temp_c, atmosphere(none|thin|thick), has_liquid_water, insolation, abundance{mineral:mult}, moons[], description`.
- **Material** (= `minerals.yaml`): `key, name, real("contraparte/lore"), description, universe, canon`.
- **Nave/Unidad** (= `units.yaml` categoría nueva `starship`): `key, name, category(fighter|capital|super|support),
  universe, requires(building activo), energy_cost, train_seconds, cost{roles o materiales},
  stats{attack,defense,hp}, propulsion(warp|ftl_jump|hyperdrive|sublight|impulse), sources, faction`.
- **Edificio/astillero** (= `buildings.yaml`): `key, name, category(shipyard|defense|...), universe`.

> Estructura física: `content/universes/<universe>/{minerals,planets,units,buildings}.yaml`, o un
> campo `universe` por entidad en los YAML actuales. El universo se elige por galaxy instance /
> temporada (un pack por partida). El default sigue siendo el universo "hard-real" (Sistema Solar +
> exosistemas, SDD 13).

---

## 4. Pack `star_trek` (canon: fiction · sources: Memory Alpha)
### Materiales
```yaml
- key: dilithium
  name: "Dilithium"
  real: "Cristal regulador del núcleo de curvatura (lore Trek)"
  description: "Energía/propulsión avanzada (warp)."
  universe: star_trek
  canon: fiction
- key: latinum
  name: "Latinum líquido"
  real: "Moneda/recurso ferengi (lore)"
  description: "Recurso premium de comercio."
  universe: star_trek
  canon: fiction
```
### Mundos
```yaml
- key: vulcan
  name: "Vulcano"
  system: "40 Eridani (lore)"
  universe: star_trek
  canon: fiction
  gravity_g: 1.4          # mundo más pesado que la Tierra (lore)
  mean_temp_c: 45         # desértico, cálido
  atmosphere: thin
  has_liquid_water: false
  insolation: 1.3
  abundance: { iron: 1.2, silicon: 1.0, titanium: 1.1, sulfur: 0.8, dilithium: 1.2 }
  moons: []
  sources: ["Memory Alpha: Vulcan"]
- key: qonos
  name: "Qo'noS (Kronos)"
  system: "Sistema Klingon (lore)"
  universe: star_trek
  canon: fiction
  gravity_g: 1.1
  mean_temp_c: 12
  atmosphere: thick
  has_liquid_water: true
  insolation: 0.9
  abundance: { iron: 1.5, basalt: 1.3, sulfur: 1.2, dilithium: 0.8 }
  moons: [praxis]
  sources: ["Memory Alpha: Qo'noS"]
```
### Naves
```yaml
starship:
  - key: federation_cruiser   # homenaje a Galaxy-class
    name: "Crucero de la Federación"
    universe: star_trek
    category: capital
    requires: shipyard
    propulsion: warp
    energy_cost: 60
    train_seconds: 900
    cost: { structural: 400, advanced: 300, dilithium: 50 }
    stats: { attack: 70, defense: 90, hp: 400 }
    faction: federation
    sources: ["Memory Alpha: Galaxy class"]
  - key: bird_of_prey         # Klingon, sigiloso
    name: "Ave de Presa"
    universe: star_trek
    category: fighter
    requires: shipyard
    propulsion: warp
    energy_cost: 30
    train_seconds: 300
    cost: { structural: 120, advanced: 80, dilithium: 15 }
    stats: { attack: 55, defense: 30, hp: 120 }
    faction: klingon
    sources: ["Memory Alpha: Bird-of-Prey"]
  - key: borg_cube            # super, raro/endgame
    name: "Cubo Borg"
    universe: star_trek
    category: super
    requires: shipyard
    propulsion: warp
    energy_cost: 200
    train_seconds: 3600
    cost: { structural: 1500, advanced: 1200, dilithium: 300 }
    stats: { attack: 200, defense: 220, hp: 2000 }
    faction: borg
    sources: ["Memory Alpha: Borg cube"]
```

## 5. Pack `bsg` (Battlestar Galactica · sources: Battlestar Wiki)
### Materiales
```yaml
- key: tylium
  name: "Tylium"
  real: "Mineral refinado a combustible de salto FTL (lore BSG)"
  description: "Combustible de naves / FTL."
  universe: bsg
  canon: fiction
```
### Mundos (las Doce Colonias + Kobol)
```yaml
- key: caprica
  name: "Caprica"
  system: "Cyrannus (lore)"
  universe: bsg
  canon: fiction
  gravity_g: 1.0
  mean_temp_c: 16
  atmosphere: thick
  has_liquid_water: true
  insolation: 1.0
  abundance: { iron: 1.2, silicon: 1.3, aluminum: 1.1, tylium: 0.6 }
  moons: []
  sources: ["Battlestar Wiki: Caprica"]
- key: kobol
  name: "Kobol"
  system: "Cyrannus (lore)"
  universe: bsg
  canon: fiction
  gravity_g: 1.0
  mean_temp_c: 14
  atmosphere: thick
  has_liquid_water: true
  insolation: 1.0
  abundance: { iron: 1.0, basalt: 1.2, tylium: 0.8 }
  moons: []
  sources: ["Battlestar Wiki: Kobol"]
```
### Naves
```yaml
starship:
  - key: battlestar
    name: "Battlestar"
    universe: bsg
    category: capital
    requires: shipyard
    propulsion: ftl_jump
    energy_cost: 70
    train_seconds: 1000
    cost: { structural: 500, advanced: 250, tylium: 80 }
    stats: { attack: 80, defense: 100, hp: 500 }
    faction: colonial
    sources: ["Battlestar Wiki: Battlestar"]
  - key: viper
    name: "Viper Mk II"
    universe: bsg
    category: fighter
    requires: shipyard
    propulsion: sublight
    energy_cost: 12
    train_seconds: 120
    cost: { structural: 60, energetic: 30, tylium: 8 }
    stats: { attack: 35, defense: 15, hp: 40 }
    faction: colonial
    sources: ["Battlestar Wiki: Viper"]
  - key: cylon_raider
    name: "Raider Cylon"
    universe: bsg
    category: fighter
    requires: shipyard
    propulsion: sublight
    energy_cost: 12
    train_seconds: 110
    cost: { structural: 55, advanced: 35, tylium: 8 }
    stats: { attack: 38, defense: 12, hp: 38 }
    faction: cylon
    sources: ["Battlestar Wiki: Cylon Raider"]
```

## 6. Pack `star_wars` (canon: fiction · sources: Wookieepedia)
### Materiales
```yaml
- key: kyber
  name: "Cristal Kyber"
  real: "Cristal energético (sables/superláser, lore SW)"
  description: "Energía/armamento avanzado."
  universe: star_wars
  canon: fiction
- key: beskar
  name: "Beskar"
  real: "Aleación mandaloriana (lore)"
  description: "Blindaje superior."
  universe: star_wars
  canon: fiction
```
### Mundos
```yaml
- key: tatooine
  name: "Tatooine"
  system: "Sistema Tatoo (binario)"
  universe: star_wars
  canon: fiction
  gravity_g: 1.0
  mean_temp_c: 40         # desierto, dos soles
  atmosphere: thin
  has_liquid_water: false
  insolation: 1.7
  abundance: { silicon: 1.5, iron: 0.8, titanium: 0.7 }
  moons: [ghomrassen, guermessa]
  sources: ["Wookieepedia: Tatooine"]
- key: hoth
  name: "Hoth"
  system: "Sistema Hoth"
  universe: star_wars
  canon: fiction
  gravity_g: 1.1
  mean_temp_c: -60        # mundo helado
  atmosphere: thin
  has_liquid_water: false # hielo, no líquido
  insolation: 0.4
  abundance: { iron: 1.3, titanium: 1.0, silicon: 0.9 }
  moons: []
  sources: ["Wookieepedia: Hoth"]
- key: coruscant
  name: "Coruscant"
  system: "Sistema Coruscant"
  universe: star_wars
  canon: fiction
  gravity_g: 1.0
  mean_temp_c: 18
  atmosphere: thick
  has_liquid_water: true
  insolation: 1.0
  abundance: { iron: 1.4, aluminum: 1.5, silicon: 1.4 }   # ecumenópolis: alto refinado
  moons: []
  sources: ["Wookieepedia: Coruscant"]
```
### Naves
```yaml
starship:
  - key: x_wing
    name: "Caza X-wing"
    universe: star_wars
    category: fighter
    requires: shipyard
    propulsion: hyperdrive
    energy_cost: 14
    train_seconds: 130
    cost: { structural: 60, energetic: 30, kyber: 6 }
    stats: { attack: 40, defense: 18, hp: 45 }
    faction: rebel
    sources: ["Wookieepedia: T-65 X-wing"]
  - key: tie_fighter
    name: "Caza TIE"
    universe: star_wars
    category: fighter
    requires: shipyard
    propulsion: sublight       # TIE base sin hiperimpulsor
    energy_cost: 8
    train_seconds: 80
    cost: { structural: 35, energetic: 25 }
    stats: { attack: 36, defense: 8, hp: 25 }
    faction: empire
    sources: ["Wookieepedia: TIE/ln"]
  - key: star_destroyer
    name: "Destructor Estelar"
    universe: star_wars
    category: capital
    requires: shipyard
    propulsion: hyperdrive
    energy_cost: 90
    train_seconds: 1200
    cost: { structural: 700, advanced: 400, kyber: 60 }
    stats: { attack: 110, defense: 120, hp: 700 }
    faction: empire
    sources: ["Wookieepedia: Imperial-class Star Destroyer"]
  - key: death_star
    name: "Estación de batalla"   # homenaje genérico (Death Star)
    universe: star_wars
    category: super
    requires: shipyard
    propulsion: hyperdrive
    energy_cost: 300
    train_seconds: 5400
    cost: { structural: 3000, advanced: 2000, kyber: 500 }
    stats: { attack: 350, defense: 300, hp: 4000 }
    faction: empire
    sources: ["Wookieepedia: Death Star"]
```

## 7. Selección de universo + facciones
- **Por galaxy instance / temporada** (SDD 8/11): cada partida corre UN universo (`universe` field
  en la instancia). El catálogo se filtra por ese universo. Default = hard-real (SDD 13).
- **Facciones** (`faction`) podrían mapear a razas/alianzas del universo (federation/klingon/borg;
  colonial/cylon; rebel/empire) — follow-up; v1 del pack puede ignorar facción (solo sabor).
- **Materiales del pack** (dilithium/tylium/kyber) se suman como minerales premium; las naves los
  piden en `cost` (igual que He-3/KREEP hoy).

## 8. Implementación (cuando se decida — NO ahora)
- Traducir cada bloque a `content/universes/<universe>/*.yaml`; el registry carga el pack del
  universo activo; `units.yaml` gana la categoría `starship`; `buildings.yaml` gana `shipyard`.
- Tests: el pack valida contra el schema (canon=fiction ⇒ sources; campos físicos presentes;
  costos referencian minerales existentes del pack); e2e: `/catalog?universe=star_wars` expone Hoth.
- i18n `*_en` para todos los textos. Multiplicadores físicos (SDD 13 §4) aplican igual (gravedad,
  insolación, atmósfera/agua para gating de unidades planetarias; las naves espaciales no gatean).

## 9. Riesgos / decisiones
- **IP** (§2): modo genérico recomendado para publicar; nombres exactos solo fan/no-comercial.
- **Balance**: stats relativos al juego actual (no a "poder canónico"); ajustable en este SDD.
- **Alcance**: arrancar con 1 pack (el favorito) y pocos mundos/naves; crecer editando este SDD.
- **Físico vs. ficción**: todo `canon: fiction`; los datos son **fieles al lore**, no físicos reales.
