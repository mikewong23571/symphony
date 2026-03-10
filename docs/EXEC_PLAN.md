# Agent Runner Streaming, Worker Harness, and Orchestrator Core

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

Symphony already has the foundation required to load `WORKFLOW.md`, validate typed runtime config,
normalize Linear issues, create safe workspace directories, and render prompts. What it cannot do
yet is run a real coding turn to completion. The current app-server client stops after the startup
handshake, so there is no streamed turn processing, no turn timeout handling, no stall handling,
and no single-issue worker that can prove end-to-end behavior before the poll loop exists.

The next usable milestone is not “start the orchestrator.” The next usable milestone is: given one
issue and a fake or real Codex app-server, Symphony can start a turn, stream protocol messages
until the turn ends, normalize the important events, terminate stuck runs deterministically, and
reuse the same session/thread for continuation turns. Once that exists, the worker harness can wrap
it for one issue, and the orchestrator core can consume the exact same normalized event stream
without inventing a second protocol abstraction.

When this plan is complete, a contributor will be able to run focused unit tests for streamed turn
handling, run a single-issue harness against a fake app-server, and then start the Django
management command with confidence that the remaining orchestrator work is about scheduling and
state transitions rather than low-level Codex protocol uncertainty.

## Progress

- [x] 2026-03-10 06:49Z: Identified dynamic `WORKFLOW.md` reload/re-apply as the next required
  conformance gap from `docs/SPEC.md` Section 6.2 / 18.1. Confirmed that
  `apps/api/symphony/management/commands/run_orchestrator.py` still loaded workflow/config only
  once at startup and that `apps/api/symphony/orchestrator/core.py` held those values for the
  lifetime of the process.
- [x] 2026-03-10 06:49Z: Added `apps/api/symphony/workflow/runtime.py` as the workflow runtime
  controller, wired `run_orchestrator` to boot from it, and taught
  `apps/api/symphony/orchestrator/core.py` to defensively reload and re-apply workflow config
  before startup/tick/retry dispatch while preserving the last known good config on invalid reload.
- [x] 2026-03-10 06:49Z: Hardened workspace-root reload behavior by storing per-running-entry
  workspace paths in `apps/api/symphony/orchestrator/core.py` and adding
  `WorkspaceManager.remove_workspace_path(...)` in `apps/api/symphony/workspace/manager.py` so
  cleanup/snapshots for in-flight runs continue to target the original workspace root after later
  config changes.
- [x] 2026-03-10 06:49Z: Added focused coverage in
  `apps/api/tests/unit/workflow/test_runtime.py` plus dynamic reload scenarios in
  `apps/api/tests/unit/orchestrator/test_core.py`, covering successful reload, invalid-reload
  fallback, prompt/poll/workspace re-apply for future dispatches, and recovery after a broken
  workflow file is fixed.
- [x] 2026-03-10 06:49Z: Validated the touched backend surface with
  `uv run ruff check apps/api/symphony/workflow apps/api/symphony/orchestrator apps/api/symphony/workspace apps/api/symphony/management/commands/run_orchestrator.py apps/api/tests/unit/workflow apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/management/test_run_orchestrator.py`,
  `uv run mypy apps/api`, and
  `uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/management/test_run_orchestrator.py -q`
  (`62 passed in 2.56s`).
- [x] 2026-03-10 06:49Z: Reran the repository quality gates after the reload slice:
  `make lint`, `make typecheck`, and `make test`, ending at `164 passed in 11.77s` for backend
  pytest and frontend vitest exiting `0` with `--passWithNoTests`.
- [x] 2026-03-10 07:18Z: Closed the post-review gaps in the reload slice by adding a background
  workflow watch loop plus reload listeners in `apps/api/symphony/workflow/runtime.py`, wiring the
  orchestrator to apply watched updates immediately instead of waiting for the next tick, switching
  `after_run` hook execution in `apps/api/symphony/agent_runner/harness.py` to read the latest live
  config, and extending focused tests for watcher-driven reload plus invalid-retry requeueing.
- [x] 2026-03-10 07:42Z: Tightened the watcher/retry lifecycle after follow-up review by removing
  dead reload-control branches in `apps/api/symphony/orchestrator/core.py`, making the workflow
  watch loop log-and-retry instead of silently exiting on unexpected exceptions, cleaning stale
  retry workspaces when `workspace.root` changes during the wait window, adding a reuse-across-
  orchestrator-lifecycles regression, and replacing the listener-removal fixed sleep with a watcher-
  fired assertion.
- [x] 2026-03-10 07:55Z: Reran the full repository quality gates after the final reload-lifecycle
  fixes: `make lint`, `make typecheck`, and `make test` all passed, ending at `175 passed in
  14.30s` for backend pytest and frontend vitest exiting `0` with `--passWithNoTests`.
- [x] 2026-03-10 00:53Z: Confirmed the repository baseline against `docs/SPEC.md` and the current
  code. `apps/api/symphony/workflow/loader.py`, `apps/api/symphony/workflow/config.py`,
  `apps/api/symphony/tracker/linear.py`, `apps/api/symphony/tracker/linear_client.py`,
  `apps/api/symphony/workspace/manager.py`, and `apps/api/symphony/agent_runner/prompting.py`
  already implement the workflow/config/tracker/workspace/prompting foundation.
- [x] 2026-03-10 00:53Z: Verified that the current app-server client in
  `apps/api/symphony/agent_runner/client.py` performs the startup handshake (`initialize`,
  `initialized`, `thread/start`, `turn/start`) and that the focused backend unit suite passes.
- [x] 2026-03-10 00:53Z: Ran the baseline command
  `uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/tracker apps/api/tests/unit/workspace apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_client.py`
  from the repository root and observed `75 passed in 1.64s`.
