# SDD 77 — Consejero conversacional con memoria + mensajes proactivos

## Problema
El usuario pidió "hablar con la IA que tiene memoria del juego y de lo que hablás, pedirle cosas y que
evalúe si puede hacerlas, y que la IA te pueda **mandar un mensaje** sola".

## Qué ya existía (SDD 2/9/40)
El asistente (`app/services/advisor.py`) ya: responde grounded en el grafo del juego + intel, **guarda
el historial** (`AdvisorMessage`, `/advisor/messages`), **usa ese historial como contexto** del LLM
(memoria conversacional real), tiene modos gpu|cloud|byok, y **crea gratis** (hack) lo que le pedís
construir. Lo que faltaba era **verlo como chat** y que la IA **escriba sola**.

## Fase 1a — Chat con hilo (front)
- El panel 🧠 Asistente pasó de una sola respuesta a un **hilo de burbujas** (usuario/IA), scrollable,
  con la memoria visible. `askAdvisor` muestra tu mensaje optimista y agrega la respuesta;
  `loadAdvisorThread()` trae `/advisor/messages` al abrir/refrescar el panel.

## Fase 1b — Mensajes proactivos (la IA te escribe)
- `advisor.proactive_check(session, player)` — determinista, **no gasta LLM**, con **cooldown** por
  jugador (`advisor_proactive_cooldown_hours`, default 6h). Detecta situaciones notables:
  **ataque de flota o salva de misiles entrante** (`AttackMission`/`StrikeMission` con `defender_id`
  = vos y status `outbound`) y **energía crítica** (<8% del máximo). Guarda un mensaje con rol
  **`proactive`** (se ve como burbuja 🔔 y avisa con un toast "la IA te escribió").
- Se corre en el **tick del mundo** (`worker.run_tick`) para cada humano, guardado con try/except.
- El rol `proactive` se mapea a `assistant` al armar el prompt del LLM (la API solo acepta
  system/user/assistant).
- Flag `advisor_proactive_enabled` (default OFF; ON en `values-prod.yaml`).

## Pedir acciones ("evalúa si puede hacerlas")
Ya cubierto por el hack (crear/entrenar/investigar gratis, arma la cadena) + las `suggestions`
(acciones que gastan tus recursos). El teletransporte entre búnkeres (SDD 76) queda como acción a
enganchar al chat en v2.

## Tests
- `tests/test_advisor.py::test_proactive_writes_on_incoming_attack_with_cooldown` (escribe ante ataque
  entrante; respeta cooldown y flag).

## Fase 2 — La IA actúa desde el chat (confirmar de un clic)
- El asistente ya devolvía `suggestions` ejecutables (construir/entrenar/investigar) + `hack_targets`
  (crear gratis). Se sumó la acción **`teleport`**: si el mensaje pide mandar/teletransportar
  electrónica y tenés la capacidad (2+ búnkeres + Puerta cuántica activa), la IA propone un
  teletransporte **listo** (origen = búnker con puerta y más electrónica; destino = el más pobre;
  cantidad = mitad de la reserva) que ejecutás con un botón (`doSuggestion` → `POST /bunker/teleport`).
  El prompt del sistema ahora le dice a la IA **qué acciones puede ofrecer** ("que sepa cuáles tiene").
- `advisor._teleport_intent` / `_teleport_suggestion`. Tests: servicio
  (`test_teleport_suggestion_when_intent_and_capability`) + e2e
  (`test_advisor_offers_teleport_action_e2e`, cadena chat→sugerencia→ejecutar).

## Follow-ups (v3)
- Parsear cantidades/nombres del mensaje para teleport (hoy usa defaults sensatos).
- Más acciones desde el chat (evacuar, mover tropas, lanzar satélite).
- Más disparadores proactivos (bajo nuclear con diplomacia disponible, hitos).
- Mensaje proactivo con prosa del LLM (cloud) cuando haya presupuesto, cayendo al determinista.
