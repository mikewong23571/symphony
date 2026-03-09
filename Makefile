UV ?= uv
PNPM ?= pnpm

.PHONY: sync install-web dev-api dev-web lint lint-api lint-web typecheck typecheck-api typecheck-web format format-api format-web test test-api test-web precommit-install precommit-run

sync:
	$(UV) sync

install-web:
	$(PNPM) install

dev-api:
	cd apps/api && ../../.venv/bin/python manage.py runserver

dev-web:
	$(PNPM) --dir apps/web start

lint: lint-api lint-web

test-api:
	$(UV) run pytest

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
