# Roadmap

Status: Planning snapshot as of 2026-03-10

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

This means the repository is no longer blocked on foundational orchestration plumbing. The main
remaining work now falls into three buckets:

- core conformance work needed to close remaining `docs/SPEC.md` gaps
- recommended extensions explicitly called out by `docs/SPEC.md`
- product and UI work that improves the system but is not required for spec conformance

## Core Conformance Workstreams

These items are the remaining larger workstreams that most directly affect alignment with the core
behavior expected by `docs/SPEC.md`.

### 1. Structured Logging and Observability Maturity

The repository has runtime snapshots and an HTTP observability surface, but not a fully realized
structured logging layer.

Current limitation:
- required issue/session-scoped structured logs are incomplete
- several failure paths are not operator-visible enough
- hook failures and app-server stderr diagnostics are not fully surfaced
- token accounting semantics still need to be hardened

Scope examples:
- structured `key=value` lifecycle logs for issue dispatch, worker exit, retry scheduling, reload,
  reconciliation, and startup failures
- hook start/failure/timeout logging with safe truncation
- stderr diagnostic logging for app-server processes
- stronger token/rate-limit aggregation semantics
- closure of the currently documented spec gaps in `docs/SPEC_GAPS.md`

Why it matters:
- This is the next layer of operator readiness after the core runtime exists.
- It closes multiple remaining core conformance gaps without changing the orchestration boundary.

### 2. Workspace and Runtime Polish Gaps

Several smaller runtime gaps remain that are better treated as one cleanup tranche than as isolated
micro-projects.

Current limitation:
- workspace prep does not remove temporary artifacts such as `tmp` and `.elixir_ls`
- prompt-rendering error taxonomy is still coarser than the spec
- a few runtime behaviors are implemented correctly in spirit but not yet at the exact spec surface

Scope examples:
- add workspace prep cleanup before agent launch
- split template parse vs template render error classes
- finish the smaller core items tracked in `docs/SPEC_GAPS.md`

Why it matters:
- These are the remaining smaller core conformance items outside the larger observability slice.
- Grouping them keeps the cleanup work visible instead of scattering it across unrelated tasks.

## Recommended Extension Workstreams

These items are explicitly compatible with `docs/SPEC.md` and are called out there as recommended
extensions or follow-on implementation work, but they are not required for basic core conformance.

### 1. Restart Recovery and State Persistence

This is the most important remaining recommended extension workstream.

Current limitation:
- Orchestrator state is still effectively in-memory for scheduling and live session metadata.
- Process restart loses retry queue timing and running-session summary state.

Minimum scope:
- persist retry queue entries
- persist session metadata and running-entry summaries
- load persisted recovery state during orchestrator startup
- deterministically settle or requeue in-flight runs that cannot be resumed
- add restart-recovery tests and corrupted-state fallback tests

Why it matters:
- This closes the biggest remaining operational gap in long-running service behavior.
- It is the clearest next step toward stronger restart recovery without introducing a database.

### 2. Configurable Observability Settings

This is a smaller extension that becomes more useful once the structured logging layer exists.

Current limitation:
- observability and logging behavior are not yet configurable through workflow front matter

Possible scope:
- workflow-front-matter settings for log sinks, verbosity, or snapshot behavior
- typed config and validation for observability-specific settings

Why it matters:
- It gives operators more control without prescribing a UI implementation.
- It is useful, but secondary to restart recovery and core observability correctness.

### 3. First-Class Tracker Write APIs

This remains a follow-on extension rather than a core runtime gap.

Current limitation:
- tracker writes such as comments, state transitions, and PR metadata are still expected to happen
  via agent tools rather than a Symphony-owned API surface

Possible scope:
- backend APIs or tool surfaces for tracker comments
- backend APIs or tool surfaces for state transitions
- normalized write/error semantics around tracker mutations

Why it matters:
- It could reduce prompt/tooling drift and make tracker-side workflow behavior more explicit.
- It is not the highest-priority gap while recovery and observability are still incomplete.

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
- `Core Conformance Workstreams` describe grouped implementation themes needed to close remaining
  core gaps
- `Recommended Extension Workstreams` describe follow-on work explicitly compatible with the spec
- `Product and UI Workstreams` describe delivery work that improves the product but is not required
  for spec conformance

## Suggested Priority Order

1. Structured logging and observability maturity
2. Workspace and runtime polish gaps
3. Restart recovery and state persistence
4. Configurable observability settings
5. Angular frontend runtime pages
6. First-class tracker write APIs

## Next Planning Move

When one workstream becomes the active implementation target, `docs/EXEC_PLAN.md` should be updated
or replaced with a focused execution plan for that slice rather than trying to use this roadmap as
an implementation checklist.
