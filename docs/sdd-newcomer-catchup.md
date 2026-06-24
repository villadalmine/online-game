# SDD 25 — Catch-up del recién llegado (que no arranque en desventaja, sin dar ventaja)

> **Estado:** propuesto · **Fecha:** 2026-06-24 · **Autor:** equipo online-game
> **Relacionado:** [SDD 11 temporadas/newbie protection](sdd-game-lifecycle.md),
> [SDD 12 PlayerStats](sdd-player-metrics-public.md), [SDD 8 galaxias](sdd-galaxy-limits.md),
> [SDD 19 métricas](sdd-observability-metrics.md), `app/services/onboarding.py`.

## 1. Objetivo

Cuando un jugador entra a una partida que **ya lleva tiempo**, que no quede aplastado: darle lo
**básico** + **energía** para poder jugar, **proporcional** a los días transcurridos y a **cómo están
los demás** (leyendo las métricas/stats), de modo que esté **listo pero sin ventaja**. **Siempre
priorizar defensa.**

## 2. Diseño

### 2.1 Señales (leer el estado real, no inventar)
- **Antigüedad de la partida/temporada**: días desde el inicio (SDD 11) o edad mediana de los
  jugadores de **su galaxia** (SDD 8 — el baseline es por instancia, no global).
- **Baseline de pares**: de `PlayerStats` (SDD 12) + score (`player_score`) de los jugadores
  **humanos de su galaxia**, tomar un **percentil bajo-medio** (p.ej. P40), **no el top** (para no
  copiar al líder). Objetivo: dejar al nuevo cerca del **pelotón de atrás-medio**, no adelante.

### 2.2 El grant (proporcional + tope)
Al onboardear (una sola vez por cuenta), calcular un paquete:
- **Energía**: bastante para actuar ya (varias acciones), escalada por días/baseline.
- **Infra básica**: HQ + una **mina** + un edificio de producción básico (lo mínimo para no empezar
  de cero en una partida vieja).
- **Minerales**: un colchón ~ P40 de los pares (para construir lo inmediato).
- **Defensa PRIORIZADA**: torretas / edificio defensivo + (SDD 11) escudo de novato. **Nada o casi
  nada ofensivo** (sin flota de ataque) → puede **sobrevivir**, no **dominar**.
- **Proporción**: `grant = f(días, baseline_P40)`; partida joven ⇒ grant ~0; partida vieja con pares
  fuertes ⇒ grant mayor, **capeado a ≤ baseline** (nunca por encima de la mediana → cero ventaja).

### 2.3 Regla de oro
- **Equalizar, no boostear**: el tope es el percentil de pares; si quedara por encima, se recorta.
- **Defensa > ataque**: el grant favorece sobrevivir; el crecimiento ofensivo lo hace jugando.
- **Una vez por cuenta**; no acumulable; no aplica si la partida es nueva.

## 3. De dónde salen los datos
- DB: `PlayerStats` + `player_score` + `created_at` de los humanos de la galaxia (consulta directa
  en onboarding — barato, sin depender de Prometheus). Las métricas (SDD 19/21) sirven para
  monitorear el efecto (¿los nuevos sobreviven? ¿retención?), no como fuente crítica.

## 4. Implementación (propuesta)
- `app/services/catchup.py`: `compute_grant(session, player)` → lee baseline de la galaxia + días,
  devuelve {energy, minerals, buildings, defense} capeado. `apply_grant(...)` lo otorga.
- Hook en `onboarding.onboard_player` (después de crear la base): si la partida no es joven, aplicar.
- Config: `catchup_enabled`, `catchup_percentile` (0.4), `catchup_cap_ratio` (1.0 = nunca > baseline),
  `catchup_min_days` (umbral para que aplique).
- Marcar en `Player` que ya recibió catch-up (idempotente) — o inferir de `created_at` vs onboarding.

## 5. Tests
- Partida **joven** (sin pares / pocos días) ⇒ grant ~0.
- Partida **vieja** con pares fuertes ⇒ grant > 0, **defensivo** (torretas, no flota), y el
  resultado del nuevo **≤ baseline P40** (no supera a la mediana → sin ventaja).
- Idempotencia: no se otorga dos veces.
- Por galaxia: el baseline usa solo los pares de **su** instancia (SDD 8).

## 6. Riesgos / decisiones
- **Abuso** (crear cuentas para farmear el grant): cap por percentil + una vez + invite-only (SDD 14)
  lo limitan.
- **Inflación**: como el tope es relativo a los pares, el grant se autoajusta (no infla la economía).
- **Percentil**: P40 es punto de partida; ajustable por retención observada (métricas SDD 19/21).
- **Combina con SDD 11**: el escudo de novato cubre la ventana inicial; este SDD nivela el "stock".
