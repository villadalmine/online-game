FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# The package (setuptools) needs its source dirs present to build, so copy the code
# that makes up the package BEFORE installing.
COPY pyproject.toml ./
COPY app ./app
COPY clients ./clients
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# Data-driven content + migrations + web (not part of the package; loaded by path).
COPY content ./content
COPY migrations ./migrations
COPY web ./web
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Same image runs api or worker; override command in compose/k8s.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
