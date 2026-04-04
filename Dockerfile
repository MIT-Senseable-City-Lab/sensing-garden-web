FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock ./
RUN poetry install --without dev --no-root

COPY app.py start.sh ./
COPY templates ./templates
COPY static ./static

RUN chmod +x /app/start.sh

ENV PORT=8080

EXPOSE 8080

CMD ["./start.sh"]
