SHELL := /bin/bash

.PHONY: check backend-check frontend-check docker-check

check: backend-check frontend-check docker-check
	@echo ""
	@echo "========================================"
	@echo "NEXUS LOCAL CI: ALL CHECKS PASSED"
	@echo "========================================"

backend-check:
	@echo ""
	@echo "========================================"
	@echo "1/3 BACKEND QUALITY"
	@echo "========================================"
	docker compose build backend
	docker compose run --rm backend pytest tests/unit -q
	docker compose run --rm backend pytest tests/api -q
	docker compose run --rm backend pytest tests/integration -q
	docker compose run --rm backend ruff check src tests
	docker compose run --rm backend mypy src

frontend-check:
	@echo ""
	@echo "========================================"
	@echo "2/3 FRONTEND QUALITY"
	@echo "========================================"
	@test -n "$$VITE_API_BASE_URL" || (echo "ERROR: VITE_API_BASE_URL is required"; exit 1)
	docker run --rm \
		-e VITE_API_BASE_URL="$${VITE_API_BASE_URL}" \
		-v "$(CURDIR)/frontend:/source:ro" \
		-w /app \
		node:20-bookworm \
		bash -c '\
			cp -a /source/. /app/ && \
			npm ci && \
			npm run typecheck && \
			npm run lint && \
			npm run format:check && \
			npm test && \
			rm -rf dist && \
			VITE_API_BASE_URL=$${VITE_API_BASE_URL} npm run build && \
			npx playwright install --with-deps chromium && \
			npm run test:e2e \
		'

docker-check:
	@echo ""
	@echo "========================================"
	@echo "3/3 DOCKER BUILD"
	@echo "========================================"
	docker compose build --no-cache