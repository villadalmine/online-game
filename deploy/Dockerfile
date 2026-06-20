FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

# Install deps first for layer caching.
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir .

# App code + data-driven content + migrations.
COPY app ./app
COPY clients ./clients
COPY content ./content
COPY migrations ./migrations
COPY web ./web
COPY alembic.ini ./alembic.ini

EXPOSE 8000

# Same image runs api or worker; override command in compose/k8s.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
