UV ?= uv
PNPM ?= pnpm
DJANGO_TEST_SETTINGS ?= config.settings.test

.PHONY: sync install-web dev dev-api dev-web lint lint-api lint-web typecheck typecheck-api typecheck-web format format-api format-web test test-api test-web precommit-install precommit-run

sync:
	$(UV) sync

install-web:
	$(PNPM) install

dev:
	DEV_MODE=$(DEV_MODE) API_PORT=$(API_PORT) WEB_PORT=$(WEB_PORT) RUNTIME_PORT=$(RUNTIME_PORT) API_PROXY_TARGET=$(API_PROXY_TARGET) DJANGO_ALLOWED_HOSTS=$(DJANGO_ALLOWED_HOSTS) WORKFLOW_TEMPLATE_PATH=$(WORKFLOW_TEMPLATE_PATH) RUNTIME_ROOT=$(RUNTIME_ROOT) SYMPHONY_WORKFLOW_PATH=$(SYMPHONY_WORKFLOW_PATH) SYMPHONY_RUNTIME_SNAPSHOT_PATH=$(SYMPHONY_RUNTIME_SNAPSHOT_PATH) SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH=$(SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH) SYMPHONY_RUNTIME_RECOVERY_PATH=$(SYMPHONY_RUNTIME_RECOVERY_PATH) ./scripts/dev/start.sh

dev-api:
	API_HOST=$(API_HOST) API_PORT=$(API_PORT) DJANGO_ALLOWED_HOSTS=$(DJANGO_ALLOWED_HOSTS) ./scripts/dev/api-server.sh

dev-web:
	WEB_HOST=$(WEB_HOST) WEB_PORT=$(WEB_PORT) API_PROXY_TARGET=$(API_PROXY_TARGET) ./scripts/dev/web-server.sh

lint: lint-api lint-web

test-api:
	DJANGO_SETTINGS_MODULE=$(DJANGO_TEST_SETTINGS) $(UV) run pytest

test: test-api test-web

test-web:
	$(PNPM) --dir apps/web test

lint-api:
	$(UV) run ruff check .

lint-web:
	$(PNPM) --dir apps/web lint

typecheck: typecheck-api typecheck-web

typecheck-api:
	$(UV) run mypy apps/api

typecheck-web:
	$(PNPM) --dir apps/web typecheck

format: format-api format-web

format-api:
	$(UV) run ruff format .

format-web:
	$(PNPM) --dir apps/web format

precommit-install:
	$(UV) run pre-commit install

precommit-run:
	$(UV) run pre-commit run --all-files