- [x] 2026-03-10 01:53Z: Implemented full streamed turn handling in
  `apps/api/symphony/agent_runner/client.py`, `apps/api/symphony/agent_runner/events.py`, and
  `apps/api/symphony/agent_runner/runner.py`, including terminal turn parsing, malformed stdout
  handling, approval auto-approval, unsupported tool rejection, user-input-required failure,
  `turn_timeout`, and `stall_timeout`.
- [x] 2026-03-10 01:53Z: Implemented the single-issue worker harness in
  `apps/api/symphony/agent_runner/harness.py`, including workspace creation/reuse, required/best-
  effort hooks, prompt rendering, continuation turns on a shared `thread_id`, tracker state
  refresh, and typed attempt results.
- [x] 2026-03-10 01:53Z: Implemented orchestrator core in
  `apps/api/symphony/orchestrator/core.py`, including candidate selection, blocker enforcement,
  running/claimed/retry state, startup terminal cleanup, active-run reconciliation, stall-driven
  cancellation, continuation retry, and exponential backoff retry.
- [x] 2026-03-10 01:53Z: Integrated the management command with the real orchestrator and added a
  `--once` mode in `apps/api/symphony/management/commands/run_orchestrator.py` so tests and manual
  smoke runs can execute one startup-cleanup + dispatch cycle without blocking indefinitely.
- [x] 2026-03-10 01:53Z: Validated the backend surface with
  `uv run ruff check apps/api`, `uv run mypy apps/api`, and `uv run pytest`, ending at
  `103 passed in 6.52s`.
- [x] 2026-03-10 04:06Z: Added the first runtime snapshot surface from orchestrator state in
  `apps/api/symphony/orchestrator/core.py` and exposed `GET /api/v1/state` via
  `apps/api/symphony/api/` + `apps/api/config/urls.py`, including running rows, retry rows,
  aggregate Codex totals, and latest rate limits.
- [x] 2026-03-10 04:06Z: Added focused coverage in
  `apps/api/tests/unit/orchestrator/test_core.py` and `apps/api/tests/unit/api/test_state.py` and
  validated the touched backend surface with
  `uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/api/test_state.py`
  (`13 passed in 0.75s`) plus `uv run mypy apps/api`.
- [x] 2026-03-10 05:20Z: Replaced the `/api/v1/state` in-process-only provider dependency with a
  file-backed runtime snapshot bridge in `apps/api/symphony/observability/runtime.py`, kept the
  orchestrator as the snapshot owner/publisher from `apps/api/symphony/orchestrator/core.py`,
  aligned API errors to the spec envelope in `apps/api/symphony/api/views.py`, and added focused
  coverage for cross-process reads plus `405 Method Not Allowed`.
- [x] 2026-03-10 05:35Z: Hardened the snapshot bridge so observability file publish/cleanup
  failures do not break orchestrator correctness, let `/api/v1/state` keep serving the live
  in-process provider when file refresh fails, and switched snapshot temp writes to unique files to
  avoid same-path writer collisions.
- [x] 2026-03-10 06:10Z: Moved the runtime snapshot bridge out of `apps/api/symphony/api/` and
  into `apps/api/symphony/observability/runtime.py` so the optional HTTP layer stays read-only and
  the orchestrator depends on observability infrastructure rather than API views.
- [x] 2026-03-10 06:45Z: Fixed the post-review correctness and robustness issues in the first
  observability slice: `turn_count` now tracks distinct observed `turn_id`s, runtime snapshot
  refresh no longer performs file publication while holding the orchestrator's async state lock,
  stale file-backed snapshots are rejected, default snapshot file names are process-specific, retry
  snapshot rows no longer store redundant monotonic due times, and the focused tests now cover
  repeated same-turn events plus stale snapshot rejection.
- [x] 2026-03-10 07:20Z: Added `GET /api/v1/<issue_identifier>` as the first issue-scoped runtime
  debug endpoint, deriving read-only detail responses from the existing runtime snapshot bridge,
  extending snapshot rows with attempt/workspace metadata, and covering running/retrying/404/405
  API behavior plus the new snapshot fields in focused tests.
- [x] 2026-03-10 07:45Z: Fixed the follow-up snapshot regression in
  `apps/api/symphony/orchestrator/core.py` so runtime snapshot serialization now uses a best-
  effort workspace-path fallback for degenerate issue identifiers instead of raising from
  `resolve_workspace_path(...)`, and added focused orchestrator coverage for running/retrying rows
  with invalid workspace identifiers.
- [x] 2026-03-10 05:49Z: Added `POST /api/v1/refresh` as the first operational control trigger,
  implemented a file-backed refresh-request bridge in `apps/api/symphony/observability/runtime.py`,
  taught `apps/api/symphony/orchestrator/core.py` to consume coalesced refresh requests between poll
  cycles, and added focused API/orchestrator coverage for request queueing, method handling, stale
  parent-path behavior, and early wake-up from the wait loop.
- [x] 2026-03-10 05:57Z: Fixed the follow-up `/api/v1/refresh` usability regression by marking the
  operational trigger endpoint CSRF-exempt in `apps/api/symphony/api/views.py` and adding an
  `enforce_csrf_checks=True` API test so curl/dashboard-style clients can use the trigger under the
  default Django middleware stack.
- [x] 2026-03-10 06:33Z: Completed the optional HTTP observability/control slice by adding typed
  `server.port` workflow config in `apps/api/symphony/workflow/config.py`, CLI `--port` override
  plus loopback WSGI sidecar startup in
  `apps/api/symphony/management/commands/run_orchestrator.py` and
  `apps/api/symphony/api/server.py`, and a read-only dashboard at `/` in
  `apps/api/symphony/api/views.py` backed by the existing runtime snapshot bridge while preserving
  `/healthz`, `/api/v1/state`, `/api/v1/<issue_identifier>`, and `/api/v1/refresh`.
