# SDD 55 — Inteligencia de la IA: tope de ataques por objetivo/día (anti-farmeo) + agresividad

> **Estado:** **IMPLEMENTADO (parcial)** 2026-06-29 — topes duros (por objetivo/día + entrante/día)
> HECHOS (aplican a humanos Y NPCs); el sesgo del cerebro NPC (§3.2) queda pendiente. · **Diseño:** 2026-06-29
> **Relacionado:** [SDD 29 inteligencia estratégica de NPCs](sdd-npc-strategic-intelligence.md)
> (perfiles + memoria + reflexión), [SDD 25 catch-up de novatos](sdd-newcomer-catchup.md),
> [SDD 53 balance](sdd-resource-balance.md), [SDD 54 bugs economía/defensa](sdd-economy-defense-bugs.md),
> `app/services/combat.py` (límite por ventana), `app/services/npc.py` (`pick_posture_rules`,
> `reflect_on_battle`, `PROFILES`), `app/core/config.py`.

## 1. Problema reportado (usuario, 2026-06-29)
"La IA parece muy agresiva; me ataca tanto que no me deja progresar. ¿Aprende/recuerda? ¿Hay un
límite de ataques por día a una persona? Debería tener una **capacidad de ataque por día** para evitar
abusos." → Una NPC (o varias) puede **farmear** a un mismo jugador hasta estrangularlo.

## 2. Estado actual (verificado)
- **Sí aprende/recuerda** (SDD 29 v2): memoria corta `Player.npc_memory` (últimas acciones),
  **postura persistente** `npc_posture` elegida por `pick_posture_rules` (determinista, lee
  scoreboard/amenazas/economía) y **`reflect_on_battle`** que cambia la postura tras pelear
  (perdés en casa → defensive; tu ataque falla → expand; ganaste atacando → raid). O sea: si gana
  atacándote, **tiende a seguir** (raid) → de ahí la sensación de acoso.
- **El único freno hoy** (1.103.0) es `attacks_per_window=3` cada `attack_window_seconds=14400` (4 h),
  contado **por atacante, sobre TODOS sus ataques** (`combat.py` cuenta `AttackMission` del atacante en
  la ventana, sin discriminar objetivo). ⇒ una NPC puede pegarle al **mismo** jugador hasta 3×/4 h ≈
  **18×/día**, y **varias** NPC pueden apilarse sobre la misma víctima. No hay tope **por objetivo**.
- Existe protección de novato (`_clear_protection` en tests; protección temporal al onboarding), pero
  no cubre a un jugador establecido que igual no puede progresar bajo acoso sostenido.

## 3. Diseño propuesto
### 3.1 Tope de ataques por objetivo y día (anti-farmeo) — el pedido central
- Nuevo límite **por par (atacante, defensor) en 24 h**: `attacks_per_target_per_day` (default **2**).
  Cuenta `AttackMission` con mismo `attacker_id` + `target_player_id` en las últimas 24 h; al llegar al
  tope, `start_attack` rechaza (humanos y NPCs). Evita el farmeo 1-a-1.
- Nuevo **tope de daño recibido por defensor/día** (defensa contra "pile-on" de varias NPC):
  `max_incoming_attacks_per_day` por jugador (default **6**) — más allá, los ataques entrantes a ese
  jugador se bloquean ("tu rival ya fue muy golpeado hoy"). Da aire para reconstruir.
- Ambos configurables por env (0 = sin límite, para no romper tests/escenarios).

### 3.2 Que la IA modere su agresividad (no solo el límite duro)
- En `pick_posture_rules`/`PROFILES`: bajar la propensión a `raid`/`aggressive` cuando la víctima está
  **mucho más débil** (no patear al que está en el piso) → preferir `expand`/`economy`. Anti-snowball.
- **Cooldown de objetivo en el cerebro NPC**: recordar (en `npc_memory`/estrategia) a quién atacó
  recientemente y **rotar de objetivo** en vez de insistir sobre el mismo → reparte la presión.
- Respetar SDD 25 (catch-up): no atacar a jugadores muy por debajo del promedio / recién golpeados.

### 3.3 Visibilidad (el usuario dijo "no puedo ver los ataques que hace la NPC")
- Que el panel de batallas (`/combat/battles`) y/o el journal muestren claramente los ataques
  entrantes con atacante + cuántos llevás hoy ("te atacaron 3/6 hoy"). Reusar SDD 51 (📈 Tu historia)
  para una serie de "ataques recibidos en el tiempo".

## 4. Tests / validación
- `test_combat.py` / e2e: el 3.º ataque del mismo atacante al mismo objetivo en 24 h se rechaza
  (`attacks_per_target_per_day=2`); el (N+1) ataque entrante a un defensor se rechaza
  (`max_incoming_attacks_per_day`).
- `test_npc.py`: con una víctima muy débil, `pick_posture_rules` NO elige raid contra ella; el NPC
  rota de objetivo si ya atacó al mismo recientemente.
- Invariante: estos topes aplican **igual** a humanos y NPCs (no asimetría explotable).

## 4.bis Implementación (2026-06-29)
- ✅ **Tope por objetivo/día** (`attacks_per_target_per_day=2`) y **entrante por defensor/día**
  (`max_incoming_attacks_per_day=6`) en `app/core/config.py` + `combat.py:start_attack` (cuenta
  `AttackMission` por (atacante,defensor) y por defensor en las últimas 24 h; 0 = sin límite). Aplican
  a humanos Y NPCs. e2e `test_attack_per_target_daily_cap_e2e`, `test_attack_incoming_daily_cap_e2e`;
  el e2e de ventana ya existente se aisló (apaga estos topes por monkeypatch).
- ⏳ **Pendiente (§3.2)**: sesgar `pick_posture_rules`/cerebro NPC a no patear al débil + cooldown/
  rotación de objetivo + más visibilidad de ataques recibidos. Los topes duros ya cortan el farmeo;
  el sesgo es refinamiento.

## 5. Rollout / riesgos
- Config + lógica acotada en `combat.py` (conteo por par/por defensor) y `npc.py` (sesgo + cooldown);
  aditivo. Va por el pipeline de Argo. e2e + tests de servicio (regla del proyecto).
- Riesgo: topes muy bajos vuelven el PvP inofensivo → arrancar conservador (2/día por par, 6/día
  entrante) y afinar con datos. Riesgo: un humano podría escudarse en el tope entrante para no recibir
  consecuencias → balancear con la duración (24 h) y que el saqueo siga existiendo bajo el tope.
