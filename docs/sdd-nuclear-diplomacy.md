# SDD 67 — Diplomacia nuclear: el nuclear tarda 24 h y el defensor puede comprar la cancelación

> **Estado:** **IMPLEMENTADO** 2026-07-02 (1.130.0): edificio `government` + tech `diplomacy` (cat
> `politics`) + el nuclear viaja 24 h (`nuclear_travel_seconds`) + `offer_tribute`/`accept_tribute`
> (`/combat/strike/{id}/tribute` y `.../accept-tribute`) + migración `79fc068c4f1e`
> (`StrikeMission.tribute`). Sin recall unilateral. **v2 balance (1.137.0):** el nuclear necesita **10
> torretas** para bloqueo total (`intercept_cost` 100) y con menos **impacta PARCIAL al 50%**
> (`strike_partial_impact_factor`, intercepción parcial en `simulate_strike`); al **aceptar el tributo
> el misil VUELVE al hangar** del atacante (no se pierde). **Pendiente menor:** gobierno "y más cosas"
> (tratados) en v3. · **Pedido:** usuario.
> **Relacionado:** [SDD 49 misiles](sdd-missile-launcher.md) (salvas + intercepción), [SDD 53 balance
> por rol](sdd-resource-balance.md), `app/services/strike.py`, `content/{technologies,buildings}.yaml`.

## 1. Pedido (usuario, 2026-07-02)
- Un **misil nuclear tarda 24 h en llegar** (hoy viaja como cualquier salva). **No se puede cancelar.**
- PERO: si el **defensor tiene la diplomacia desarrollada**, puede **enviarle mercaderías y energía al
  atacante** para que ÉL cancele el misil (comprar la paz).
- La **diplomacia hay que desarrollarla** (research) y requiere un **edificio de gobierno**, que sirve
  para eso "y más cosas" (futuro: tratados, pactos de no agresión, embajadas…). Por ahora, esto.

## 2. Diseño
### 2.1 Contenido (data-driven)
- **Edificio `government`** ("Edificio de gobierno", categoría nueva `politics`): requiere
  `research_lab`. Base de la política del imperio (v1: habilita investigar diplomacia; v2: tratados).
- **Tech `diplomacy`** ("Diplomacia", categoría `politics`): `requires: government`. Habilita ofrecer
  tributo ante un nuclear entrante (y futuras acciones diplomáticas).
### 2.2 El nuclear viaja 24 h (ventana de negociación)
- Config `nuclear_travel_seconds = 86400`: una salva que incluya `nuclear_missile` llega en 24 h
  (las demás salvas siguen con el viaje normal). El atacante NO puede retirarla (no hay recall de
  misiles) → la única salida es el tributo.
### 2.3 Tributo (comprar la cancelación)
- **Defensor** (con `diplomacy` investigada + `government` ACTIVO): `POST /combat/strike/{id}/tribute
  {minerals:{k:v}, energy}` sobre una salva nuclear ENTRANTE → la oferta queda en la misión y el
  atacante es notificado. Se valida que el defensor TENGA esos recursos (en su planeta natal).
- **Atacante**: ve la oferta en su salva en vuelo; `POST /combat/strike/{id}/accept-tribute` →
  transfiere minerales (natal defensor → natal atacante) + energía (hasta el tope del atacante), la
  salva pasa a `cancelled` y ambos son notificados. Si no acepta, el misil sigue su curso.
- El tributo se descuenta AL ACEPTAR (re-validado); si el defensor ya no lo tiene, la aceptación falla.
### 2.4 UI
- El defensor ve la **salva nuclear entrante** (nuevo `strikes_incoming` en el snapshot con countdown
  ☢) y, si tiene diplomacia, el mini-form de tributo (mineral + cantidad + energía → 🕊 ofrecer).
- El atacante ve en su lista de salvas la **oferta** (💰 …) con el botón **aceptar** (cancela).

## 3. Tests
- Servicio: el nuclear viaja 24 h; ofrecer exige diplomacia+gobierno y recursos; aceptar transfiere y
  cancela; no se puede ofrecer sobre salvas no nucleares/ya resueltas; re-validación al aceptar.
- e2e: lanzar nuclear → defensor ofrece → atacante acepta → misil cancelado + recursos movidos; error
  sin la tech (400).

## 4. Rollout / riesgos
- Aditivo, sin flag (gateado por research/edificio nuevos; el cambio de viaje del nuclear es global
  pero le DA una defensa al que no tiene torretas — antes no había ventana). Por el pipeline de Argo.
- Riesgo: pagar tributo como meta-farmeo (lanzo nuclear para cobrar) → mitigan: el tope de salvas por
  alojamiento, el costo del nuclear (750 por rol + fisión) y que el tributo lo fija el DEFENSOR.
