# Public REST API production image.  Build from the repo root:
#   docker build -f api/Dockerfile -t brainbox-api .
# On start it runs `alembic upgrade head`, then the API (deploy/start-api.sh).
# Set RUN_MIGRATIONS=false to skip the migration step (e.g. when CI migrates first).
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app \
    ENVIRONMENT=prod

WORKDIR /app

# Copy the code (see .dockerignore: no .env, no secrets/), then install the [api] extra.
# alembic.ini, migrations/, scripts/ and data/ come along, so the same image can migrate,
# seed (scripts/seed_customer.py) and make admins (scripts/make_admin.py).
COPY . .
# sed: a build from a Windows checkout would copy the start script with CRLF line endings.
RUN pip install --upgrade pip && pip install -e ".[api]" \
    && sed -i 's/\r$//' deploy/start-api.sh && chmod +x deploy/start-api.sh

# Run as a non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000

# Docker / Compose / most hosts restart the container when this fails. (Cloud Run ignores it
# and uses its own startup probe.) start-period leaves time for the migrations.
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/v1/health', timeout=4)" || exit 1

CMD ["/app/deploy/start-api.sh"]
