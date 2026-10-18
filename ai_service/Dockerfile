# Internal AI service image.  Build from the repo root:
#   docker build -f ai_service/Dockerfile -t brainbox-ai .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

COPY . .
RUN pip install --upgrade pip && pip install -e ".[ai]"

RUN useradd --create-home appuser
USER appuser

EXPOSE 8001
CMD ["uvicorn", "ai_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