- [x] 2026-03-10 06:33Z: Closed the follow-up review items for the HTTP slice by making the
  dashboard and read-only JSON endpoints CSRF-exempt so unsupported methods still return spec-style
  `405` responses under the default Django middleware stack, adding a real HTTP server lifecycle
  test in `apps/api/tests/unit/api/test_server.py`, deduplicating dashboard issue-link rendering,
  tightening `server.port` validation, and rerunning the full quality gates:
  `make lint`, `make typecheck`, and `make test` (`160 passed in 11.49s` backend pytest; frontend
  vitest exited `0` with `--passWithNoTests`).

## Surprises & Discoveries

- Observation: Dynamic workspace-root reload is not just a future-dispatch concern. If the
  orchestrator recomputes workspace paths from the latest root for already-running issues, runtime
  snapshots and terminal cleanup can silently point at the wrong directory.
  Evidence: Before the fix, `RunningEntry` stored only the issue identifier and
  `_cleanup_workspace(...)` always resolved through the current `WorkspaceManager`, so a later
  `workspace.root` change would redirect cleanup away from the original worker path.

- Observation: A last-known-good fallback alone is not enough for invalid reload handling; new
  dispatches also need an explicit gate or Symphony will continue launching fresh work from stale
  policy after the operator has already broken `WORKFLOW.md`.
  Evidence: `docs/SPEC.md` Section 6.2 requires preserving the last good config on invalid reload,
  while Section 6.3 says workflow read/YAML errors block new dispatches until fixed.

- Observation: “Watch the workflow file” and “re-check before dispatch” are two separate
  requirements, not interchangeable approximations of the same thing.
  Evidence: The review found that tick/retry-only reload logic still let prompt/concurrency/hook
  changes sit stale for one full poll interval, while `docs/SPEC.md` Section 6.2 explicitly treats
  defensive per-dispatch reload as a fallback in case filesystem watch events are missed.

- Observation: Workspace-root reload can leak retry workspaces even when running-entry cleanup is
  already correct.
  Evidence: The follow-up review found that retry rows were immediately repointed at the new root,
  so a failed attempt that had already created a workspace under the old root would never be
  removed unless the reload path explicitly scheduled best-effort cleanup of the stale directory.

- Observation: The typed config layer is ahead of the runtime. The defaults for
  `codex.turn_timeout_ms`, `codex.read_timeout_ms`, and `codex.stall_timeout_ms` already exist in
  `apps/api/symphony/workflow/config.py`, even though only the startup handshake currently consumes
  `read_timeout_ms`.
  Evidence: `CodexConfig` includes all three fields, while `apps/api/symphony/agent_runner/client.py`
  currently accepts only `read_timeout_ms` in the live protocol path.

- Observation: The spec assigns stall detection to the coordination layer, not to the raw stdout
  parser. That means stall logic should not be buried in the lowest-level JSON line reader.
  Evidence: `docs/SPEC.md` Section 10.6 defines `codex.stall_timeout_ms` as “enforced by
  orchestrator based on event inactivity.”

- Observation: The current management command intentionally stops at config validation and prints a
  skeleton message. This is useful because it keeps the remaining gap visible and proves there is
  no hidden orchestrator implementation elsewhere in the repo.
  Evidence: `apps/api/symphony/management/commands/run_orchestrator.py` prints
  `Orchestrator skeleton created. Implementation is pending.`

- Observation: `--once` is needed even after the real orchestrator exists, because the default
  long-running loop is correct for production but wrong for deterministic unit tests and local
  smoke runs.
  Evidence: `apps/api/tests/unit/management/test_run_orchestrator.py` now patches
  `Orchestrator.run_once()` and `Orchestrator.run_forever()` separately and verifies both command
  paths without hanging the test process.

- Observation: A read-only API surface still needs a durable bridge when the orchestrator and
  Django are in separate processes. The smallest acceptable version here is an explicit snapshot
  file, not a second state machine inside Django.
  Evidence: The updated `/api/v1/state` tests read a snapshot written by the orchestrator after the
  in-process provider has been cleared, and still return `200`.

- Observation: Because the HTTP snapshot surface is optional, snapshot file I/O must not sit on the
  orchestrator's correctness path. Write or cleanup failures should degrade the status surface, not
  stop startup, event handling, or shutdown.
  Evidence: The hardened snapshot tests now force publish failures during startup and worker-event
  updates while the orchestrator continues serving its in-memory snapshot.

- Observation: Letting `GET /api/v1/state` republish the snapshot to disk subtly turns a read-only
  observability endpoint into a writer and inverts the intended module boundary.
  Evidence: The follow-up review found `apps/api/symphony/api/runtime.py` being imported by
  `apps/api/symphony/orchestrator/core.py`, and the view-path snapshot getter was writing the file
  again on every successful in-process read.

- Observation: Refreshing the exported snapshot while still holding the orchestrator's async state
  lock couples fast in-memory bookkeeping with potentially slow filesystem I/O in the same critical
  section.
  Evidence: The follow-up fixes moved `_refresh_runtime_snapshot()` out of the `async with
  self._lock` regions in event handling, retry dispatch, and reconciliation so the async lock now
  covers only in-memory state mutation.

