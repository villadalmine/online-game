# SDD 54 — Bugs de economía/defensa: staffing de minas, torreta que no defiende, piso de trabajadores

> **Estado:** **diseño** (no implementado) · **Fecha:** 2026-06-29
> **Relacionado:** [SDD 47 minería/trabajadores/silos](sdd-mining-workers-storage.md),
> [SDD 46 alojamiento](sdd-unit-housing-capacity.md), `app/services/combat.py` (resolución de ataque),
> `app/services/production.py` / `app/services/state.py` (producción lazy + staffing),
> `content/units.yaml` (worker), `content/buildings.yaml` (turret), `tests/test_mining.py`,
> `tests/test_combat.py`.

## 1. Problemas reportados (usuario, 2026-06-29)
Tres bugs/inconsistencias que dejan al jugador **trabado y vulnerable**:

1. **Las minas juntan material sin trabajadores.** "Si no tengo worker igual las minas siguen
   juntando materiales." El staffing (SDD 47) tiene un **piso** `mining_staffing_floor=0.34` → una
   mina sin obreros igual rinde ~34%. Se diseñó como gracia para no zerear a novatos, pero hace que
   los trabajadores "no se sientan necesarios" y rompe la intuición (sin gente no debería producir, o
   muy poco).
2. **La torreta no cuenta como defensa al ser atacado.** "Tengo torreta pero si me atacan no cuenta
   como defensa." La torreta aporta `defense_power` solo si está **`active`** y **en la base
   exactamente atacada** (`combat.py` suma `defense_power` de los `Building` con
   `base_id == target_base_id, status == "active"`). Sospechas a confirmar: (a) la torreta está en
   OTRA base/planeta del jugador y el ataque pega en una base sin torreta; (b) la torreta quedó
   `building`/no `active`; (c) el cálculo se aplica pero el atacante la supera y el usuario no ve el
   aporte reflejado. **Hay que reproducir y confirmar la causa real antes de tocar nada.**
3. **Te quedás sin trabajadores tras varios ataques → trabado.** "Si me atacan tanto me quedo sin
   trabajadores; debería quedarme siempre con un mínimo para seguir juntando materiales, sino quedo
   trabado y puedo perder." Si el combate mata TODAS las unidades del defensor (incluidos workers),
   te quedás sin economía → no podés reconstruir → muerte por estrangulamiento.

> Nota: este SDD se cruza con [SDD 53](sdd-resource-balance.md) (defensa siempre pagable con el
> mineral estructural) y [SDD 55](sdd-npc-aggression-limits.md) (que la IA no te farmee). Los tres
> juntos buscan que **nunca quedes en un pozo sin salida**.

## 2. Diseño propuesto
### 2.1 Staffing real de minas (bug 1)
- Bajar el piso: `mining_staffing_floor` de **0.34 → ~0.10** (sin obreros, una mina rinde 10%: simbólico,
  no cero, pero claramente "necesitás gente"). Configurable por env (no hardcodear).
- Que la UI muestre el **% de staffing** por mina y el faltante de obreros (ya hay panel Economía SDD 47;
  reforzar el mensaje "mina al X% — asigná N obreros").
- Invariante: con obreros completos rinde 100%; sin obreros, exactamente `floor` (test).

### 2.2 La torreta defiende de verdad (bug 2) — primero REPRODUCIR
- Test e2e que ataca una base **con** torreta `active` y verifica que `flat_defense` ≥ `defense_power`
  de la torreta y que cambia el resultado vs la misma base sin torreta.
- Si el bug es "torreta en otra base": decidir diseño — ¿la defensa es **por base** (realista, hay que
  defender cada base) o se suma una fracción de la defensa global? Propuesta: **por base** (mantener),
  pero la UI debe avisar "esta base no tiene defensas" y el asistente sugerir torretas por base.
- Si el bug es de estado/`active`: arreglar el filtro o el flujo de finalización de la torreta.

### 2.3 Piso de trabajadores que sobrevive al combate (bug 3)
- **Protección de economía mínima**: el combate **nunca** puede dejar al defensor con menos de
  `min_surviving_workers` (p.ej. 2) trabajadores. Las pérdidas de combate se aplican primero a unidades
  militares y, sobre los workers, se respeta el piso (los últimos N no mueren / no son capturados).
- Configurable por env (`min_surviving_workers`, default 2; 0 = sin piso para no romper escenarios).
- Razón de diseño: garantiza que **siempre puedas volver a juntar material** y reconstruir → no hay
  "game over silencioso" por estrangulamiento. Se alinea con el catch-up (SDD 25) y con SDD 53.
- Alternativa/refuerzo: que los workers sean **no-combatientes** (no cuentan como defensa ni se
  pierden en combate salvo saqueo), separando "economía" de "ejército". A evaluar (cambia balance).

## 3. Tests / validación
- `test_mining.py`: con 0 obreros, output == `floor` exacto; con obreros completos, 100%.
- `test_combat.py`: torreta `active` en la base atacada sube `flat_defense`; cambia el outcome.
- e2e (`test_api_e2e.py`): construir torreta → ser atacado → la defensa cuenta (no cae como si no
  hubiera nada). Ataque masivo a un defensor → **siempre** le quedan ≥ `min_surviving_workers`.

## 4. Rollout / riesgos
- Mayormente config + ajustes acotados en `combat.py`/producción; aditivo. Va por el pipeline de Argo.
- Riesgo: bajar el floor encarece el early-game → balancear con `make balance` y datos.
- Riesgo: el piso de workers puede ser explotado (esconder economía detrás de 2 workers intocables);
  mitiga que el saqueo de **minerales** sí siga (solo se protege la **capacidad de seguir jugando**).
