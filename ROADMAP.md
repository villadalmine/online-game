# Roadmap

Dónde estamos y qué sigue. El detalle cronológico de cada cambio está en
[`CHANGELOG.md`](CHANGELOG.md).

## ✅ Hecho (jugable hoy)

**Núcleo**
- API-first (FastAPI), web + CLI consumiendo la misma API.
- Contenido 100% data-driven en `content/*.yaml` (minerales, planetas, razas, edificios,
  unidades, lunas/dioses, tecnologías, tipos de alianza).
- Estado *lazy* por timestamp; **tick del mundo** automático (`AUTO_TICK_SECONDS`) + `/admin/tick`.
- DB SQLite (local) / Postgres (Docker); **migra sola al arrancar** (Alembic), sin reset manual.

**Juego**
- Onboarding: galaxia → planeta → raza. 2 galaxias (Vía Láctea + Andrómeda), 5 planetas, 3 razas.
- Economía: energía horaria, minas que producen por timestamp, recursos por raza.
- Construcción de edificios y entrenamiento de unidades (con colas/temporizadores).
- **Combate con viaje**: flotas que viajan, resuelven al llegar y vuelven con sobrevivientes+botín;
  **recall**; torretas/defensa de base; defensa mutua de alianza.
- **Expediciones** a lunas → recursos premium + boons de dioses.
- **Investigación/tecnologías** (bonus permanentes prod/ataque/defensa).
- **Alianzas** con tipos data-driven (no-agresión / defensiva / plena) y beneficios:
  bonus compartido, tech de unidades por raza, defensa mutua, visión compartida, comercio.
- **Ranking** de jugadores y de alianzas.
- **NPCs con IA**: cerebro por reglas (default) o LLM (OpenRouter) con personalidad + memoria;
  tácticos (recall/torretas, atacan al más débil); forman su propia alianza.
- **Notificaciones** + **push en tiempo real (SSE)**.

**Cliente web**
- Jugable: mapa de la galaxia, imperio (energía/minerales/unidades), bases, colas con barras,
  alianzas (tipos/beneficios/comercio/visión), investigación, ranking, guía in-game, costos y
  avisos de "te falta", pill de DB en uso.

**Infra / calidad**
- Redis (cache de catálogo + rate-limit de ataques), con degradación si no está.
- Makefile con 3 modos: `run` (full-local) · `run-lan` · `up`+`tunnel` (online).
- Docker (compose) y k8s (Helm). Repo público + `LICENSE` (MIT) + `CLAUDE.md`.
- Tests: unit + integración + **e2e HTTP** + **e2e de navegador (Playwright)** con screenshots.

## 🔜 Próximo (mañana seguimos)

1. **Bot de Telegram** — otro cliente sobre la misma API (jugar y recibir notificaciones desde
   Telegram). Cierra la premisa multi-cliente.
2. **Deploy online real** — exponer para jugar a distancia (tunnel/cloud) con Postgres + secreto fuerte.
3. **Mejorar NPCs LLM** — modelo mejor que el free / few-shot; alianzas dinámicas entre NPCs.

## 💡 Backlog / ideas

- Tech `build_speed` (acelerar construcción/entrenamiento) — ya hay framework de efectos.
- Combate que use `hp` de unidades; daño por rondas.
- Chat / mensajes de alianza; eventos del mundo; misiones.
- Más galaxias/planetas y minerales premium con usos reales (He-3, hielo).
- Web: sonidos, vista de detalle por planeta, chat/mensajes de alianza, eventos del mundo.
  (✅ mapa con "naves viajando" + mapa agrupado por galaxia.)

## ⚠️ Deuda técnica

- `JWT_SECRET` fuerte en prod (PyJWT avisa con el default corto).
- Redis **locks** distribuidos para acciones mutantes (hoy hay cache + rate-limit).
- Web sin test de navegador para *todos* los flujos (cubrimos los principales).
