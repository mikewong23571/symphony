# Symphony ExecPlan

Status: Draft v1

Purpose: Define the execution plan, milestone sequence, and task breakdown for implementing Symphony
with Django, Angular, `uv`, `pnpm`, and an `asyncio`-based orchestrator.

## 1. Architecture Baseline

This execution plan assumes the following architecture choices:

- Backend host framework: Django 5.2
- API layer: Django REST Framework
- API schema: drf-spectacular
- Orchestrator runtime: Django management command + `asyncio`
- Frontend dashboard: Angular
- UI styling: Tailwind CSS
- UI theming model: tokenized design system via shared design tokens
- Python package/runtime management: `uv`
- Node package/runtime management: `pnpm`
- Primary backend quality tools: `ruff`, `pytest`, `mypy`, `django-stubs`
- Primary frontend quality tools: `angular-eslint`, `prettier`, `vitest`, `playwright`,
  `tailwindcss`

System role split:

- Django provides configuration loading, API, admin, issue tracker adapter wiring, workspace
  management wiring, observability endpoints, and operator control endpoints.
- The orchestrator is a separate long-running process invoked via Django management command.
- Angular is an optional dashboard and consumes backend APIs only.
- Tailwind CSS provides the utility layer, but visual decisions must flow from shared tokens rather
  than ad hoc utility values.
- The coding agent app-server is launched and supervised by the orchestrator, not by the web layer.

## 2. Delivery Strategy

Implementation should follow the main execution path first:

1. Load workflow and typed config.
2. Fetch candidate issues from the tracker.
3. Create or reuse the issue workspace.
4. Build the prompt and start the coding-agent session.
5. Stream runtime events back into orchestrator state.
6. Handle worker completion, retry, reconciliation, and cleanup.
7. Expose observability through logs and snapshot APIs.
8. Add dashboard and operator ergonomics after the backend loop is stable.

Execution principle:

- Build the smallest end-to-end backend loop before investing in dashboard polish.
- Keep orchestrator state in-memory and authoritative.
- Use persistence only for auditability, debugging, and cached observability if needed.
- Keep framework-dependent code at the edges; core coordination logic should remain testable as
  plain Python modules.

## 3. Milestones

### M0. Repository and Toolchain Foundation

Goal: Establish the monorepo, local developer workflow, and code-quality baseline.

Scope:

- Create backend application skeleton under `apps/api`
- Create frontend application skeleton under `apps/web`
- Set up `uv`-managed Python project and lockfile
- Set up `pnpm` workspace and Angular project
- Establish shared scripts for lint, test, and local run
- Establish environment variable conventions and `.env.example`
- Define initial CI layout for backend and frontend validation

Tasks:

- Backend bootstrap
  - Create Django project structure
  - Add DRF and drf-spectacular
  - Add settings split for local/test/prod if needed
  - Add management command package layout
- Frontend bootstrap
  - Create Angular app with standalone components and strict settings
  - Add Tailwind CSS integration
  - Define initial design-token structure for color, spacing, radius, typography, shadow, and
    motion
  - Add lint/format/test configuration
  - Add typed API client generation placeholder workflow
- Tooling
  - Configure `ruff`
  - Configure `pytest` and `pytest-django`
  - Configure `mypy` and `django-stubs`
  - Configure `angular-eslint` and `prettier`
  - Configure Tailwind token usage conventions
  - Configure `vitest` and `playwright`
- Developer experience
  - Add root task entrypoints for install, lint, test, run
  - Add basic README setup instructions

Acceptance:

- `uv sync` succeeds
- `pnpm install` succeeds
- Backend tests and lint pass in CI
- Frontend tests and lint pass in CI
- Developers can start API server and frontend dev server locally
- Frontend token definitions are the single source of truth for theme primitives

### M1. Workflow, Config, and Tracker Integration

Goal: Build the typed configuration layer and the first external dependency integration.

Scope:

- `WORKFLOW.md` discovery and parsing
- YAML front matter extraction and prompt body extraction
- Typed config layer with defaults and environment resolution
- Dynamic reload/watch for workflow changes
- Linear-compatible tracker adapter with normalized `Issue` model
- CLI workflow path selection and startup validation behavior

Tasks:

- Workflow loader
  - Implement workflow path discovery
  - Parse front matter and markdown body
  - Define normalized workflow definition object
  - Surface actionable config validation errors
- Config layer
  - Define typed settings accessors
  - Implement default values and `$ENV` indirection
  - Implement path normalization
  - Include explicit support for `agent.max_turns`
  - Add dispatch preflight validation
  - Implement reload semantics and change application rules
  - Preserve the last known good effective configuration on invalid reload
- CLI and host lifecycle
  - Accept an explicit workflow path argument
  - Default to `./WORKFLOW.md` when no explicit path is provided
  - Fail clearly on nonexistent explicit path or missing default workflow file
  - Surface startup failure and host exit semantics cleanly
