SHELL := /bin/bash

-include .env
export VITE_API_BASE_URL
export VITE_CONVERSATION_MODEL

.PHONY: check backend-check frontend-check infra-check docker-check

check: backend-check frontend-check infra-check docker-check
	@echo ""
	@echo "========================================"
	@echo "NEXUS LOCAL CI: ALL CHECKS PASSED"
	@echo "========================================"

backend-check:
	@echo ""
	@echo "========================================"
	@echo "1/4 BACKEND QUALITY"
	@echo "========================================"
	docker compose build backend
	docker compose run --rm backend pytest tests/unit -q
	docker compose run --rm backend pytest tests/api -q
	docker compose run --rm -e NEXUS_REQUIRE_POSTGRES_TESTS=true backend pytest tests/integration -q
	docker compose run --rm -e NEXUS_REQUIRE_POSTGRES_TESTS=true backend pytest tests --cov=nexus --cov-branch --cov-report=term-missing -q
	docker compose run --rm backend ruff check src tests
	docker compose run --rm backend mypy src

frontend-check:
	@echo ""
	@echo "========================================"
	@echo "2/4 FRONTEND QUALITY"
	@echo "========================================"
	@test -n "$$VITE_API_BASE_URL" || (echo "ERROR: VITE_API_BASE_URL is required"; exit 1)
	@test -n "$$VITE_CONVERSATION_MODEL" || (echo "ERROR: VITE_CONVERSATION_MODEL is required"; exit 1)
	docker run --rm \
		-e VITE_API_BASE_URL="$${VITE_API_BASE_URL}" \
		-e VITE_CONVERSATION_MODEL="$${VITE_CONVERSATION_MODEL}" \
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
			npm run test:coverage && \
			rm -rf dist && \
			VITE_API_BASE_URL=$${VITE_API_BASE_URL} VITE_CONVERSATION_MODEL=$${VITE_CONVERSATION_MODEL} npm run build && \
			npx playwright install --with-deps chromium && \
			npm run test:e2e \
	'

infra-check:
	@echo ""
	@echo "========================================"
	@echo "3/4 INFRASTRUCTURE QUALITY"
	@echo "========================================"
	docker run --rm \
		-v "$(CURDIR):/source:ro" \
		-w /source \
		mcr.microsoft.com/azure-cli:2.77.0 \
		sh -c '\
			az bicep install --version v0.47.16 >/dev/null && \
			az bicep build --file infra/azure/file-upload-events.bicep --stdout >/dev/null && \
			az bicep build --file infra/azure/shared-storage-system-topic.bicep --stdout >/dev/null && \
			az bicep build-params --file infra/azure/file-upload-events.example.bicepparam --stdout >/dev/null \
		'

docker-check:
	@echo ""
	@echo "========================================"
	@echo "4/4 DOCKER BUILD"
	@echo "========================================"
	docker compose build --no-cache
