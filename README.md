# Symphony

Symphony is a coding-agent orchestration service with a Django backend,
an `asyncio`-driven orchestrator, and an Angular Material dashboard.

## Repository layout

```
apps/api/        Django project, management commands, backend packages, tests
apps/web/        Angular application (standalone components, Angular Material)
docs/            Product spec, ADRs, development guide
examples/        Sample workflow and runtime files
scripts/         Dev and CI shell scripts
.github/         CI workflow
```

## Prerequisites

- Python 3.12 + [`uv`](https://docs.astral.sh/uv/)
- Node.js 20+ + [`pnpm`](https://pnpm.io/) 10.6.0

## Setup

```sh
uv sync        # Python dependencies
pnpm install   # Node dependencies
```

Copy `.env.example` to `.env.local` and fill in `DJANGO_SETTINGS_MODULE`,
`LINEAR_API_KEY`, and any other required values before starting services.

## Development

| Command | Description |
|---|---|
| `make dev` | Start Django, orchestrator, and Angular together |
| `make dev-api` | Django only |
| `make dev-web` | Angular only |

## Quality

| Command | Description |
|---|---|
| `make lint` | Lint all |
| `make typecheck` | Typecheck all |
| `make test` | Test all |
| `make precommit-run` | Run all pre-commit checks |

## Documentation

| Document | Description |
|---|---|
| [`docs/development.md`](docs/development.md) | Dev server setup, port configuration, orchestrator flags, CI |
| [`docs/SPEC.md`](docs/SPEC.md) | Product behavior and sequencing |
| [`docs/ADR/`](docs/ADR/) | Architecture decision records |