- Tracker integration
  - Define stable internal issue DTOs
  - Implement candidate issue fetch
  - Implement candidate pagination
  - Use project `slugId` filtering for Linear candidate fetch
  - Implement `fetch_issues_by_states(state_names)` for startup cleanup
  - Implement issue state refresh by IDs
  - Use GraphQL `[ID!]` typing for refresh queries
  - Implement terminal-issue fetch for startup cleanup
  - Implement normalization and error mapping
  - Normalize `labels`, `blocked_by`, and `priority` according to spec rules
- Tests
  - Unit tests for workflow parsing
  - Unit tests for config validation
  - Contract tests for tracker normalization
  - CLI path precedence and startup failure tests

Acceptance:

- Invalid workflow config fails clearly before dispatch
- Workflow reload updates effective config without process restart
- Invalid workflow reload keeps the last known good effective configuration active
- Tracker client returns normalized issues compatible with orchestrator input needs
- CLI path selection and startup failure behavior match spec expectations

### M2. Workspace and Agent Runner MVP

Goal: Make one issue runnable end-to-end outside of the full scheduler.

Scope:

- Workspace manager
- Workspace lifecycle hooks
- Prompt construction
- Coding-agent app-server client
- Single issue worker attempt execution path

Tasks:

- Workspace manager
  - Implement issue identifier sanitization
  - Implement workspace path resolution
  - Implement create/reuse behavior
  - Implement terminal cleanup
  - Enforce filesystem safety invariants
- Hooks
  - Implement `after_create`, `before_run`, `after_run`, `before_remove`
  - Add hook timeout handling
  - Define hook failure semantics
- Prompting
  - Implement strict template rendering
  - Provide `issue` and `attempt` context
  - Implement retry/continuation prompt semantics
  - Use full prompt on first turn and continuation guidance on later turns in the same thread
- Agent runner
  - Launch coding-agent app-server subprocess via `bash -lc <codex.command>` in the workspace cwd
  - Implement `initialize`, `initialized`, `thread/start`, and `turn/start` handshake sequence
  - Implement turn start/stream/read loop
  - Separate stdout protocol parsing from stderr logging
  - Enforce request read timeout, turn timeout, and stall timeout behavior
  - Parse runtime events into normalized internal messages
  - Map failures, timeouts, approvals, and user-input-required events according to documented
    policy
- Runner harness
  - Implement a direct command or test harness that runs one issue attempt without the poll loop

Acceptance:

- A single issue can be executed end-to-end with workspace creation, prompt rendering, agent launch,
  streamed updates, and clean shutdown
- Hook failures and agent failures are surfaced deterministically
- Agent runtime events can be consumed by orchestrator-facing code
- The worker can execute multiple turns on the same live thread up to `agent.max_turns`

### M3. Orchestrator Core

Goal: Deliver the minimum conforming backend control loop.

Scope:

- Polling loop
- Candidate selection
- Global concurrency control
- Running/claimed state tracking
- Retry queue with continuation retry and exponential backoff
- Reconciliation of active runs
- Startup terminal workspace cleanup

Tasks:

- State model
  - Define runtime state structures for running sessions, claimed issues, retry attempts, and token
    totals
  - Define runtime event types emitted from workers to orchestrator
  - Model normal-exit continuation retry separately from failure-driven retry semantics
- Poll loop
  - Implement periodic candidate fetch
  - Implement dispatch ordering and eligibility rules
  - Implement slot accounting
  - Apply per-state concurrency limits
  - Enforce blocker rule for `Todo` issues
- Dispatch and worker lifecycle
  - Spawn worker attempts
  - Track live session metadata
  - Release claims on completion or terminal exit
  - Schedule short continuation retry after normal worker exit
  - Schedule exponential-backoff retry after abnormal worker exit
- Reconciliation
  - Refresh tracker state for active issues
  - Stop workers whose issues are terminal or non-active
  - Trigger terminal cleanup when required
- Startup recovery
  - Sweep terminal workspaces on startup
  - Rebuild runtime state from tracker and filesystem where applicable
- Testing
  - Deterministic state-machine tests
  - Failure and retry path tests
  - Concurrency boundary tests

Acceptance:

- Orchestrator can continuously poll and dispatch eligible issues
- Normal worker exit schedules the required short continuation retry
- Failed attempts enter retry with bounded exponential backoff
- Terminal state transitions stop runs and clean workspaces when required
- Restarting the service does not require a database to resume correct dispatch behavior

### M4. Observability and Operational Surface

Goal: Make the system operable and debuggable.

Scope:

- Structured logs
- Runtime snapshot API
- Optional HTTP server
- Basic operator control endpoints
- Django admin visibility for audit/debug support

Tasks:

- Logging
  - Define structured log schema
  - Include `issue_id`, `issue_identifier`, `session_id`, retry metadata, and error context
  - Separate operator-facing summaries from raw protocol details
- Metrics and runtime accounting
  - Track token totals and runtime totals
  - Track latest rate-limit payload
  - Maintain snapshot serialization helpers
- HTTP extension
  - Add `GET /api/v1/state` as the baseline runtime snapshot endpoint
  - Add `GET /api/v1/<issue_identifier>` as the baseline issue debug endpoint
  - Add `/api/v1/refresh`
  - Add error envelope conventions
  - Add any extra endpoints only as implementation-specific extensions beyond the baseline spec
