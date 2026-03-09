# Symphony

Symphony is a coding-agent orchestration service with a Django backend, an
`asyncio`-driven orchestrator process, and an Angular + Tailwind CSS dashboard.
The repository is currently at the foundation stage described in
[`docs/EXEC_PLAN.md`](docs/EXEC_PLAN.md): the backend and frontend skeletons,
tooling baseline, and CI workflow are in place, while the orchestrator,
workflow loader, and tracker integrations are still stubs.

## Repository Layout

- `apps/api`: Django project, management commands, backend packages, and tests
- `apps/web`: Angular application and shared design tokens
- `docs`: product specification, execution plan, and ADR placeholders
- `.github/workflows`: CI workflow for backend and frontend validation

## Prerequisites

- Python 3.12
- `uv`
- Node.js 20 or newer
- `pnpm` 10.6.0

## Initial Setup

1. Sync Python dependencies:

   ```sh
   uv sync
   ```

2. Install frontend dependencies:

   ```sh
   pnpm install
   ```

3. Copy `.env.example` values into your shell or local environment as needed.
   The current skeleton uses `config.settings.local` by default when running
   Django via `manage.py`.

## Common Commands

- Install Python dependencies: `make sync`
- Install frontend dependencies: `make install-web`
- Run all lint checks: `make lint`
- Run all type checks: `make typecheck`
- Run all tests: `make test`
- Run pre-commit checks: `make precommit-run`

## Local Development

### API Server

Start the Django development server from the repository root:

```sh
make dev-api
```

The API health endpoint is available at
[`http://127.0.0.1:8000/healthz`](http://127.0.0.1:8000/healthz) and currently
returns:

```json
{"status": "ok", "service": "symphony-api"}
```

### Frontend Dashboard

Start the Angular development server from the repository root:

```sh
make dev-web
```

The dashboard currently renders a token-driven shell that confirms Angular,
Tailwind CSS, and the shared design-token setup are wired correctly.

## Quality Gates

The repository uses the same commands locally and in CI:

- Backend: `make lint-api`, `make typecheck-api`, `make test-api`
- Frontend: `make lint-web`, `make typecheck-web`, `make test-web`

GitHub Actions runs these checks on every `push` and `pull_request` via the
[workflow file](.github/workflows/ci.yml).

## Current Status

- Django, DRF, and drf-spectacular are configured under `apps/api`.
- Angular standalone bootstrap, Tailwind CSS, and shared tokens are configured
  under `apps/web`.
- The orchestrator command exists but still prints a placeholder message.
- `WORKFLOW.md` loading, tracker integration, workspace management, and runtime
  orchestration are planned next in `docs/EXEC_PLAN.md`.
