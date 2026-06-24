FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# The package (setuptools) needs its source dirs present to build, so copy the code
# that makes up the package BEFORE installing.
COPY pyproject.toml ./
COPY app ./app
COPY clients ./clients
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Data-driven content + migrations + web + scripts (not part of the package; loaded by path).
COPY content ./content
COPY migrations ./migrations
COPY web ./web
COPY scripts ./scripts
COPY alembic.ini ./alembic.ini

# --- GATE de tests (SDD 22, capa 1): corre la suite unit/e2e DURANTE el build (browser excluido
# por addopts). Si algo falla, el RUN falla → la imagen NO se construye/publica. El runtime depende
# de este stage (COPY del marker), así que Kaniko lo ejecuta sí o sí.
FROM base AS test
COPY tests ./tests
# El test del generador de Pages (SDD 18) y otros leen docs/CHANGELOG/ROADMAP del repo.
COPY docs ./docs
COPY ROADMAP.md CHANGELOG.md ./
RUN pip install --no-cache-dir ".[dev]" && pytest -q && touch /tmp/tests-passed

# --- Runtime final (lean: sin dev-deps ni tests). Depende del gate.
FROM base AS runtime
COPY --from=test /tmp/tests-passed /tmp/tests-passed

EXPOSE 8000

# Same image runs api or worker; override command in compose/k8s.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