- Admin/debug support
  - Expose recent runs, configuration state, and operational events where useful
  - Keep admin as secondary visibility, not orchestration control
- Tests
  - API shape tests
  - Snapshot correctness tests
  - Logging contract tests

Acceptance:

- Operators can understand current system state from logs and snapshot APIs alone
- Dashboard clients can consume a stable read model without duplicating orchestration logic
- Operational refresh and debugging endpoints behave predictably
- If the HTTP extension is shipped, its baseline endpoints align with the spec contract

### M5. Angular Dashboard

Goal: Provide a useful operator dashboard without moving orchestration logic into the frontend.

Scope:

- Dashboard shell
- Runtime overview
- Active sessions view
- Retry queue view
- Issue/run detail view
- Manual refresh and basic operator actions
- Tokenized design system implementation

Tasks:

- Frontend structure
  - Define feature-based Angular app structure
  - Add generated API client integration
  - Establish app-wide error/loading handling
  - Wire Tailwind to shared design tokens and theme primitives
- Dashboard features
  - Overview cards for runtime totals and health
  - Running sessions table
  - Retry queue table
  - Recent events and errors panel
  - Run detail drill-down
- Interaction model
  - Manual refresh
  - Polling or push update strategy
  - Error recovery states
- UI quality
  - Use design tokens instead of hard-coded color, spacing, or typography values
  - Responsive layout
  - Operator-friendly data formatting
  - E2E coverage for core dashboard flows

Acceptance:

- The dashboard reflects runtime state entirely from backend APIs
- Operators can inspect active work, retries, and recent failures without terminal access
- Frontend remains a consumer of backend state, not a second orchestrator
- Theme and component styling are driven by tokens rather than one-off utility values

### M6. Hardening and Production Readiness

Goal: Validate the system under realistic operational conditions.

Scope:

- Failure injection
- Integration testing
- Security and secret handling review
- Deployment and service supervision
- Runbooks and operational documentation

Tasks:

- Failure scenarios
  - Tracker API failures
  - Agent startup failures
  - Hook timeouts
  - Workspace permission/path failures
  - Orchestrator restart during active load
- Operational hardening
  - Secret loading review
  - Safe default bind host and HTTP exposure rules
  - Signal handling and graceful shutdown
  - Log rotation or sink integration
- Deployment
  - Define process model for API, orchestrator, and frontend
  - Add production configuration examples
  - Add health checks and supervision guidance
- Documentation
  - Local dev guide
  - Deployment guide
  - Incident response and operator runbook

Acceptance:

- Core flows are covered by integration tests
- Common failure classes have documented behavior and recovery steps
- The system can be deployed and supervised with clear operational guidance

## 4. Cross-Cutting Workstreams

These workstreams span multiple milestones and should not be left to the end.

### 4.1 API Contract Discipline

- Keep Angular bound to OpenAPI-generated types where practical
- Version operator APIs conservatively
- Avoid exposing internal protocol noise directly to the frontend

### 4.2 Testing Strategy

- Unit tests for config, normalization, prompt rendering, and state transitions
- Integration tests for tracker, workspace, and agent runner boundaries
- End-to-end tests for the backend control loop
- UI tests only after backend snapshot APIs stabilize

### 4.3 Security and Safety

- Validate all workspace paths before filesystem operations
- Avoid leaking secrets into prompts, logs, and hook environments
- Bound hook runtime and agent wait states
- Treat input-required turns as explicit failures unless policy changes

### 4.4 Operational Simplicity

- Prefer one orchestrator instance per deployment unless leadership/locking is explicitly designed
- Avoid introducing Celery or distributed schedulers in the first implementation
- Keep the system understandable from logs plus runtime snapshot alone

### 4.5 UI Token Discipline

- Define semantic tokens first, then map them to Tailwind usage
- Keep raw palette values and sizing primitives centralized
- Prefer CSS variable backed tokens for runtime theming flexibility
- Avoid component-level hard-coded utility values when an existing token should be used

## 5. Recommended Team Slicing

If multiple engineers are involved, split work by ownership boundaries:

- Engineer A: workflow/config/tracker
- Engineer B: workspace/agent runner
- Engineer C: orchestrator/runtime state/observability API
- Engineer D: Angular dashboard and generated client

If only one engineer is implementing:

- Complete M0 to M3 before serious investment in M5
- Do not start dashboard work before snapshot API shapes are stable

## 6. Exit Criteria for First Production-Usable Version

The first production-usable version should include:

- M0 through M4 completed
- M5 optional, unless the team explicitly needs a browser-based operator surface
- At least one real tracker integration profile tested against a non-mock environment
- Operator runbook for startup, shutdown, restart, and failure triage

Recommended cut line for `v0.1`:

- Backend-only conforming implementation with structured logs and snapshot API
- No requirement for Angular dashboard yet

Recommended cut line for `v0.2`:

- Dashboard added
- Operator quality-of-life improvements
- Stronger integration coverage and deployment polish
