.PHONY: help setup up down logs ingest test lint dev-api dev-web clean

help:
	@echo "make setup    - copy .env, install backend + frontend deps"
	@echo "make up       - build and start everything (docker compose)"
	@echo "make down     - stop everything"
	@echo "make logs     - follow the API logs"
	@echo "make ingest   - (re)load transcripts into the knowledge base"
	@echo "make test     - run the backend test suite"
	@echo "make lint     - ruff"
	@echo "make dev-api  - run the API locally with reload"
	@echo "make dev-web  - run the Vite dev server"
	@echo "make clean    - stop and delete the database volume"

setup:
	cp -n .env.example .env || true
	cd backend && pip install -r requirements-dev.txt
	cd frontend && npm install

up:
	docker compose up --build -d
	@echo "Web  http://localhost:5173"
	@echo "API  http://localhost:8000/docs"

down:
	docker compose down

logs:
	docker compose logs -f api

ingest:
	docker compose exec api python -m app.rag.ingest --path /app/data/transcripts

test:
	cd backend && python -m pytest

lint:
	cd backend && ruff check .

dev-api:
	cd backend && uvicorn app.main:app --reload --port 8000

dev-web:
	cd frontend && npm run dev

clean:
	docker compose down -v
