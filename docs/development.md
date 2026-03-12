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
   # Optional when testing Plane-backed config or adapter paths:
   export PLANE_API_KEY=...
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

### Runtime refresh model

- The Angular runtime views treat the REST snapshot endpoints as the canonical
  source of truth: `GET /api/v1/state`, `GET /api/v1/<issue_identifier>`, and
  `POST /api/v1/refresh`.
- Snapshot freshness metadata (`generated_at`, `expires_at`, `revision`) drives
  automatic revalidation in the browser. The shared frontend runtime session
  service schedules the next poll from `expires_at` instead of using a fixed
  interval.
- The browser also revalidates immediately when the page regains focus or
  becomes visible again, so background tabs do not stay stale until the next
  scheduled poll.
- `GET /api/v1/events` is an optional SSE invalidation stream. Events are
  lightweight signals such as `snapshot_updated`, `issue_changed`, and
  `refresh_queued`; the browser reacts by fetching the canonical REST snapshot
  again rather than trusting streamed state payloads.
- The current runtime HTTP sidecar is a threaded WSGI server. Each connected
  SSE client occupies one server thread for the life of the stream, so this
  path is intended for a small number of internal operator sessions rather than
  high fan-out traffic.
- The invalidation broker is process-local in memory. SSE clients must connect
  to the same runtime sidecar process that is publishing snapshot updates.

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
- The workflow `tracker` section is kind-specific: Linear uses
  `endpoint` / `project_slug`, while Plane uses `api_base_url` /
  `workspace_slug` / `project_id`.

#### Plane self-host workflow example

Use this front matter shape when exercising a self-hosted Plane deployment:

```md
---
tracker:
  kind: plane
  api_base_url: $PLANE_API_BASE_URL
  api_key: $PLANE_API_KEY
  workspace_slug: $PLANE_WORKSPACE
  project_id: $PLANE_PROJECT_ID
  active_states: Todo, In Progress
  terminal_states: Done, Canceled
---
# Prompt body
Continue working on {{ issue.identifier }}.
```

Example environment bootstrap:

```sh
export PLANE_API_BASE_URL=https://plane.example.com
export PLANE_API_KEY=plane_api_example
export PLANE_WORKSPACE=engineering
export PLANE_PROJECT_ID=88c2d97c-a6ad-4012-b526-5577c0d7c769
```

`api_base_url` points at the root of your self-hosted Plane deployment.
`workspace_slug` and `project_id` map directly to
`/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/`.

The environment variable names above (`PLANE_API_BASE_URL`, `PLANE_API_KEY`, `PLANE_WORKSPACE`,
`PLANE_PROJECT_ID`) are conventional — the runtime only sees the resolved string value, so any
name works as long as you reference it via `$VAR_NAME` in the workflow front matter.

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
