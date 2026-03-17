# AGENTS.md

## Working Rules

- Use `docs/SPEC.md` as the normative product and behavior contract.
- Use `docs/EXEC_PLAN.md` as the implementation sequencing plan.
- When writing complex features or significant refactors, use an ExecPlan as described in
  `.agent/PLANS.md`.
- Treat the orchestrator as a separate long-running process. Do not move orchestration logic into
  Django request handlers or Angular state.

## Styleguide

- Backend styleguide
  - Python 3.12
  - `ruff check` for linting
  - `ruff format` for formatting
  - `mypy` with `django-stubs` for static typing
- Frontend styleguide
  - Angular standalone components with strict TypeScript settings
  - `eslint` for linting
  - `prettier` for formatting
  - `tsc --noEmit` for type checking
  - Tailwind CSS driven by shared design tokens in `apps/web/src/styles/tokens.css`
- General styleguide
  - Keep imports ordered and unused code removed
  - Prefer small, framework-light modules in backend domain code
  - Keep frontend feature code under `features/` and reusable primitives under `shared/`
  - Do not hard-code theme primitives when a token should exist

## Workflow

- Before opening a substantial implementation, read the relevant section of `docs/SPEC.md`.
- If the change is complex, prepare or update an ExecPlan before editing.
- After code changes, run the project checks that apply to the touched surface:
  - `make lint`
  - `make typecheck`
  - `make test`
- Before committing, run `make precommit-run` or rely on installed git hooks from
  `make precommit-install`.
- Use `make format` before finalizing changes when formatting was affected.
- Treat failing lint or typecheck as a blocker for completion.

## Code Map

### Critical Entry Points

- `docs/SPEC.md`: product and behavior source of truth
- `docs/EXEC_PLAN.md`: implementation order and milestones; feature-specific plans live as `docs/EXEC_PLAN_<name>.md`
- `docs/ROADMAP.md`: product roadmap
- `docs/SPEC_GAPS.md`: known gaps between spec and implementation
- `docs/ADR/`: architecture decision records
- `Makefile`: unified local commands
- `.pre-commit-config.yaml`: commit-time quality gates

### Backend

- `apps/api/manage.py`: Django entrypoint
- `apps/api/config/wsgi.py`: WSGI application (used by the embedded runtime HTTP server)
- `apps/api/config/settings/base.py`: main Django/DRF settings; `local.py`, `test.py`, `prod.py` are environment overrides
- `apps/api/config/urls.py`: HTTP route registration
- `apps/api/symphony/apps.py`: root app registration
- `apps/api/symphony/cli.py`: package CLI entry point (`run_orchestrator_main`)
- `apps/api/symphony/api/views.py`: HTTP API views — runtime dashboard, state, SSE events, tracker mutations
- `apps/api/symphony/api/server.py`: embedded `RuntimeHTTPServer` used by the orchestrator to serve agent callbacks
- `apps/api/symphony/management/commands/run_orchestrator.py`: `run_orchestrator` management command
- `apps/api/runtime/agent_runner/`: Codex SDK integration — `client.py`, `runner.py`, `harness.py`, `events.py`, `dynamic_tool.py`, `prompting.py`
- `apps/api/runtime/orchestrator/`: runtime state machine — `core.py`, `recovery.py`
- `apps/api/runtime/workspace/`: workspace lifecycle — `manager.py`, `hooks.py`
- `apps/api/runtime/observability/`: snapshots and SSE events — `snapshots.py`, `runtime.py`, `events.py`
- `apps/api/lib/workflow/`: workflow definition loading (`loader.py`), typed config (`config.py`), runtime helpers (`runtime.py`)
- `apps/api/lib/tracker/`: tracker adapters — `interfaces.py` (abstract), `linear.py`/`plane.py` (impls), `write_service.py`/`write_contract.py` (mutation layer)
- `apps/api/lib/common/`: shared domain logic — `types.py` (e.g. `ServiceInfo`), `logging.py` (`log_event`)
- `apps/api/tests/unit/`: backend unit tests, mirroring the module structure above

### Frontend

- `apps/web/package.json`: frontend commands and dependencies
- `apps/web/angular.json`: build and dev-server config
- `apps/web/eslint.config.js`: frontend lint rules
- `apps/web/tailwind.config.ts`: Tailwind theme mapping
- `apps/web/src/main.ts`: Angular app bootstrap
- `apps/web/src/styles/tokens.css`: design token source of truth
- `apps/web/src/styles/globals.css`: global styles
- `apps/web/src/app/features/`: feature areas — `dashboard/`, `issues/`, `runs/`
- `apps/web/src/app/shared/`: shared UI and helpers — `api/`, `lib/`, `ui/`
- `apps/web/src/app/generated/`: generated API client

## Implementation Notes

- Keep backend core logic framework-light and testable as plain Python modules.
- Keep Angular as a consumer of backend runtime state, not a second orchestrator.
- Use Tailwind CSS through shared tokens. Avoid ad hoc hard-coded utility values when a token should
  exist.
- Prefer extending the existing code map instead of creating duplicate top-level domains.
