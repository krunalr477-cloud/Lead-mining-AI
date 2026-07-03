.PHONY: infra infra-down dev api worker beat web migrate makemigration seed verify-demo test test-unit test-integration lint smoke-keys full full-down

# --- Infrastructure (postgres + redis in Docker via Colima) ---
infra:
	docker compose up -d postgres redis

infra-down:
	docker compose down

# --- Native dev processes (run each in its own terminal, or use `make dev`) ---
api:
	cd backend && uv run uvicorn app.main:app --reload --port 8000

worker:
	cd backend && uv run celery -A app.workers.celery_app worker \
		-Q google_maps_jobs,website_scrape_jobs,directory_source_jobs,facebook_signal_jobs,job_signal_jobs,enrichment_jobs,validation_jobs,spreadsheet_sync_jobs,campaign_jobs,bounce_check_jobs,export_jobs,audit_jobs \
		--pool=solo --loglevel=INFO

beat:
	cd backend && uv run celery -A app.workers.celery_app beat --loglevel=INFO

web:
	cd frontend && npm run dev

# --- Database ---
migrate:
	cd backend && uv run alembic upgrade head

makemigration:
	cd backend && uv run alembic revision --autogenerate -m "$(m)"

seed:
	cd backend && uv run python -m scripts.seed_demo

# --- Verification ---
verify-demo:
	cd backend && uv run python -m scripts.verify_demo

test:
	cd backend && uv run pytest -q

test-unit:
	cd backend && uv run pytest tests/unit -q

test-integration:
	cd backend && uv run pytest tests/integration -q

lint:
	cd backend && uv run ruff check app tests scripts && uv run ruff format --check app tests scripts

smoke-keys:
	bash scripts/smoke_keys.sh

# --- Full containerized profile (production parity) ---
full:
	docker compose --profile full up -d --build

full-down:
	docker compose --profile full down
