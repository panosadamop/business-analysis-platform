.PHONY: help install test test-all test-e2e test-coverage lint run worker seed up down logs build reset

help:
	@echo "install  install backend and frontend dependencies"
	@echo "test     run the infrastructure free suites (unit, API, acceptance, frontend)"
	@echo "test-all run everything, including the live deployment suites"
	@echo "test-e2e run only the live deployment suites"
	@echo "run      run the API locally (needs MongoDB on localhost)"
	@echo "worker   run the background worker locally"
	@echo "seed     seed the reference project"
	@echo "up       start the company hosted deployment with Docker"
	@echo "down     stop the deployment"
	@echo "logs     follow the API and worker logs"

install:
	cd backend && python -m venv .venv && ./.venv/Scripts/pip install -r requirements-dev.txt
	cd frontend && npm install

test:
	bash scripts/run-tests.sh

test-all:
	bash scripts/run-tests.sh --all

test-e2e:
	bash scripts/run-tests.sh --e2e

test-coverage:
	bash scripts/run-tests.sh --coverage

lint:
	cd frontend && npm run lint

run:
	cd backend && ./.venv/Scripts/python -m uvicorn app.main:app --reload

worker:
	cd backend && ./.venv/Scripts/python -m app.workers.worker

seed:
	cd backend && ./.venv/Scripts/python -m app.seed

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f api worker

reset:
	docker compose down -v
