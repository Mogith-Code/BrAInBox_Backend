# Internal AI service image.  Build from the repo root:
#   docker build -f ai_service/Dockerfile -t brainbox-ai .
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Tesseract OCR reads scanned pages of the NIE resource books during RAG ingestion.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY . .
RUN pip install --upgrade pip && pip install -e ".[ai]"

RUN useradd --create-home appuser
USER appuser

EXPOSE 8001
CMD ["uvicorn", "ai_service.main:app", "--host", "0.0.0.0", "--port", "8001"]
