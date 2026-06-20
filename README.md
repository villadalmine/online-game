# Online Galaxy War

Juego de estrategia espacial **por turnos asíncrono** y **API-first**: galaxias, planetas
y minerales **reales**. Un mismo backend sirve a web, móvil, Telegram, WhatsApp y CLI.

Inspirado en *StarKingdoms*, pero con la Vía Láctea real: empiezas eligiendo planeta
(Tierra, Marte o Venus) y raza, y te desarrollas con los minerales que existen en ese mundo.

## Instalar y jugar en 2 minutos

Requisitos: **Python 3.12+** (o **Docker** si preferís no instalar Python).

```bash
git clone <URL-DEL-REPO>
cd online-game
make install     # crea el entorno e instala (una vez)
make run         # http://localhost:8099/  → Registrar y jugar
```
Con Docker, en vez de `install/run`: `make up` (incluye Postgres+Redis). La base de datos
se crea/migra sola al arrancar — no hay pasos manuales.

## Principios

- **No romper, extender.** Todo el contenido del juego vive en `content/*.yaml`
  (minerales, planetas, razas, edificios, unidades, dioses). Rebalancear = editar un valor.
- **Portable.** Misma imagen en laptop (`docker-compose`) y en k8s (Helm). Config por env.
- **Escalable.** API stateless; el estado avanza *lazy* por timestamp (sin cron por usuario).

## Mecánica clave: roles de recurso

Las recetas piden **roles abstractos** (`structural`, `energetic`, `advanced`).
Cada raza mapea un rol → un mineral concreto en `content/races.yaml`.
Cambiar qué mineral usa una raza es **un solo valor**.

## Cómo jugar — 3 modos

El mismo código soporta 3 modos; elegís con qué comando lo levantás. La web ya apunta al
mismo origen, así que no hay que configurar nada en el front.

| Modo | Comando | Quién juega | Datos |
|---|---|---|---|
| **Full-local** | `make run` | solo vos (127.0.0.1) | SQLite local |
| **LAN** | `make run-lan` | cualquiera en tu red (tu IP) | SQLite local |
| **Online** | `make up` (Docker) + `make tunnel` | desde otra casa | Postgres |

### Empezar (cualquier modo)
```bash
make install        # crea .venv e instala todo (una vez)
make run            # full-local → abrí http://localhost:8099/
```

### Jugar en la misma red (LAN)
```bash
make run-lan        # imprime tu URL de LAN, ej: http://192.168.1.50:8099/
```
El otro abre esa URL en su navegador. Mismo mundo, misma partida.

### Jugar a distancia (online)
```bash
make up             # Postgres + Redis + API + worker en Docker (http://localhost:8000)
make tunnel         # crea una URL pública temporal (cloudflared) para compartir
```

> Si exponés el juego (LAN/online), poné un `JWT_SECRET` propio y fuerte en `.env`.

`make help` lista todos los targets. `make demo` corre el flujo completo solo (humo).

**Jugar en el navegador:** abrí **http://localhost:8099/** (cliente web incluido).
OpenAPI interactivo en http://localhost:8099/docs

## Jugar por CLI (demuestra que es 100% API)

Con el server corriendo (`make run`, puerto 8099), en otra terminal apuntá el CLI a ese
puerto y jugá:

```bash
export API_URL=http://localhost:8099     # debe coincidir con el puerto del server
ogame-cli register alice secret123
ogame-cli catalog
ogame-cli onboard milky_way mars martian
ogame-cli me
ogame-cli build 1 mine iron      # construir una mina de hierro en la base 1
ogame-cli train 1 worker 5       # entrenar 5 trabajadores en la base 1
ogame-cli attack 7 soldier:10,tank:2   # atacar la base 7 con esa fuerza
ogame-cli reports                # historial de combates
ogame-cli moons                  # lunas alcanzables (dioses)
ogame-cli expedition luna        # enviar expedición a la Luna (requiere transbordador)
ogame-cli players                # scoreboard (incl. razas NPC) y sus bases
ogame-cli tick                   # avanzar el mundo ahora (las NPC juegan su turno)
ogame-cli me
```

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## Desplegar en k8s

```bash
helm install galaxy deploy/helm
```

## Estructura

```
content/   contenido data-driven (YAML) — el "diseño" del juego
app/       FastAPI: core, models, schemas, services, api/v1
clients/   cliente CLI de referencia
deploy/    Dockerfile, docker-compose, chart Helm
docs/      game-design.md (bosquejo), architecture.md
tests/     energía, producción, contenido, flujo end-to-end
```

## Documentación

- [`ROADMAP.md`](ROADMAP.md) — **dónde estamos**: hecho / próximo / backlog.
- [`CHANGELOG.md`](CHANGELOG.md) — **registro de todo lo logrado**, por fecha.
- [`docs/development.md`](docs/development.md) — **guía de desarrollo**: setup, mapa del
  código, cómo extender (razas/minerales/edificios/endpoints), migraciones, tests, deploy.
- [`docs/game-design.md`](docs/game-design.md) — diseño del juego (bosquejo).
- [`docs/architecture.md`](docs/architecture.md) — arquitectura técnica.
