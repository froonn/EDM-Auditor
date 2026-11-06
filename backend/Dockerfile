# The API with its migrations. Data lives in /app/data, which docker-compose.yml mounts as a volume.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first, so a code change does not reinstall them.
COPY pyproject.toml ./
RUN mkdir -p src/edm_auditor && touch src/edm_auditor/__init__.py \
    && pip install . \
    && pip uninstall -y edm-auditor-backend

COPY src ./src
RUN pip install --no-deps .

COPY alembic.ini ./
COPY migrations ./migrations
COPY config ./config

# The server runs without root; the volume takes the owner of this directory on first use.
RUN useradd --uid 10001 --no-create-home --home-dir /app edm \
    && mkdir -p data/uploads \
    && chown -R edm:edm data
USER edm

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"]

# Migrations run on every start: the server refuses to work on an outdated schema. One worker,
# because SQLite allows one writer.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn edm_auditor.api.app:create_app --factory --host 0.0.0.0 --port 8000"]