- Observation: Django's default CSRF middleware runs before view method dispatch, so unsupported
  methods on read-only HTTP endpoints do not reliably surface as `405` unless those routes are
  explicitly exempted.
  Evidence: The follow-up HTTP review found that `POST /api/v1/state` and
  `POST /api/v1/<issue_identifier>` would return `403` under `enforce_csrf_checks=True` until
  `apps/api/symphony/api/views.py` marked those endpoints CSRF-exempt.

## Decision Log

- Decision: Implement dynamic workflow reload as a repository-local runtime controller
  (`apps/api/symphony/workflow/runtime.py`) instead of scattering file checks across the management
  command and orchestrator methods.
  Rationale: One controller can own the resolved workflow path, last-known-good definition/config,
  change detection, and reload error state. That keeps startup and runtime reload semantics aligned
  while preserving a small API for the orchestrator host.
  Date/Author: 2026-03-10 / Codex

- Decision: Preserve the last known good config for reconciliation/runtime bookkeeping, but block
  fresh dispatch/retry-dispatch when the latest workflow reload is invalid.
  Rationale: This is the smallest implementation that satisfies both sides of the spec: the service
  does not crash or lose its prior effective config, but it also does not continue launching new
  work from stale policy after `WORKFLOW.md` becomes unreadable or invalid.
  Date/Author: 2026-03-10 / Codex

- Decision: Store the concrete workspace path on each running entry and clean up by explicit path
  when a run ends, rather than always re-deriving the workspace path from the current manager root.
  Rationale: Reloaded `workspace.root` values should affect future runs, but must not retroactively
  rewrite the location of already-running workspaces or their terminal cleanup path.
  Date/Author: 2026-03-10 / Codex

- Decision: Add a small background watch thread inside `WorkflowRuntime` and use listener callbacks
  to push live config/error updates into the orchestrator event loop.
  Rationale: This satisfies the spec’s required on-change reload behavior without moving file-watch
  logic into Django or the orchestrator poll loop, while the existing tick/retry reload path
  remains as the defensive fallback if the watcher misses an update.
  Date/Author: 2026-03-10 / Codex

- Decision: When `workspace.root` changes, preserve the retry row’s original workspace path long
  enough to schedule a best-effort cleanup task before repointing future retry work to the new
  root.
  Rationale: Future attempts should honor the latest root, but a workspace created by an earlier
  failed attempt under the old root is still Symphony-owned state and should not be orphaned by the
  reload transition.
  Date/Author: 2026-03-10 / Codex

- Decision: Rewrite `docs/EXEC_PLAN.md` as a living execution document centered on the current
  implementation frontier rather than keeping a generic milestone roadmap.
  Rationale: The repository already contains substantial M1 and partial M2 work. A novice now needs
  precise sequencing, concrete file targets, and proof commands more than a broad architectural
  outline.
  Date/Author: 2026-03-10 / Codex

- Decision: Treat the immediate critical path as three consecutive layers: streamed agent runner,
  then single-issue worker harness, then orchestrator core.
  Rationale: The harness and orchestrator both depend on stable turn completion/error semantics,
  event normalization, and timeout behavior. Implementing them before the streamed runner would
  create duplicate protocol parsing and force later rewrites.
  Date/Author: 2026-03-10 / Codex

- Decision: Keep the raw app-server protocol logic and the higher-level runtime event semantics in
  separate modules.
  Rationale: `apps/api/symphony/agent_runner/client.py` already owns subprocess launch, stdin
  writes, and stdout JSON decoding. Timeout policy, approval policy, unsupported-tool handling, and
  normalized runtime events belong one layer up so both the worker harness and the orchestrator can
  consume the same abstraction.
  Date/Author: 2026-03-10 / Codex

- Decision: Implement stall handling in the worker-facing turn runner first, but make it use the
  same “last protocol activity” semantics that the orchestrator will later surface in runtime
  state.
  Rationale: The spec places stall policy in the coordination layer, but the repository needs a
  testable implementation before the full poll loop exists. A worker-facing watchdog gives that
  proof without forcing stall logic into the lowest-level parser.
  Date/Author: 2026-03-10 / Codex

- Decision: Keep continuation retry and failure retry scheduling inside the orchestrator, even
  though the worker harness now knows why a run ended.
  Rationale: Retry policy belongs to the single authoritative coordination layer. The harness
  returns typed outcomes; the orchestrator decides whether those outcomes mean continuation,
  exponential backoff, release, or cleanup.
  Date/Author: 2026-03-10 / Codex

- Decision: Implement the first `/api/v1/state` surface as an orchestrator-owned snapshot export
  plus a minimal API-provider registry, instead of rebuilding runtime state inside Django views.
  Rationale: The spec requires status surfaces to draw from orchestrator state. A provider registry
  keeps the view read-only and makes the “no live provider” case explicit without moving
  orchestration into request handlers.
  Date/Author: 2026-03-10 / Codex

- Decision: Promote the snapshot export to a small file-backed bridge shared by the orchestrator
  and Django, while keeping the in-process provider only as an optional same-process fallback.
  Rationale: The repository boundary is explicit that `run_orchestrator` is a separate long-running
  process. Publishing the already-built runtime snapshot atomically to disk preserves that boundary
  and makes `/api/v1/state` work without recreating orchestrator state in request handlers.
  Date/Author: 2026-03-10 / Codex

- Decision: Treat snapshot file publication and cleanup as best-effort side effects and never let
  them fail orchestrator lifecycle or live event handling.
  Rationale: `docs/SPEC.md` explicitly marks the snapshot/status surface as optional and not
  required for correctness. The in-memory orchestrator snapshot remains authoritative; the shared
  file is only a bridge for other processes.
  Date/Author: 2026-03-10 / Codex

