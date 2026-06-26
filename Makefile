# ======================================================================
# Online Galaxy War — tareas comunes
# Uso: make <target>   ·   make help para ver todo
# Variables: PORT (8099) · NPC_BRAIN (rules|llm) · m="msg" · ARGS="..."
# ======================================================================

PORT      ?= 8099
NPC_BRAIN ?= rules
AUTOTICK  ?= 15
REPO      ?= online-game
VENV      := .venv
PY        := $(VENV)/bin/python
PIP       := $(VENV)/bin/pip
UVICORN   := $(VENV)/bin/uvicorn
ALEMBIC   := $(VENV)/bin/alembic
RUFF      := $(VENV)/bin/ruff
CLI       := $(VENV)/bin/ogame-cli
API_URL   := http://localhost:$(PORT)
DB_URL    ?= sqlite+aiosqlite:///./game.db
JWT       ?= dev-secret-key-at-least-32-bytes-long!!

.DEFAULT_GOAL := help
.PHONY: help venv install update run run-lan run-llm tunnel demo demo-llm stop health cli \
        test test-ui test-file lint fmt check publish \
        migrate migration downgrade db-current db-history db-reset \
        up down logs ps build-image helm-template helm-install helm-uninstall \
        release deploy deploy-force e2e-local dt-up dt-down clean clean-all

# ---- ayuda -----------------------------------------------------------
help: ## Muestra esta ayuda
	@awk 'BEGIN{FS=":.*?## "; print "\nTargets disponibles:\n"} \
		/^[a-zA-Z0-9_-]+:.*?## /{printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2} \
		/^## /{printf "\n\033[1m%s\033[0m\n", substr($$0,4)}' $(MAKEFILE_LIST)
	@echo ""

## Setup
venv: ## Crea el virtualenv (.venv)
	python3 -m venv $(VENV)

install: venv ## Instala dependencias (app + dev)
	$(PIP) install -q --upgrade pip
	$(PIP) install -q -e ".[dev]"
	@echo "OK: entorno listo."

update: ## Reinstala dependencias (tras cambiar pyproject)
	$(PIP) install -q -e ".[dev]"

## Correr — 3 modos
# Nota: el patrón [u]vicorn evita que pkill se mate a sí mismo (su propia cmdline no matchea).
run: ## Modo FULL-LOCAL: solo tu PC (SQLite, 127.0.0.1:PORT)
	-@pkill -f "[u]vicorn app.main:app" 2>/dev/null; sleep 1
	DATABASE_URL=$(DB_URL) JWT_SECRET=$(JWT) NPC_BRAIN=$(NPC_BRAIN) AUTO_TICK_SECONDS=$(AUTOTICK) \
		$(UVICORN) app.main:app --reload --port $(PORT)

run-lan: ## Modo LAN: otros en tu red entran por tu IP (0.0.0.0:PORT)
	-@pkill -f "[u]vicorn app.main:app" 2>/dev/null; sleep 1
	@ip=$$(hostname -I 2>/dev/null | awk '{print $$1}'); \
		echo "Compartí esta URL en tu red local:  http://$$ip:$(PORT)/"
	DATABASE_URL=$(DB_URL) JWT_SECRET=$(JWT) NPC_BRAIN=$(NPC_BRAIN) AUTO_TICK_SECONDS=$(AUTOTICK) \
		$(UVICORN) app.main:app --host 0.0.0.0 --port $(PORT)

run-llm: ## Como 'run' pero NPCs con OpenRouter (NPC_BRAIN=llm)
	$(MAKE) run NPC_BRAIN=llm

tunnel: ## Modo ONLINE rápido: expone el server local por un túnel público (cloudflared)
	@command -v cloudflared >/dev/null || { echo "Instalá cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"; exit 1; }
	cloudflared tunnel --url http://localhost:$(PORT)

demo: ## Server efímero + flujo completo por CLI (register→tick→players)
	PORT=$(PORT) NPC_BRAIN=$(NPC_BRAIN) bash scripts/demo.sh

demo-llm: ## Demo con NPCs por OpenRouter
	PORT=$(PORT) NPC_BRAIN=llm bash scripts/demo.sh

stop: ## Mata cualquier uvicorn de este proyecto
	-@pkill -f "[u]vicorn app.main:app" 2>/dev/null && echo "server detenido" || echo "no había server"

health: ## Chequea que el server responde en PORT
	@curl -sf $(API_URL)/health && echo "" || echo "no responde en $(API_URL)"

cli: ## Pasa comandos al CLI: make cli ARGS="players"
	API_URL=$(API_URL) $(CLI) $(ARGS)

## Calidad
test: ## Corre la suite API (unit + integración + e2e), sin browser
	$(PY) -m pytest -m "not chrome" -q

test-ui: ## Tests de frontend con browser real (Playwright/Chromium) — SDD 45
	$(PIP) install -q -e ".[ui]" && $(VENV)/bin/playwright install chromium
	$(PY) -m pytest -m chrome tests/test_web_smoke.py -q
	$(PY) -m pytest tests/browser -o addopts="" -p no:asyncio -q 2>/dev/null || true

