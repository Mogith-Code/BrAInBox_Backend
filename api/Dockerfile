# Public REST API image.  Build from the repo root:
#   docker build -f api/Dockerfile -t brainbox-api .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Copy the code (see .dockerignore), then install the package with the [api] extra.
COPY . .
RUN pip install --upgrade pip && pip install -e ".[api]"

# Run as a non-root user
RUN useradd --create-home appuser
USER appuser

EXPOSE 8000
# Cloud Run tells the container which port to use through $PORT (default 8000 elsewhere).
# --proxy-headers: trust X-Forwarded-* from the Cloud Run front end (https URLs, client IP).
CMD ["sh", "-c", "exec uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips=*"]