- Decision: Move the runtime snapshot bridge into `apps/api/symphony/observability/` and keep the
  Django view strictly read-only.
  Rationale: The code map assigns runtime snapshots to the observability layer, and `docs/SPEC.md`
  treats the HTTP server as an optional extension. The orchestrator should publish snapshots
  through observability infrastructure; `GET /api/v1/state` should only read the best available
  snapshot source.
  Date/Author: 2026-03-10 / Codex

- Decision: Treat `turn_count` as “number of distinct turn IDs observed in the current worker
  session” instead of “number of turn transitions.”
  Rationale: The snapshot/status surface needs a stable count that does not depend on the order of
  repeated events within one turn. Tracking seen `turn_id`s removes the off-by-one ambiguity from
  the initial event and matches the worker-facing semantics that operators care about.
  Date/Author: 2026-03-10 / Codex

- Decision: Reject stale file-backed snapshots and use process-specific default snapshot paths.
  Rationale: The JSON API should not present arbitrarily old runtime state as live when the
  orchestrator has exited or multiple local orchestrators are sharing one machine. Expiry metadata
  and PID-scoped default paths keep the first observability surface honest without introducing a
  larger coordination mechanism.
  Date/Author: 2026-03-10 / Codex

- Decision: Implement the optional HTTP extension as a small loopback-only WSGI sidecar started by
  `run_orchestrator`, and keep it outside the orchestrator correctness path.
  Rationale: `docs/SPEC.md` treats HTTP as an extension, not a second authority. Starting a small
  server only when `--port` or `server.port` is configured preserves the boundary while making the
  existing snapshot bridge and control trigger directly usable from a browser or curl.
  Date/Author: 2026-03-10 / Codex

- Decision: Mark the dashboard and read-only JSON observability endpoints CSRF-exempt.
  Rationale: The spec requires unsupported methods on defined routes to return `405 Method Not
  Allowed`. Under Django's default middleware stack, CSRF checks happen before the view can return
  its method error, so explicit exemption is the smallest way to keep the routes read-only while
  preserving the documented HTTP behavior.
  Date/Author: 2026-03-10 / Codex

## Outcomes & Retrospective

- 2026-03-10: Extended the orchestrator from startup-only workflow loading to live workflow
  re-application for future work. Symphony now notices `WORKFLOW.md` changes before startup/ticks
  and retry dispatches, updates future prompt/config/workspace behavior without restart, and keeps
  in-flight workers on their original settings.
- 2026-03-10: Closed the most obvious post-core conformance gap from the spec. The remaining
  follow-on work is no longer “can Symphony adapt to workflow changes at runtime?” but rather
  product extensions such as richer observability/log surfaces, persistence across restarts, and
  optional tracker-tooling extensions.
- 2026-03-10: The dynamic reload slice uncovered a subtle correctness boundary around workspace
  roots. Recording concrete workspace paths on running entries avoided a regression where runtime
  snapshots or cleanup would drift to a newly configured root before the original worker finished.
- 2026-03-10: Replaced the generic execution roadmap with a repository-state-aware ExecPlan. The
  immediate outcome is clarity: the next deliverable is no longer “more M2 work” in the abstract;
  it is a streamed agent runner that can terminate success, failure, timeout, and stall cases and
  feed a single-issue harness. The remaining gap is implementation, not planning.
- 2026-03-10: Tightened the reload slice after review. Symphony now reacts to `WORKFLOW.md`
  changes on a dedicated watch loop instead of only at tick boundaries, and long-running attempts
  still pick up the latest `after_run` hook settings without forcing a session restart.
- 2026-03-10: Closed the lifecycle edge cases around the watcher path. The repository now has
  focused regressions for listener removal, shutdown fencing, and reuse of one `WorkflowRuntime`
  across multiple orchestrator lifecycles, plus best-effort cleanup for stale retry workspaces
  after a workspace-root reload.
- 2026-03-10: Completed the planned critical path. The repository now has a normalized streamed
  agent runner, a single-issue worker harness, and a working orchestrator core with retry and
  reconciliation tests. Remaining work is no longer foundational execution plumbing; it is follow-on
  product and operational surface area.
- 2026-03-10: Added the first operator-visible runtime snapshot/export path. The backend can now
  serialize orchestrator state into a JSON-friendly summary and expose it at `GET /api/v1/state`,
  while preserving `GET /healthz`. The remaining gap for observability is cross-process delivery if
  the orchestrator and Django server do not share a process.
- 2026-03-10: Closed the first observability gap by having the orchestrator publish runtime
  snapshots to a small shared JSON file that Django can read across process boundaries. The API now
  returns spec-style error envelopes and explicit `405` responses on unsupported methods, while
  preserving the existing health check.
- 2026-03-10: Hardened the first observability surface so file I/O failures now degrade only the
  shared snapshot bridge rather than the orchestrator itself. Same-process `/api/v1/state` reads
  continue to work from the live provider, and file writes now use unique temp paths to avoid
  writer collisions before the final atomic replace.
- 2026-03-10: Tightened the module boundary after review. The runtime snapshot bridge now lives in
  the observability layer, and the HTTP endpoint no longer republishes snapshots during a read.
- 2026-03-10: Tightened the first observability surface after a second review pass. Snapshot reads
  now reject stale files, default snapshot files no longer collide across local orchestrator
  processes, distinct turns are counted deterministically, and snapshot publication no longer holds
  the orchestrator's async state lock across filesystem I/O.
- 2026-03-10: Extended the HTTP observability surface from aggregate-only state to issue-scoped
  debugging. Operators can now fetch one active issue by identifier from the same runtime snapshot
  source without moving orchestration logic into Django views, while unknown issues return a
  spec-style `404` error envelope.
