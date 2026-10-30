# Shortcuts for common tasks. Windows: use Git Bash, or copy the command after the tab.
.PHONY: up down logs migrate seed ingest test lint fmt typecheck

up:        ## start db + api + ai_service
	docker compose up -d --build

down:      ## stop everything (data is kept in the pgdata volume)
	docker compose down

logs:
	docker compose logs -f api ai_service

migrate:   ## apply database migrations
	docker compose exec api alembic upgrade head

seed:      ## dev seed: syllabus, community groups, app_config, 15 sample MCQs (idempotent)
	docker compose exec api python -m scripts.seed_dev --with-samples

ingest:    ## RAG: ingest data/rag_sources
	docker compose exec ai_service python scripts/ingest_documents.py

test:      ## run the tests on your machine (needs: pip install -e ".[api,ai,dev]")
	pytest

lint:
	ruff check .
	ruff format --check .

fmt:
	ruff check . --fix
	ruff format .

typecheck:
	mypy api ai_service shared
