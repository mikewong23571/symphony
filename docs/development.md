# Development Guide

## Prerequisites

- Python 3.12
- `uv`
- Node.js 20 or newer
- `pnpm` 10.6.0
- `overmind` (`brew install overmind`)

## Initial Setup

1. Sync Python dependencies:

   ```sh
   uv sync
   ```

2. Install frontend dependencies:

   ```sh
   pnpm install
   ```

3. Export environment variables from `.env.example`:

   ```sh
   export DJANGO_SETTINGS_MODULE=config.settings.local
   export DJANGO_ALLOWED_HOSTS='*'
   export LINEAR_API_KEY=...
   ```

4. If you want to run the orchestrator, create a repository-local `WORKFLOW.md`
   or pass an explicit path to the management command. The orchestrator will
   fail to start if the workflow file is missing.

---

## Unified Dev Server

Start Django, the orchestrator runtime, and Angular together:

```sh
make dev
```

This uses `overmind` with [`Procfile.dev`](../Procfile.dev) and
[`./scripts/dev/start.sh`](../scripts/dev/start.sh). Three processes start
together:

| Process | Description | Default address |
|---|---|---|
| `api` | Django dev server | `127.0.0.1:8000` |
| `runtime` | Orchestrator + HTTP sidecar | `127.0.0.1:9000` |
| `web` | Angular dev server | `127.0.0.1:4200` |

Before startup, `start.sh` prepares `./.runtime/dev/`, copies
[`examples/WORKFLOW.dev.md`](../examples/WORKFLOW.dev.md) to
`./.runtime/dev/WORKFLOW.md`, and exports runtime path env vars so Django and
the orchestrator share the same workflow/snapshot/recovery files.

When present, `start.sh` also loads `.env` then `.env.local`. Explicit env
vars passed to `make dev` take precedence; script defaults only fill in values
that remain unset.

### Network modes

```sh
make dev               # local: binds to 127.0.0.1 (default)
make dev DEV_MODE=lan  # lan: binds to 0.0.0.0 for LAN testing
```

Angular still proxies `/api/*` to `http://127.0.0.1:${API_PORT}` in both
modes, so the frontend always reaches Django even when exposed externally.

### Useful overrides

```sh
API_PORT=9000 WEB_PORT=4300 make dev
API_PROXY_TARGET=http://127.0.0.1:9000 make dev
DJANGO_ALLOWED_HOSTS='*' make dev DEV_MODE=lan
RUNTIME_ROOT=$PWD/.runtime/dev-alt make dev
```

---

## Individual Servers

### Django API

```sh
make dev-api                       # listen on 127.0.0.1:8000
make dev-api API_HOST=0.0.0.0      # expose on all interfaces
```

Health check: `GET http://127.0.0.1:8000/healthz` → `{"status":"ok","service":"symphony-api"}`

The runtime sidecar also exposes the dashboard JSON endpoints under `/api/v1/*`.

### Angular Frontend

```sh
make dev-web                       # listen on 127.0.0.1:4200
make dev-web WEB_HOST=0.0.0.0     # expose on all interfaces
```

The Angular dev server proxies `/api/*` to `API_PROXY_TARGET`, which defaults
to `http://127.0.0.1:8000`.

### Orchestrator

Run a single startup-cleanup and poll tick:

```sh
cd apps/api
../../.venv/bin/python manage.py run_orchestrator --once --port 9000
```

Run the long-lived loop:

```sh
cd apps/api
../../.venv/bin/python manage.py run_orchestrator --port 9000
```

Expose the HTTP sidecar on all interfaces:

```sh
cd apps/api
../../.venv/bin/python manage.py run_orchestrator --port 9000 --host 0.0.0.0
```

**Notes:**

- `WORKFLOW.md` defaults to the repository root; pass an explicit path as the
  first positional argument to override.
- `--port` enables the runtime HTTP server. Omitting it disables the listener.
- `--host` defaults to `127.0.0.1`. Use `0.0.0.0` only when you want the
  sidecar reachable from other machines.
- A valid Linear configuration (`LINEAR_API_KEY` + workflow tracker settings)
  is required for real issue dispatching.

---

## uv Tool Install

Install the orchestrator as a uv tool from this repository:

```sh
uv tool install --editable .
symphony-orchestrator --port 9000 --host 0.0.0.0
```

Run ad hoc without installing:

```sh
uv tool run --from . symphony-orchestrator --port 9000 --host 0.0.0.0
```

---

## Quality Gates

The same commands run locally and in CI:

| Scope | Lint | Typecheck | Test |
|---|---|---|---|
| Backend | `make lint-api` | `make typecheck-api` | `make test-api` |
| Frontend | `make lint-web` | `make typecheck-web` | `make test-web` |
| All | `make lint` | `make typecheck` | `make test` |

Run all pre-commit checks at once:

```sh
make precommit-run
```

GitHub Actions runs lint, typecheck, and test on every push and pull request
via [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