- 2026-03-10: Hardened the issue-scoped snapshot path after review. Runtime snapshot refreshes no
  longer fail when tracker identifiers are too degenerate for `WorkspaceManager` sanitization; the
  observability surface now falls back to a best-effort workspace path in the same way the worker
  harness already does.
- 2026-03-10: Added the first operational control hook to the optional HTTP surface. `POST
  /api/v1/refresh` now queues a best-effort poll+reconcile trigger through a small shared file, and
  the orchestrator consumes that trigger between normal poll intervals without moving scheduling
  logic into Django.
- 2026-03-10: Completed the first optional HTTP server slice around the existing observability
  bridge. `run_orchestrator` now supports `--port` plus workflow `server.port`, starts a loopback
  WSGI sidecar when configured, and serves a human-readable dashboard at `/` without adding a
  second scheduler or moving orchestrator state into Django request handlers.
- 2026-03-10: Closed the HTTP slice with a full review/fix loop and final quality-gate proof. The
  read-only dashboard and JSON observability routes now preserve spec-style `405` behavior under
  the default CSRF middleware stack, the HTTP server lifecycle has dedicated unit coverage, and the
  repository passes `make lint`, `make typecheck`, and `make test`.

## Context and Orientation

The relevant backend code lives under `apps/api/symphony/`. The repository already has working
modules for workflow loading (`workflow/loader.py`), typed config and defaults
(`workflow/config.py`), Linear normalization (`tracker/linear.py`), Linear API transport and
queries (`tracker/linear_client.py`), workspace directory safety (`workspace/manager.py`), and
prompt construction (`agent_runner/prompting.py`). The repository now also has a working
orchestrator, a file-backed runtime snapshot bridge, issue-scoped/refresh HTTP endpoints, and an
optional loopback HTTP sidecar that `apps/api/symphony/management/commands/run_orchestrator.py`
can start when `--port` or workflow `server.port` is configured.

In this plan, “app-server” means the Codex subprocess launched with `bash -lc <codex.command>` in
the workspace directory. Its stdout carries one JSON protocol message per line. Its stderr is
diagnostic text only and must never be parsed as protocol. A “turn” means one `turn/start`
request followed by the streamed protocol messages that end in a terminal outcome such as
`turn/completed`, `turn/failed`, or `turn/cancelled`. A “stall” means the subprocess stays alive
but emits no relevant protocol activity for longer than `codex.stall_timeout_ms`.

The app-server client surface lives in `apps/api/symphony/agent_runner/client.py` and
`apps/api/symphony/agent_runner/runner.py`. It now covers startup handshake, streamed turn
processing, malformed stdout handling, approval/user-input/tool-call policy behavior, and
deterministic timeout/stall termination with focused unit coverage under
`apps/api/tests/unit/agent_runner/`.

The orchestrator package is no longer a placeholder. `apps/api/symphony/orchestrator/core.py`
owns dispatch, retries, reconciliation, runtime snapshot publication, and refresh-trigger
consumption. Remaining work in this area is follow-on product and operational surface area rather
than foundational protocol plumbing.

## Plan of Work

### Milestone 1: Extend the app-server client from handshake-only to streamed turn processing

The first milestone is to make one turn observable from `turn/start` until terminal outcome. Keep
`apps/api/symphony/agent_runner/client.py` as the subprocess/protocol module, but expand it beyond
the handshake. Add a reusable stdout reader that returns decoded JSON objects one complete line at a
time, keeps stderr separate, and surfaces malformed JSON as typed protocol errors without crashing
the surrounding process cleanup.

Introduce a small event model in a new module `apps/api/symphony/agent_runner/events.py`. This
module should define plain dataclasses for normalized runtime events and terminal turn results. The
names should be boring and explicit. A novice should be able to read the type names and understand
what they carry without opening the spec. At minimum, define a runtime event type carrying the
event name, UTC timestamp, `session_id`, `thread_id`, `turn_id`, the app-server PID if available,
an optional usage snapshot, and a small payload map for event-specific fields. Also define a turn
termination object that records whether the turn completed successfully, failed, was cancelled,
timed out, or ended because input was required.

Update `apps/api/symphony/agent_runner/client.py` so that after `start_app_server_session(...)`
returns, a caller can invoke a streaming function such as `stream_turn(...)` or `run_turn_stream(...)`
against the same `AppServerSession`. That function must read stdout until it sees a terminal turn
message, process interleaved notifications, and keep enough structured information to emit
normalized runtime events. Do not make the caller parse raw Codex JSON payloads. The caller should
receive normalized events and one terminal result.

Expand `apps/api/tests/unit/agent_runner/test_client.py` with a richer fake app-server transcript.
Add tests for at least: interleaved notifications before terminal completion, `turn/completed`,
`turn/failed`, `turn/cancelled`, malformed JSON lines, subprocess exit before terminal message, and
usage payload extraction when the fake server includes token totals.

The result of this milestone is observable: the unit tests should prove that a session can survive
the startup handshake and then produce a normalized terminal outcome from a streamed turn.

### Milestone 2: Add timeout, inactivity, and policy handling to the streamed runner

Once one streamed turn works, add the time-based behavior required by `docs/SPEC.md`. Keep the
deadline math out of the lowest-level JSON decoder. The low-level parser should know only how to
read one line and decode one message. The higher-level streamed runner should own the monotonic
clock, the overall turn deadline, and the inactivity deadline.

In a new module `apps/api/symphony/agent_runner/runner.py`, define the worker-facing abstraction
that consumes `AppServerSession` plus turn configuration and emits normalized runtime events through
an async callback. This module should enforce:

1. `codex.read_timeout_ms` for synchronous request/response operations.
2. `codex.turn_timeout_ms` for total elapsed time from `turn/start` until terminal result.
3. `codex.stall_timeout_ms` for inactivity since the last protocol activity or policy action.