e2e-local: ## Gate completo en local: lint + API e2e + Chrome (SDD 45)
	$(MAKE) lint
	$(MAKE) test
	$(MAKE) test-ui

test-file: ## Corre un archivo: make test-file f=tests/test_npc.py
	$(PY) -m pytest -q $(f)

lint: ## Linter (ruff)
	$(RUFF) check .

fmt: ## Autofix de lint
	$(RUFF) check --fix .

check: lint test ## Lint + tests (lo que corre CI)

## Migraciones (Alembic)
release: ## Corta un release SemVer: make release V=X.Y.Z [DRY=1] (SDD 23)
	@test -n "$(V)" || (echo 'Falta V=X.Y.Z'; exit 1)
	$(PY) scripts/release.py $(V) $(if $(DRY),--dry-run,)

deploy: ## CD con gate de tests (build→dt→e2e+chrome→prod): make deploy V=X.Y.Z (SDD 44/45)
	@test -n "$(V)" || (echo 'Falta V=X.Y.Z'; exit 1)
	@if command -v argo >/dev/null 2>&1; then \
	  argo submit deploy/build/online-game-cicd.yaml -n kaniko -p image_tag=$(V) --watch; \
	else \
	  echo "argo CLI no encontrado; usando kubectl create (override del tag via parámetro)"; \
	  sed 's/value: "latest"/value: "$(V)"/' deploy/build/online-game-cicd.yaml | kubectl create -f -; \
	fi

deploy-force: ## Deploy SIN gate de tests (emergencias): build + helm upgrade directo (SDD 44/45)
	@test -n "$(V)" || (echo 'Falta V=X.Y.Z'; exit 1)
	@echo "⚠ deploy-force saltea el gate de tests (SDD 45). Solo para incidentes."
	sed 's/value: "latest"/value: "$(V)"/' deploy/build/online-game-kaniko.yaml | kubectl create -f -

dt-up: ## Levanta la instancia de testing galaxy-dt (SDD 45): make dt-up V=X.Y.Z
	@test -n "$(V)" || (echo 'Falta V=X.Y.Z'; exit 1)
	helm upgrade --install galaxy-dt deploy/helm -n online-game-dt --create-namespace \
	  -f deploy/helm/examples/values-dt.yaml --set image.tag=$(V) --wait --timeout 5m

dt-down: ## Baja la instancia de testing galaxy-dt y borra su namespace efímero (SDD 45)
	-helm uninstall galaxy-dt -n online-game-dt
	-kubectl delete ns online-game-dt --wait=false

migrate: ## Aplica migraciones (alembic upgrade head)
	DATABASE_URL=$(DB_URL) $(ALEMBIC) upgrade head

migration: ## Genera migración: make migration m="mensaje"
	@test -n "$(m)" || (echo 'Falta m="mensaje"'; exit 1)
	rm -f _gen.db
	$(ALEMBIC) -x url=sqlite+aiosqlite:///./_gen.db upgrade head >/dev/null 2>&1
	$(ALEMBIC) -x url=sqlite+aiosqlite:///./_gen.db revision --autogenerate -m "$(m)"
	rm -f _gen.db

downgrade: ## Baja una migración (alembic downgrade -1)
	DATABASE_URL=$(DB_URL) $(ALEMBIC) downgrade -1

db-current: ## Muestra la revisión actual
	DATABASE_URL=$(DB_URL) $(ALEMBIC) current

db-history: ## Muestra el historial de migraciones
	$(ALEMBIC) history --verbose

db-reset: ## Borra la DB local SQLite (se recrea al arrancar)
	rm -f game.db demo.db && echo "DB local borrada"

## Docker / k8s
up: ## Postgres+Redis+API+worker en contenedores
	docker compose -f deploy/docker-compose.yml up --build

down: ## Baja los contenedores
	docker compose -f deploy/docker-compose.yml down

logs: ## Logs de los contenedores
	docker compose -f deploy/docker-compose.yml logs -f

ps: ## Estado de los contenedores
	docker compose -f deploy/docker-compose.yml ps

build-image: ## Construye la imagen Docker
	docker build -f deploy/Dockerfile -t online-game:0.1.0 .

helm-template: ## Renderiza el chart Helm
	helm template galaxy deploy/helm

helm-install: ## Instala en el cluster k8s actual
	helm install galaxy deploy/helm

helm-uninstall: ## Desinstala del cluster
	helm uninstall galaxy

## Publicar
publish: ## Crea el repo en GitHub y sube todo (requiere gh logueado): make publish REPO=nombre
	@command -v gh >/dev/null || { echo "Instalá GitHub CLI (gh) y corré 'gh auth login': https://cli.github.com/"; exit 1; }
	@git rev-parse --is-inside-work-tree >/dev/null 2>&1 || git init -b main
	@git add -A && git -c user.name="$$(git config user.name || echo dev)" commit -m "Initial commit" 2>/dev/null || true
	gh repo create $(REPO) --public --source=. --remote=origin --push \
		--description "Juego de estrategia espacial API-first por turnos (full-local / LAN / online)"

## Limpieza
clean: ## Borra DBs locales y caches
	rm -f game.db demo.db _gen.db
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} +

clean-all: clean ## clean + borra el virtualenv
	rm -rf $(VENV)
