# Roadmap

Status: Updated after Milestone 4 re-audit on 2026-03-10

Purpose: Record the major remaining implementation work after the core Symphony execution path
landed, grouped by how each item relates to `docs/SPEC.md`.

Related documents:
- `docs/SPEC.md`: normative product and behavior contract
- `docs/SPEC_GAPS.md`: confirmed spec gap audit
- `docs/EXEC_PLAN.md`: current or next active execution plan

## Completed Foundation

The current implementation already has the main execution spine in place:

- workflow loading, typed config, and live `WORKFLOW.md` reload
- tracker polling and issue normalization
- workspace creation, reuse, and cleanup
- streamed app-server session handling
- single-issue worker harness
- orchestrator dispatch, retry, and reconciliation
- runtime snapshot export and JSON status endpoints
- optional loopback HTTP dashboard/control surface

This means the repository is no longer blocked on foundational orchestration plumbing. After the
2026-03-10 re-audit, the main remaining work is product delivery plus the still-optional tracker
write extension.

## Recently Completed

### Structured Logging and Observability Maturity

This workstream is complete.

Delivered behavior:
- stable `key=value` logs for tracker candidate fetch failures, running-state refresh failures,
  workflow reload failures, startup cleanup failures, retry scheduling, and worker exits
- hook lifecycle logs for start, timeout, and failure while preserving best-effort behavior for
  non-fatal hooks
- app-server `stderr` diagnostics surfaced through operator-visible logs with issue/session context
- token and rate-limit snapshot behavior covered by focused backend tests

Validation recorded in `docs/EXEC_PLAN.md`:
- baseline backend suite: `155 passed in 13.56s`
- Milestone 1 focused suite: `109 passed in 12.14s`

### Workspace and Runtime Polish Gaps

This workstream is complete.

Delivered behavior:
- per-attempt workspace prep removes `tmp` and `.elixir_ls` safely before hooks and agent launch
- prompt template parse failures and render failures use distinct typed error codes
- token aggregation accepts event-defined absolute totals without double-counting repeated updates or
  polluting totals with delta-only payloads

Validation recorded in `docs/EXEC_PLAN.md`:
- Milestone 2 focused suite: `87 passed in 9.48s`

### Restart Recovery and State Persistence

This workstream is complete.

Delivered behavior:
- retry queue entries and prior session metadata persist to a recovery file with atomic replace
  semantics
- startup restores retry timing, converts recovered running entries into retry rows, and tolerates
  corrupt recovery state with warning logs
- runtime snapshots and issue-detail state preserve prior session summaries across restart recovery

Validation recorded in `docs/EXEC_PLAN.md`:
- Milestone 3 focused suite: `98 passed in 4.22s`

### Configurable Observability Settings

This workstream is complete.

Delivered behavior:
- `WORKFLOW.md` front matter supports typed `observability` settings for snapshot, refresh-request,
  recovery paths, and snapshot freshness
- management-command startup and orchestrator workflow reloads apply those settings to future
  runtime writes
- backend tests cover the configured-path and reload behavior

Validation recorded in `docs/EXEC_PLAN.md`:
- Milestone 4 focused suite: `98 passed in 4.22s`

## Core Conformance Workstreams

No currently confirmed core conformance workstreams remain after the 2026-03-10 re-audit.

## Recommended Extension Workstreams

These items remain explicitly compatible with `docs/SPEC.md`, but they are not required for
baseline conformance.

### 1. First-Class Tracker Write APIs

This remains the primary backend extension still open from the roadmap.

Possible scope:
- backend APIs or tool surfaces for tracker comments
- backend APIs or tool surfaces for state transitions
- normalized write/error semantics around tracker mutations

Why it matters:
- tracker writes such as comments, state transitions, and PR metadata are still expected to happen
  via agent tools rather than a Symphony-owned API surface
- It could reduce prompt/tooling drift and make tracker-side workflow behavior more explicit.

## Product and UI Workstreams

These items improve usability and product completeness, but they are not required for spec
conformance.

### 1. Angular Frontend Runtime Pages

The Angular frontend is still effectively unimplemented.

Current limitation:
- `apps/web` contains entrypoints, styles, and feature placeholders, but not actual runtime pages
- the only current operator UI is the server-rendered read-only dashboard served by Django
- there is not yet a real frontend dashboard implemented in Angular

Likely feature slices:
- dashboard overview page
- issue detail/runtime debugging page
- runs/retry queue page
- client consumption of existing `/api/v1/*` runtime endpoints

Frontend dashboard scope:
- build a real Angular dashboard page as the operator landing surface
- show aggregate runtime counts, retry queue state, token/runtime totals, and workflow status
- show active issue rows with links into issue-level runtime detail views
- expose refresh controls backed by `/api/v1/refresh`
- preserve the current backend-rendered dashboard as a minimal fallback or transitional surface until
  the Angular dashboard is production-ready

Suggested minimum frontend deliverable:
- one Angular dashboard route consuming `/api/v1/state`
- one issue detail route consuming `/api/v1/<issue_identifier>`
- one retry/runs view derived from the existing runtime APIs
- basic loading, empty, unavailable, and stale-state handling

Why it matters:
- This is the largest missing user-facing surface.
- It should consume backend runtime APIs rather than duplicating orchestration logic.

## Relationship to SPEC_GAPS

`docs/SPEC_GAPS.md` is the authoritative list of currently confirmed spec gaps.

This roadmap is broader:
- `docs/SPEC_GAPS.md` currently reports no confirmed core conformance gaps
- `Recommended Extension Workstreams` describe follow-on work explicitly compatible with the spec
- `Product and UI Workstreams` describe delivery work that improves the product but is not required
  for spec conformance

## Suggested Priority Order

1. Angular frontend runtime pages
2. First-class tracker write APIs

## Next Planning Move

When one workstream becomes the active implementation target, `docs/EXEC_PLAN.md` should be updated
or replaced with a focused execution plan for that slice rather than trying to use this roadmap as
an implementation checklist.
