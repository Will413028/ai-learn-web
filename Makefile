ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
ATTACHMENTS := $(ROOT)/docs/plans/2026-10-01-full-rebuild
.PHONY: schema check schema-check e2e inventory-check mutation-check integration smoke-container db-migrate dev-worker dev-backend dev-frontend eval eval-search eval-rag eval-image

schema:
	uv run --directory "$(ROOT)/backend" --frozen python "$(ROOT)/backend/export_openapi.py"
	pnpm --dir "$(ROOT)/frontend" exec openapi-typescript "$(ROOT)/backend/openapi.json" -o "$(ROOT)/frontend/src/lib/generated/api.ts"

schema-check:
	python3 "$(ROOT)/check_schema.py"

check: schema-check
	uv run --directory "$(ROOT)/backend" --frozen ruff check "$(ROOT)/backend"
	uv run --directory "$(ROOT)/backend" --frozen mypy "$(ROOT)/backend/app" "$(ROOT)/backend/export_openapi.py"
	uv run --directory "$(ROOT)/backend" --frozen pytest -q
	pnpm --dir "$(ROOT)/frontend" lint
	pnpm --dir "$(ROOT)/frontend" typecheck
	node "$(ROOT)/frontend/test-support/network-guard.test.mjs"
	node "$(ROOT)/frontend/test-support/browser-network.test.mjs"
	node "$(ROOT)/frontend/test-support/proxy.test.mjs"
	NEXT_TELEMETRY_DISABLED=1 pnpm --dir "$(ROOT)/frontend" build

e2e:
	pnpm --dir "$(ROOT)/frontend" e2e

inventory-check:
	python3 "$(ATTACHMENTS)/audit_source.py" --self-test
	python3 "$(ATTACHMENTS)/offline_probes.py"

mutation-check:
	python3 "$(ROOT)/backend/mutation_check.py"

integration:
	uv run --directory "$(ROOT)/backend" --frozen pytest -q

db-migrate:
	uv run --directory "$(ROOT)/backend" --frozen alembic upgrade head

dev-worker:
	uv run --directory "$(ROOT)/backend" --frozen python -m app.worker

dev-backend:
	uv run --directory "$(ROOT)/backend" --frozen uvicorn app.main:app --host 127.0.0.1 --port 8100 --timeout-keep-alive 65

dev-frontend:
	NEXT_TELEMETRY_DISABLED=1 pnpm --dir "$(ROOT)/frontend" dev

smoke-container:
	uv run --directory "$(ROOT)/backend" --frozen python "$(ROOT)/backend/smoke_container.py"

# Default fake self-check; cloud needs explicit CLI opt-in and configuration.
eval:
	uv run --directory "$(ROOT)/backend" --frozen python "$(ROOT)/backend/eval_provider.py" $(EVAL_ARGS)

eval-search:
	$(MAKE) eval EVAL_ARGS="--kind search $(EVAL_ARGS)"

eval-rag:
	$(MAKE) eval EVAL_ARGS="--kind rag $(EVAL_ARGS)"

eval-image:
	$(MAKE) eval EVAL_ARGS="--kind image $(EVAL_ARGS)"