This module should also implement the policy behaviors required to prevent turns from hanging:
auto-approve approval requests when the configured policy says to auto-approve, fail the turn
immediately on user-input-required signals, and return a structured failure result for unsupported
dynamic tool calls so the session can continue instead of stalling. Keep the policy implementation
simple and explicit; do not introduce a general plugin system here.

Add focused tests under `apps/api/tests/unit/agent_runner/`. The fake app-server should be able to
simulate a silent stall, a never-ending turn, a user-input-required request, an approval request,
and an unsupported tool call. The new tests should assert both the terminal result and the emitted
normalized events. The important outcome is determinism: a turn that would otherwise hang must now
produce a predictable failure category.

The result of this milestone is observable: the unit suite can prove all end states required for a
single turn without relying on orchestrator code.

### Milestone 3: Build the single-issue worker harness around the streamed runner

After the streamed runner semantics are stable, add the worker harness in
`apps/api/symphony/agent_runner/` or a closely related backend module. This harness is the missing
proof that Symphony can execute one issue attempt end-to-end outside the poll loop. It should own:
workspace creation or reuse via `apps/api/symphony/workspace/manager.py`, hook execution, prompt
construction, app-server session startup, continuation-turn logic up to `agent.max_turns`, and
final cleanup/return values.

Implement hook execution before and after the run using the timeout already defined in
`hooks.timeout_ms`. Fatal hook behavior must match the spec: `after_create` and `before_run`
failures abort the current attempt; `after_run` and `before_remove` failures are logged and
ignored. The harness must use the full rendered prompt on the first turn and
`build_continuation_guidance(...)` on subsequent turns within the same thread.

Create a direct harness test path. This can be a dedicated test helper or a small management
command used only for manual proof, but it must be runnable from the repository root without the
orchestrator loop. The harness tests should prove success, retry-worthy failure, timeout, stall,
and multi-turn continuation behavior with one persistent `thread_id`.

The result of this milestone is observable: one issue can be run end-to-end against a fake
app-server without involving tracker polling or concurrency control.

### Milestone 4: Implement orchestrator core on top of the harness and normalized runner events

Only after Milestones 1 through 3 are complete should work move into
`apps/api/symphony/orchestrator/`. Create a plain-Python state model for running issues, claimed
issues, retry entries, and live session metadata. Keep this state machine framework-light so the
Django management command remains a thin host.

The orchestrator core should use the existing Linear client and config layer to fetch eligible
issues, claim them, dispatch worker harness tasks, and reconcile active runs against tracker state.
Normal worker exit should schedule the short continuation retry described in the spec. Abnormal exit
should schedule exponential backoff up to `agent.max_retry_backoff_ms`. Terminal issue state changes
should stop running work and eventually clean the corresponding workspace.

Testing here should focus on deterministic state transitions rather than protocol details. Create
unit tests for candidate selection, claim release, retry scheduling, stall-driven termination, and
reconciliation when an issue leaves the active states. The orchestrator tests must treat the worker
harness as an injected dependency that emits normalized events, not as a place to re-test raw
Codex JSON protocol handling.

The result of this milestone is observable: `uv run --project apps/api python apps/api/manage.py
run_orchestrator` can continuously poll, dispatch eligible issues within concurrency limits, and
recover from failures using the already-proven worker harness behavior.

## Concrete Steps

Work from the repository root: `/Users/mike/projs/main/symphony`.

1. Re-run the current backend baseline before editing anything:

       uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/tracker apps/api/tests/unit/workspace apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_client.py

   Expected result now:

       ============================== 75 passed in 1.64s ==============================

2. Implement Milestone 1 in `apps/api/symphony/agent_runner/client.py`,
   `apps/api/symphony/agent_runner/events.py`, and the matching tests. Then run:

       uv run pytest apps/api/tests/unit/agent_runner -q

   Expect the suite to include new streaming tests and pass without needing the orchestrator.

3. Implement Milestone 2 in `apps/api/symphony/agent_runner/runner.py` and add the timeout,
   inactivity, approval, and unsupported-tool tests. Then run:

       uv run pytest apps/api/tests/unit/agent_runner -q

   Expect explicit passing cases for `turn_timeout`, stall failure, approval handling, and
   user-input-required failure.

4. Implement Milestone 3 and add a focused single-issue harness test suite. Then run:

       uv run pytest apps/api/tests/unit/agent_runner -q

   Expect harness tests to prove workspace creation, hook semantics, continuation turns, and clean
   subprocess shutdown.

5. Implement Milestone 4 and the management-command integration path. Then run the project quality
   gates:

       make lint
       make typecheck
       make test

   If the repository is not ready for the full `make` targets yet, record the failing command and
   the reason in `Progress`, then keep the narrower targeted suites green while finishing the
   missing setup.

Completed verification transcript:

       uv run ruff check apps/api
       uv run mypy apps/api
       uv run pytest

## Validation and Acceptance

The implementation described by this plan is acceptable only when the following behaviors are
observable.

For the streamed agent runner:

- A fake app-server can emit interleaved notifications and then `turn/completed`, and the runner
  produces normalized runtime events followed by a successful terminal result.
- A fake app-server can emit `turn/failed` or `turn/cancelled`, and the runner maps those to
  deterministic failure categories without leaving the subprocess hanging.
- A fake app-server can stop emitting protocol activity, and the worker-facing runner ends the turn
  with the configured stall failure once `codex.stall_timeout_ms` elapses.
- A fake app-server can keep streaming non-terminal noise forever, and the runner ends the turn
  with the configured `turn_timeout` once `codex.turn_timeout_ms` elapses.
