# Diseño del juego (bosquejo)

> Todos los valores numéricos son punto de partida ajustable en `content/*.yaml`.
> Datos de minerales basados en investigación real (fuentes al final).

## Concepto

Estrategia espacial **por turnos asíncrono**. Eliges una **galaxia** y un **planeta real**,
y te desarrollas con los **minerales que existen en ese mundo**. Construyes bases,
entrenas población, fabricas unidades pesadas, y a futuro luchas y exploras lunas
donde habitan **dioses** que te ayudan.

## Galaxias y planetas

- **Galaxia inicial:** Vía Láctea (extensible a más galaxias).
- **Planetas jugables:** Tierra, Marte, Venus. (Mercurio, lunas de Júpiter, etc. = futuro.)
- Cada planeta tiene un **modificador de abundancia** por mineral (`content/planets.yaml`),
  que multiplica la producción de las minas.

## Minerales (recursos in-game ↔ minerales reales)

| In-game | Real | Abundante en |
|---|---|---|
| Hierro | Hierro / feldespato | Tierra, Marte |
| Silicio | Silicatos / cuarzo | Todos |
| Aluminio | Plagioclasa | Tierra |
| Titanio | Ilmenita (FeTiO₃) | Luna, Venus |
| Azufre | Jarosita / pirita | Venus, Marte |
| Magnesio | Olivino / MgO | Marte |
| Roca basáltica | Basalto / piroxeno | Marte, Venus |
| Helio-3 | Regolito lunar + ilmenita | Luna (endgame) |
| Tierras raras (KREEP) | K, REE, P | Luna |
| Hielo de agua | Condrita carbonácea | Fobos / Deimos |

## Razas (3 terrestres iniciales)

| Raza | Planeta | Mineral estructural | Energético | Avanzado | Bonus |
|---|---|---|---|---|---|
| Terrícolas | Tierra | Hierro | Silicio | Aluminio | economía, trabajadores |
| Marcianos | Marte | Hierro | Azufre | Magnesio | combate, unidades pesadas |
| Venusianos | Venus | Basalto | Azufre | Titanio | ciencia, defensa |

**Mecánica clave (extensible):** las recetas piden roles abstractos
(`structural`/`energetic`/`advanced`); cada raza resuelve el rol → mineral en
`content/races.yaml`. Cambiar el mineral de una raza = un solo valor.

## Edificios

Base central (HQ), Mina (extrae un mineral), Planta de energía, Cuartel (militares),
Taller/Fábrica (unidades pesadas), Laboratorio (ciencia). Cada edificio tiene costo en
roles + costo de energía + tiempo de construcción (`content/buildings.yaml`).

## Población y unidades

- **Personajes:** trabajadores, militares, científicos (extensible: espías, ingenieros…).
- **Unidades pesadas (difieren por raza):** tanques, barcos, aviones, transbordadores.
- **Entrenamiento implementado:** cada unidad cuesta energía + minerales (resueltos por
  raza) y requiere su edificio activo (`requires`); entra a una cola y se entrega al
  cumplirse el timer.
- **Combate PvP con viaje/tiempo:** atacás la base de otro comprometiendo una fuerza que
  **viaja** (tiempo según distancia entre planetas). Las unidades se bloquean en tránsito;
  el defensor ve el ataque entrante y tiene **ventana para reaccionar**. Al llegar se
  resuelve con `stats` + bonus de raza + boons; hay bajas y **botín**. Los sobrevivientes y
  el botín **regresan** a la base. Historial en `/combat/reports`.
- **Guerra intra-planeta (SDD 49/50, implementado):** dos vías de "golpe" que **no salen del
  planeta**, paralelas a la flota, para **ablandar** una base rival antes de atacarla:
  - **Misiles** (lanzadera `launcher` + sónico→transatlántico→nuclear, tech-gated): una salva
    vuela a una base del mismo planeta; las **torretas** la interceptan con una fórmula
    determinista (enjambre satura, nuclear casi imparable + área/fallout). El daño **destruye
    edificios** (no saquea).
  - **Drones** (fábrica `drone_factory` + espía/ataque): un escuadrón **orbita** una base del
    planeta dando **intel en vivo**; drena tu energía y cae ante torretas (todo *lazy* por
    timestamp). Los de ataque castigan la base por tick; podés **retirarlos** antes de que mueran.
  - Frenos: protección de novato, no se ataca a aliados, tope de alojamiento y drenaje de energía.

## Lunas y dioses

Los **dioses** viven en las lunas y conceden boons / recursos premium vía expediciones
(**implementado**: enviás una expedición, cuesta energía + transbordador, y al volver
entrega los recursos y un boon temporal):

- **Tierra → Luna:** He-3 / tierras raras + boon de producción.
- **Marte → Fobos y Deimos:** hielo de agua + boon de defensa / producción.
- **Venus → no tiene luna natural.** Usamos su **cuasi-satélite real "Zoozve" (2002 VE68)**
  como dios mítico comodín (titanio + He-3, boon de ataque). (Easter egg fiel a la realidad.)

## Bucle de juego

1. La **energía** regenera cada hora hasta un tope (cálculo *lazy* por timestamp).
2. Construir/entrenar cuesta **energía + minerales** y entra a una **cola** con temporizador.
3. Las **minas** producen minerales con el tiempo (también *lazy*).
4. Un **tick** periódico resolverá combate, boons de dioses y turnos de razas NPC (IA).

## Razas NPC con IA (implementado)

Bots como jugadores reales (uno por raza) que toman una acción por tick vía los mismos
sistemas que un humano (construir/entrenar/atacar). Cerebro **enchufable**: por defecto
reglas (heurística determinista, gratis y sin red); opcionalmente un LLM vía **OpenRouter**
(`NPC_BRAIN=llm`, modelo free por defecto) con **fallback a reglas** ante cualquier fallo.
La IA es un proveedor intercambiable, desacoplado del motor.

## Roadmap (iteración 2+)

Ataques con viaje/tiempo, cerebro LLM con personalidad/memoria por raza,
notificaciones (WebSocket), bot de Telegram. Todo aditivo: **extender, no romper**.

## Fuentes

- Corteza terrestre: sandatlas.org; Visual Capitalist.
- Marte: Marspedia (Surface composition); Ehlmann & Edwards 2014.
- Venus: Mineralogy of the Venus Surface (Springer); Britannica.
- Luna: Nature (helium reservoirs); Grokipedia (lunar resources).
- Fobos/Deimos: MDPI (Phobos review); NASA NTRS.