- Approval requests, unsupported tool calls, and user-input-required signals no longer stall the
  session indefinitely.

For the worker harness:

- One issue can execute from workspace acquisition through final result without the poll loop.
- Continuation turns reuse the original `thread_id` and stop when `agent.max_turns` is reached or a
  terminal run result is produced.
- Hook failure semantics match the spec and are proven by tests.

For the orchestrator core:

- The management command can dispatch eligible issues, track active work, and schedule retries
  without reparsing Codex protocol messages.
- Reconciliation stops work when an issue becomes terminal or otherwise ineligible.

The final proof command remains:

    make lint
    make typecheck
    make test

The plan is not complete until these checks pass or any residual blockers are explicitly documented
in `Progress` with their exact failing command and reason.

## Idempotence and Recovery

The planned steps are intentionally additive. Re-running the targeted pytest commands is safe and
should not mutate repository state. The fake app-server tests should always create their own
temporary files under `tmp_path`, so they can be repeated without cleanup.

When editing the agent runner, always preserve process cleanup on failure. Any new streaming or
watchdog code must terminate or kill the subprocess if it exits abnormally or if a timeout fires.
This protects repeated local test runs from accumulating orphaned app-server processes. If a new
test flakes because a subprocess remains alive, treat that as a correctness bug in the harness or
runner rather than as “just a test issue.”

If work on Milestones 3 or 4 reveals that the event model from Milestones 1 or 2 is missing
fields, revise `apps/api/symphony/agent_runner/events.py` and update this ExecPlan in the same
change. Do not bypass the normalized event model by letting higher layers inspect raw protocol
payloads directly.

## Artifacts and Notes

Current proof that the repository foundation exists:

    $ uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/tracker apps/api/tests/unit/workspace apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_client.py
    ============================== 75 passed in 1.64s ==============================

Current proof that the orchestrator is still only a startup shell:

    Superseded on 2026-03-10 01:53Z. The management command now instantiates `Orchestrator` and can
    either run one tick with `--once` or enter the long-running loop by default.

Current proof of the handshake-only boundary:

    Superseded on 2026-03-10 01:53Z. The agent runner now streams turn events through
    `apps/api/symphony/agent_runner/runner.py`, and the harness/orchestrator consume normalized
    runtime events instead of stopping after the startup handshake.

Current proof that the optional HTTP surface is wired end-to-end:

    $ make lint
    $ make typecheck
    $ make test
    backend: ============================= 160 passed in 11.49s =============================
    frontend: vitest exited 0 with --passWithNoTests

## Interfaces and Dependencies

The implementation should stay within the existing backend stack: Python 3.12, `asyncio`, Django
management commands as the host entrypoint, and plain dataclasses for the protocol/runtime models.
Do not introduce Celery, Redis, or a separate job framework for this work.

Create the following interfaces as part of Milestones 1 and 2.

In `apps/api/symphony/agent_runner/events.py`, define:

    @dataclass(slots=True, frozen=True)
    class UsageSnapshot:
        input_tokens: int
        output_tokens: int
        total_tokens: int

    @dataclass(slots=True, frozen=True)
    class AgentRuntimeEvent:
        event: str
        timestamp: datetime
        session_id: str
        thread_id: str
        turn_id: str
        codex_app_server_pid: int | None
        usage: UsageSnapshot | None
        payload: Mapping[str, Any]

    @dataclass(slots=True, frozen=True)
    class TurnResult:
        outcome: str
        error_code: str | None
        message: str | None
        usage: UsageSnapshot | None

In `apps/api/symphony/agent_runner/client.py`, keep and extend:

    async def start_app_server_session(...) -> AppServerSession

    async def start_next_turn(
        session: AppServerSession,
        *,
        prompt_text: str,
        title: str,
        approval_policy: str,
        sandbox_policy: Mapping[str, Any],
        read_timeout_ms: int,
    ) -> str:
        ...

    async def read_protocol_message(
        session: AppServerSession,
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        ...

The exact helper names can change if the final implementation is clearer, but the boundary must
remain: `client.py` owns subprocess I/O and JSON message decoding.

In `apps/api/symphony/agent_runner/runner.py`, define:

    async def stream_turn(
        session: AppServerSession,
        *,
        turn_timeout_ms: int,
        stall_timeout_ms: int,
        on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None = None,
    ) -> TurnResult:
        ...

This function is the worker-facing abstraction that Milestone 3 and Milestone 4 should consume.
The worker harness may wrap it, but higher layers must not reimplement raw Codex protocol parsing.

In the future worker harness module, define a single top-level async entrypoint that accepts the
normalized `Issue`, the typed `ServiceConfig`, and a callback for runtime events, and returns a
typed attempt result that the orchestrator can use for retry decisions. Keep the name explicit, for
example `run_issue_attempt(...)`.

Revision note (2026-03-10 00:53Z): rewrote this file from a generic milestone roadmap into a
repository-state-aware living ExecPlan. Reason: the codebase already has workflow/tracker/workspace
foundations and a handshake-only agent runner, so the immediate need is an executable critical-path
plan for streamed turns, timeout/stall handling, the single-issue worker harness, and the
orchestrator core that depends on them.

Revision note (2026-03-10 01:53Z): updated this file after implementation. Reason: the critical
path is now complete, so the plan needed to record the shipped modules, final validation commands,
and the remaining boundary between foundational execution plumbing and later operational work.

Revision note (2026-03-10 06:49Z): updated this file for the dynamic `WORKFLOW.md` reload slice.
Reason: the next required conformance gap after the orchestrator/HTTP foundation was runtime
workflow re-apply, including invalid reload fallback, future-dispatch gating, and workspace-root-
safe cleanup for already-running sessions.
