# Close Remaining `SPEC_GAPS` Conformance and Recovery Extensions

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

Symphony already runs issues end to end, but the remaining gaps in `docs/SPEC_GAPS.md` still leave operators blind in several failure paths and leave restart behavior weaker than the specification intends. Today a tracker refresh can fail quietly, best-effort hooks can fail without any operator-visible record, app-server `stderr` stays buffered in memory instead of becoming diagnostics, temporary workspace artifacts are left behind, prompt template failures are not classified precisely enough, and restart loses retry/session state.

When this plan is complete, an operator will be able to start the orchestrator, see stable `key=value` logs for issue, session, hook, tracker, and recovery events, confirm that temporary workspace clutter is removed before each run, observe exact prompt parse versus render failures in tests and logs, verify that token totals stay correct across repeated agent updates, and restart the process without dropping retry queue state or the last known session metadata. The proof is behavioral: focused unit tests pass, the full quality gates pass, and manual smoke runs emit the expected structured logs and recovery behavior.

## Progress

- [x] 2026-03-10 08:22Z: Audited `docs/SPEC_GAPS.md` against `docs/SPEC.md`, `docs/ROADMAP.md`, and the current backend implementation to identify the concrete modules and tests affected by every remaining gap.
- [x] 2026-03-10 08:22Z: Replaced the placeholder `docs/EXEC_PLAN.md` with a repository-specific execution plan that covers all currently listed `SPEC_GAPS` items in milestone order.
- [x] 2026-03-10 09:32Z: Implemented Milestone 1: added repository-owned structured logging, surfaced tracker and startup failures, emitted hook lifecycle/failure logs with issue context, and forwarded app-server `stderr` diagnostics into operator-visible logs without affecting worker liveness semantics.
- [x] 2026-03-10 09:32Z: Verified Milestone 1 with focused backend tests: `uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/agent_runner/test_client.py apps/api/tests/unit/workspace/test_hooks.py apps/api/tests/unit/management/test_run_orchestrator.py -q` -> `69 passed in 11.61s`.
- [x] 2026-03-10 09:32Z: Ran repository quality gates after Milestone 1: `make lint` passed, `make typecheck` passed, and `make test` passed (`189 passed in 15.08s` for backend pytest; frontend Vitest exited `0` with `--passWithNoTests`).
- [x] 2026-03-10 09:53Z: Implemented Milestone 2: added per-attempt workspace temp-artifact cleanup, split prompt parse versus render failures with operator-visible logging, and tightened token accounting to accept only event-defined absolute totals while ignoring delta-only updates.
- [x] 2026-03-10 10:16Z: Completed the Milestone 2 review/fix loop: prompt rendering now fails before workspace hooks run, workspace resolution versus preparation failures log distinct events, usage fallthrough semantics are documented and covered, and prompt rendering reuses a shared Jinja environment.
- [x] 2026-03-10 10:16Z: Verified Milestone 2 with focused backend tests: `uv run pytest apps/api/tests/unit/agent_runner/test_events.py apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/workspace/test_manager.py apps/api/tests/unit/orchestrator/test_core.py -q` -> `77 passed in 9.55s`.
- [x] 2026-03-10 10:05Z: Re-ran repository quality gates after Milestone 2: `make lint` passed, `make typecheck` passed, and `make test` passed (`200 passed in 15.74s` for backend pytest; frontend Vitest exited `0` with `--passWithNoTests`).
- [x] 2026-03-10 11:04Z: Implemented Milestone 3: added workflow-configurable observability paths, file-backed restart recovery persistence for running/retry state, recovery-driven retry reconstruction with preserved prior session metadata, and focused backend coverage for the restart recovery paths and workflow-configured observability reload behavior.
- [x] 2026-03-10 11:04Z: Completed the Milestone 3 review/fix loop: recovery persistence now imports and builds retry rows correctly, focused recovery tests write to the effective workflow-configured recovery path, and the ExecPlan records the actual validation result for this milestone.
- [x] 2026-03-10 11:04Z: Verified Milestone 3 with focused backend tests: `uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/management/test_run_orchestrator.py -q` -> `71 passed in 4.20s`.
- [x] 2026-03-10 11:15Z: Closed a follow-up Milestone 3 recovery race from the review loop: worker exit no longer publishes an empty recovery snapshot between removing a running row and scheduling its retry, and the new regression test `uv run pytest apps/api/tests/unit/orchestrator/test_core.py -q -k worker_exit_persists_retry_without_empty_recovery_gap -vv` passed (`1 passed, 37 deselected in 0.04s`).
- [x] 2026-03-10 11:46Z: Re-ran repository quality gates after Milestone 3 and the follow-up test-snapshot fixes: `make lint` passed, `make typecheck` passed, and `make test` passed (`211 passed in 15.70s` for backend pytest; frontend Vitest exited `0` with `--passWithNoTests`).

## Surprises & Discoveries

- Observation: `apps/api/symphony/workspace/hooks.py` currently implements `run_hook_best_effort(...)` by swallowing every `HookError` and returning `None`, so `after_run` and `before_remove` failures satisfy the “ignored” half of the contract but miss the required logging entirely.
  Evidence: `run_hook_best_effort(...)` catches `HookError` and drops it without calling any logger or callback.

- Observation: `apps/api/symphony/agent_runner/client.py` already collects non-JSON `stderr` lines in `AppServerSession.stderr_lines`, but nothing consumes that buffer for operator diagnostics.
  Evidence: `AppServerSession` has a `stderr_lines` field and `_drain_stderr(...)` appends to it, yet no downstream path logs those lines.

- Observation: temporary workspace cleanup is not a missing branch inside `WorkspaceManager.ensure_workspace(...)`; it is missing entirely from the per-attempt preparation path.
  Evidence: `apps/api/symphony/agent_runner/harness.py` goes directly from `ensure_workspace(...)` and optional `after_create` into `before_run` without a prep-cleanup pass.

- Observation: token extraction is currently more permissive than the spec allows, because `apps/api/symphony/agent_runner/events.py` accepts generic `usage` maps without distinguishing absolute totals from delta payloads.
  Evidence: `extract_usage_snapshot(...)` inspects top-level, `params`, `result`, and nested `usage` maps indiscriminately, while `docs/SPEC.md` Section 13.5 requires event-type-aware preference for absolute totals and explicit rejection of delta-only payloads such as `last_token_usage`.

## Decision Log

- Decision: Use one active ExecPlan to close every gap currently listed in `docs/SPEC_GAPS.md`, but execute the work in two layers: core conformance first, recommended extensions second.
  Rationale: The current audit is small enough to keep in one self-contained plan, and the extension work depends on the logging and state-shaping improvements from the core tranche.
  Date/Author: 2026-03-10 / Codex

- Decision: Add a repository-owned structured logging helper under `apps/api/symphony/observability/` instead of hand-formatting `logger.warning(...)` strings at each call site.
  Rationale: The spec requires stable `key=value` formatting and repeated issue/session context fields. A helper avoids drift and lets the orchestrator, harness, hook code, and management command all emit the same shape.
  Date/Author: 2026-03-10 / Codex

- Decision: Implement restart recovery as a file-backed JSON snapshot of orchestrator state, not as a database or as a best-effort reinterpretation of the runtime snapshot file.
  Rationale: `docs/SPEC.md` explicitly wants restart recovery without requiring a database. A dedicated recovery file can store durable wall-clock retry metadata and prior session summaries without coupling recovery semantics to the freshness rules of the dashboard snapshot.
  Date/Author: 2026-03-10 / Codex

- Decision: Keep the first workflow-configurable observability extension minimal and path-oriented by adding an `observability` front-matter section for snapshot, refresh-request, and recovery-state file locations plus snapshot freshness age.
  Rationale: These settings already exist as operational concepts in `apps/api/symphony/observability/runtime.py`, they help the recovery work immediately, and they do not prescribe any UI behavior.
  Date/Author: 2026-03-10 / Codex

## Outcomes & Retrospective

Milestones 1, 2, and 3 are complete. The implementation now emits stable `key=value` logs for startup validation, tracker fetch/refresh failures, retry scheduling, worker exit paths, workspace hook lifecycle/failures, startup terminal cleanup, app-server `stderr` diagnostics, prompt template failures, workspace preparation failures, and recovery-load failures. The worker prep path now removes `tmp` and `.elixir_ls` before each attempt, prompt template syntax versus render failures are distinguishable in both tests and logs, session token accounting only accepts event-defined absolute totals while ignoring delta-only telemetry, and restart recovery persists retry/running state with prior session metadata while letting workflow front matter choose future snapshot, refresh-request, and recovery file paths.

Validation so far:

- Focused Milestone 1 suite passed: `uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/agent_runner/test_client.py apps/api/tests/unit/workspace/test_hooks.py apps/api/tests/unit/management/test_run_orchestrator.py -q` -> `69 passed in 11.61s`.
- Focused Milestone 2 suite passed after the review/fix loop: `uv run pytest apps/api/tests/unit/agent_runner/test_events.py apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/workspace/test_manager.py apps/api/tests/unit/orchestrator/test_core.py -q` -> `77 passed in 9.55s`.
- Focused Milestone 3 suite passed after the review/fix loop: `uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/management/test_run_orchestrator.py -q` -> `71 passed in 4.20s`.
- Follow-up Milestone 3 recovery regression passed: `uv run pytest apps/api/tests/unit/orchestrator/test_core.py -q -k worker_exit_persists_retry_without_empty_recovery_gap -vv` -> `1 passed, 37 deselected in 0.04s`.
- Repository gates passed after Milestone 2: `make lint`, `make typecheck`, and `make test`.
- `make test` details after Milestone 2: backend `pytest` -> `200 passed in 15.74s`; frontend `vitest run --passWithNoTests` exited `0`.
- Repository gates passed after Milestone 3: `make lint`, `make typecheck`, and `make test`.
- `make test` details after Milestone 3: backend `pytest` -> `211 passed in 15.70s`; frontend `vitest run --passWithNoTests` exited `0`.

The plan is now closed at the repository quality-gate level. Remaining follow-up work, if any, belongs in a new ExecPlan or in `docs/SPEC_GAPS.md`, not as unfinished Milestone 3 carryover.

Success for the remaining plan still means `docs/SPEC_GAPS.md` can be updated so every current item is either removed or marked fixed, the backend test surface proves each behavior explicitly, and operators can verify the new behavior from logs and persisted runtime state without attaching a debugger. If later implementation reveals a gap that deserves its own follow-on project, capture it here and in `docs/SPEC_GAPS.md` rather than letting it disappear into code comments.

## Context and Orientation

The current implementation spine already exists. `apps/api/symphony/orchestrator/core.py` owns the poll loop, runtime state, retry queue, worker dispatch, reconciliation, and runtime snapshot building. `apps/api/symphony/agent_runner/harness.py` performs one issue attempt: it ensures the workspace exists, runs workspace hooks, renders the workflow prompt, launches the Codex app-server, streams turns, refreshes issue state, and returns an `AttemptResult`. `apps/api/symphony/agent_runner/client.py` is the low-level stdio protocol client that performs the handshake and buffers `stderr`. `apps/api/symphony/agent_runner/events.py` normalizes usage telemetry. `apps/api/symphony/workspace/manager.py` owns safe workspace paths and deletion. `apps/api/symphony/workspace/hooks.py` runs hook shell scripts. `apps/api/symphony/workflow/config.py` provides typed front-matter config. `apps/api/symphony/observability/runtime.py` already persists the read-only runtime snapshot and the refresh trigger file used by the optional HTTP surface.

In this repository, a “structured log” means a normal log line whose message is stable `key=value` text and whose fields are deterministic enough to assert in tests. An “operator-visible failure” means a failure that appears in a standard logger output path without a debugger attached. A “best-effort hook” is `after_run` or `before_remove`: failure must not fail the enclosing orchestration action, but it must still be logged. “Restart recovery” means the next process instance can reconstruct retry scheduling and prior session metadata from files written by the previous process, even though it cannot resume a dead subprocess.

The tests that already cover the touched areas live in `apps/api/tests/unit/orchestrator/test_core.py`, `apps/api/tests/unit/agent_runner/test_harness.py`, `apps/api/tests/unit/agent_runner/test_client.py`, `apps/api/tests/unit/agent_runner/test_events.py`, `apps/api/tests/unit/agent_runner/test_prompting.py`, `apps/api/tests/unit/workspace/test_manager.py`, `apps/api/tests/unit/workspace/test_hooks.py`, `apps/api/tests/unit/workflow/test_config.py`, and `apps/api/tests/unit/management/test_run_orchestrator.py`. Extend those tests instead of creating a second parallel test layout.

## Plan of Work

### Milestone 1: Make failures operator-visible and logs spec-shaped

At the end of this milestone, Symphony will no longer silently swallow the gaps called out in the highest-severity audit items. Tracker candidate-fetch failures, running-state refresh failures, startup terminal-cleanup failures, `after_run` failures, `before_remove` failures, and app-server `stderr` diagnostics will all reach a normal logger. The emitted messages will be stable `key=value` strings and will include `issue_id`, `issue_identifier`, and `session_id` whenever those values exist for the event.

Start by adding `apps/api/symphony/observability/logging.py`. This module should expose a tiny helper that takes an event name, a log level, and a mapping of fields, drops `None` values, stringifies JSON-safe scalars, truncates long diagnostics, and emits one stable `key=value` message through the standard Python logging stack. Keep this helper intentionally small; it is a formatting boundary, not a second state system. Use it from `apps/api/symphony/management/commands/run_orchestrator.py` for startup validation and HTTP-server bind failures, and from `apps/api/symphony/orchestrator/core.py` for the tracker and dispatch paths identified in `docs/SPEC_GAPS.md`: `tick(...)`, `reconcile_running_issues(...)`, `_startup_terminal_workspace_cleanup(...)`, `_handle_worker_event(...)`, `_handle_worker_exit(...)`, `_schedule_retry(...)`, and workflow-reload failure handling.

Do not push issue-aware hook logging down into `apps/api/symphony/workspace/hooks.py`, because that file does not know which issue or session it belongs to. Instead, keep `run_hook(...)` as the low-level shell runner and make the higher-level callers in `apps/api/symphony/agent_runner/harness.py` and `apps/api/symphony/orchestrator/core.py` wrap hook execution with explicit `hook_started`, `hook_failed`, and `hook_timed_out` logs that include the issue identifier, issue id, workspace path, and session id when available. Fatal hooks (`after_create`, `before_run`) should still abort the attempt. Best-effort hooks (`after_run`, `before_remove`) should still be ignored after logging.

For app-server diagnostics, extend `apps/api/symphony/agent_runner/client.py` so `_drain_stderr(...)` can emit each decoded `stderr` line through a callback or queue instead of only appending to `AppServerSession.stderr_lines`. Carry those diagnostics into `apps/api/symphony/agent_runner/harness.py` as `AgentRuntimeEvent` records such as `stderr_diagnostic`, and let the orchestrator log them with session and issue context in `_handle_worker_event(...)`. Preserve the in-memory `stderr_lines` buffer for tests and snapshots, but make logging the first-class behavior.

The tests for this milestone belong in `apps/api/tests/unit/orchestrator/test_core.py`, `apps/api/tests/unit/agent_runner/test_harness.py`, `apps/api/tests/unit/agent_runner/test_client.py`, `apps/api/tests/unit/workspace/test_hooks.py`, and `apps/api/tests/unit/management/test_run_orchestrator.py`. Add assertions against captured log output rather than only return values. The acceptance bar is that every currently silent path in `docs/SPEC_GAPS.md` becomes observable, and the log lines use the exact context fields required by `docs/SPEC.md` Sections 13.1, 13.2, and 17.6.

### Milestone 2: Match the remaining core runtime semantics exactly

At the end of this milestone, the remaining non-restart core conformance gaps will be closed: the per-attempt workspace prep path removes temporary artifacts before the agent runs, prompt template parse versus render failures are distinguishable, and token aggregation only counts absolute totals once.

Implement workspace prep cleanup in `apps/api/symphony/workspace/manager.py` as a method that removes only repository-local temporary artifacts required by the spec right now: `tmp` and `.elixir_ls` directly under the per-issue workspace root. This method must validate that the target path still sits under the workspace root before deleting anything and must be idempotent so it can run before every attempt. Call it from `apps/api/symphony/agent_runner/harness.py` immediately after `ensure_workspace(...)` and before `before_run`. If cleanup fails because a path cannot be removed, surface a `WorkspaceError` so the attempt fails explicitly rather than proceeding with a half-prepared workspace.

Split prompt failures in `apps/api/symphony/agent_runner/prompting.py` into two subclasses: one for syntax/assertion failures while compiling the template and one for runtime failures while rendering with `issue` and `attempt`. Preserve `PromptTemplateError` as the common base so existing callers can continue to treat all template problems as fatal, but give the subclasses exact `code` values of `template_parse_error` and `template_render_error`. The tests in `apps/api/tests/unit/agent_runner/test_prompting.py` must assert both codes and the conditions that trigger them.

Harden token accounting across `apps/api/symphony/agent_runner/events.py` and `apps/api/symphony/orchestrator/core.py`. The current extractor is too permissive. Change it so it prefers absolute totals from event types that actually promise absolute totals, such as `thread/tokenUsage/updated` payloads and wrapper payloads that expose `total_token_usage`. Ignore delta-only payloads such as `last_token_usage`, and do not let a generic `usage` object update orchestrator totals unless the event type defines it as cumulative. The easiest implementation is to make usage extraction event-aware and let the orchestrator update aggregate totals only when the extracted snapshot declares itself absolute. Preserve the existing “last reported totals” fields on `RunningEntry`, but make the tests prove that repeated identical totals do not double-count and that lower-quality delta payloads are ignored. Extend `apps/api/tests/unit/agent_runner/test_events.py` and `apps/api/tests/unit/orchestrator/test_core.py` for this.

This milestone also needs new log assertions where prompt errors and workspace cleanup failures are surfaced, because the spec requires those failures to be operator-visible, not just typed internally.

### Milestone 3: Persist retry/session state and make observability paths configurable

At the end of this milestone, Symphony will survive a process restart without forgetting when retries were due or what the previous session metadata looked like, and the file paths used by the runtime snapshot, refresh request, and recovery state will be configurable from `WORKFLOW.md`.

Begin by extending `apps/api/symphony/workflow/config.py` with a new `ObservabilityConfig` dataclass and a corresponding `observability` section on `ServiceConfig`. The first version should support `snapshot_path`, `refresh_request_path`, `recovery_path`, and `snapshot_max_age_seconds`. Keep environment variables as overrides for tests and emergency host-level control, but let workflow config provide the normal repository-owned defaults. Wire the chosen values into `apps/api/symphony/observability/runtime.py` through explicit setters or a lightweight runtime config object; do not leave this as a pile of unrelated globals. The orchestrator’s workflow reload path in `apps/api/symphony/orchestrator/core.py` must re-apply updated observability settings for future writes.

Add a new recovery module, preferably `apps/api/symphony/orchestrator/recovery.py`, that serializes the minimal durable state needed for restart recovery. Persist retry rows with issue id, identifier, retry attempt, workspace path, wall-clock `due_at`, and last error. Persist running rows with issue id, identifier, current attempt, workspace path, `started_at`, and the session metadata that already lives on `RunningEntry` (`session_id`, `thread_id`, `turn_id`, token totals, last event, last event timestamp, app-server pid, and turn count). Write this recovery file whenever the orchestrator refreshes its runtime snapshot or materially changes retry/running state. Use the same “write temp file then replace atomically” pattern already used in `apps/api/symphony/observability/runtime.py`.

On startup, load the recovery file before the first steady-state poll. Corrupt or unreadable recovery data must not crash the service; log a warning and continue without recovery. For persisted retry entries, compute the remaining delay from the stored wall-clock `due_at` and recreate retry timers immediately, clamping overdue entries to `0 ms`. For persisted running entries, do not pretend the old subprocess is still alive. Convert each one into a retry entry with an explicit restart error such as `orchestrator_restarted`, preserve the prior session metadata so it remains visible in the runtime snapshot until the next run begins, and schedule the retry immediately. This fulfills the “persist retry queue and session metadata” requirement without inventing unsupported session resumption.

Update `apps/api/symphony/orchestrator/core.py` and the snapshot-building path so retry rows can include prior session metadata when they originated from recovery. Extend the optional issue-level snapshot in `apps/api/symphony/observability/runtime.py` to expose that metadata if present. Add focused coverage in `apps/api/tests/unit/orchestrator/test_core.py`, `apps/api/tests/unit/workflow/test_config.py`, and `apps/api/tests/unit/management/test_run_orchestrator.py` for successful recovery, overdue retry recovery, recovered running-entry conversion, corrupted recovery-file fallback, and workflow-configured path application.

## Concrete Steps

Work from the repository root, `/Users/mike/projs/main/symphony`.

Before editing, run the focused baseline suites so any new failures are attributable to this work:

    uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/agent_runner/test_client.py apps/api/tests/unit/agent_runner/test_events.py apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/workspace/test_manager.py apps/api/tests/unit/workspace/test_hooks.py apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/management/test_run_orchestrator.py -q

Expect pytest to finish with `0 failed`.

After Milestone 1 edits, run:

    uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/agent_runner/test_client.py apps/api/tests/unit/workspace/test_hooks.py apps/api/tests/unit/management/test_run_orchestrator.py -q

Expect the suite to pass and captured log assertions to prove that tracker failures, hook failures, and `stderr` diagnostics are emitted.

After Milestone 2 edits, run:

    uv run pytest apps/api/tests/unit/agent_runner/test_events.py apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/workspace/test_manager.py apps/api/tests/unit/orchestrator/test_core.py -q

Expect the suite to pass and to include explicit cases for `template_parse_error`, `template_render_error`, temp-artifact cleanup, and repeated absolute token totals without double-counting.

After Milestone 3 edits, run:

    uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/management/test_run_orchestrator.py -q

Expect the suite to pass and to include restart recovery reconstruction plus corrupted recovery-file fallback.

Once all focused suites pass, run the repository gates:

    make format
    make lint
    make typecheck
    make test

Success means every command exits `0`. Record the exact passing summaries in `Progress` and `Outcomes & Retrospective`.

## Validation and Acceptance

Acceptance is behavioral, not just structural.

- When tracker candidate fetch, running-state refresh, or startup terminal cleanup fails in tests, the orchestrator must continue following the spec’s fallback behavior and must emit an operator-visible structured log line describing the failure.
- When `after_run` or `before_remove` fails or times out, the enclosing attempt or cleanup must still continue, but captured logs must include `hook=<name>`, `issue_id`, `issue_identifier`, and the failure reason.
- When the fake app-server writes plain text to `stderr`, parsing must continue normally and a structured diagnostic log line must be emitted for each captured line.
- When a workspace contains `tmp` or `.elixir_ls`, the next attempt must remove those artifacts before `before_run` executes, and removal must be safe to repeat.
- When a prompt template has invalid syntax, callers must receive `template_parse_error`; when the template compiles but references an unknown variable or filter, callers must receive `template_render_error`.
- When the same absolute token totals arrive multiple times, aggregate totals must remain stable; when delta-only payloads arrive, aggregate totals must not change.
- When the process restarts with persisted retry entries, those retries must be re-created with the correct remaining delay; when it restarts with persisted running entries, they must be converted into retry entries with preserved prior session metadata and an explicit restart reason.
- When observability paths are supplied in workflow front matter, the runtime snapshot, refresh request, and recovery state files must use those paths for future writes without requiring ad hoc environment variable setup.

## Idempotence and Recovery

Every step in this plan should be safe to rerun. The logging helper is additive. Workspace prep cleanup must only target `tmp` and `.elixir_ls` inside validated per-issue workspace roots, so repeated cleanup is a no-op after the first successful run. Recovery-file writes must be atomic replacements, not in-place mutations, so an interrupted write leaves either the old complete file or the new complete file. Recovery-file reads must treat missing files as “no recovery available” and malformed files as a logged warning plus an empty recovery state.

Do not use destructive repository resets while implementing this plan. For tests that need workspace deletion or recovery-file cleanup, operate inside pytest temporary directories and use the existing `WorkspaceManager` and observability helper paths rather than deleting arbitrary host paths. If a new recovery schema changes during implementation, write a compatibility note in this document and make the loader either accept both shapes during the transition or explicitly log-and-drop the obsolete file.

## Artifacts and Notes

Target log lines should look like this shape, with field order kept stable by the helper:

    event=hook_failed hook=after_run issue_id=lin_123 issue_identifier=ABC-123 session_id=thread-1-turn-2 error_code=hook_execution message="Hook 'after_run' failed with exit code 1."

    event=tracker_candidate_fetch_failed error_code=linear_api_request message="Linear request timed out"

    event=app_server_stderr issue_id=lin_123 issue_identifier=ABC-123 session_id=thread-1-turn-2 line="warning: tool schema mismatch"

The recovery file should be compact JSON whose important shape is easy to inspect manually:

    {
      "running": [
        {
          "issue_id": "lin_123",
          "issue_identifier": "ABC-123",
          "attempt": null,
          "workspace_path": "/tmp/.../ABC-123",
          "started_at": "2026-03-10T08:00:00Z",
          "session": {
            "session_id": "thread-1-turn-2",
            "thread_id": "thread-1",
            "turn_id": "turn-2",
            "turn_count": 2,
            "last_event": "turn_completed",
            "last_event_at": "2026-03-10T08:03:00Z",
            "tokens": {"input": 100, "output": 40, "total": 140}
          }
        }
      ],
      "retrying": [
        {
          "issue_id": "lin_124",
          "issue_identifier": "ABC-124",
          "attempt": 2,
          "due_at": "2026-03-10T08:05:00Z",
          "workspace_path": "/tmp/.../ABC-124",
          "error": "retry poll failed"
        }
      ]
    }

## Interfaces and Dependencies

In `apps/api/symphony/observability/logging.py`, define a helper with a stable interface equivalent to:

    def log_event(
        logger: logging.Logger,
        level: int,
        event: str,
        *,
        fields: Mapping[str, object | None],
    ) -> None:
            ...

This helper must never raise because of `None`, non-string scalars, or overlong diagnostic text.

In `apps/api/symphony/workflow/config.py`, define:

    @dataclass(slots=True, frozen=True)
    class ObservabilityConfig:
        snapshot_path: Path | None
        refresh_request_path: Path | None
        recovery_path: Path | None
        snapshot_max_age_seconds: int

Add `observability: ObservabilityConfig` to `ServiceConfig`, parse it from workflow front matter, and keep environment variables as overrides.

In `apps/api/symphony/workspace/manager.py`, define a method equivalent to:

    def remove_temporary_artifacts(self, workspace_path: Path) -> tuple[str, ...]:
            ...

Return the names removed so tests can assert behavior; return an empty tuple when nothing needed removal.

In `apps/api/symphony/agent_runner/prompting.py`, define:

    class PromptTemplateParseError(PromptTemplateError): ...
    class PromptTemplateRenderError(PromptTemplateError): ...

Keep `PromptTemplateError` as the shared base type used by callers.

In `apps/api/symphony/agent_runner/events.py`, extend usage extraction so the orchestrator can distinguish absolute totals from non-cumulative telemetry. One acceptable interface is:

    @dataclass(slots=True, frozen=True)
    class UsageSnapshot:
        input_tokens: int
        output_tokens: int
        total_tokens: int
        is_absolute_total: bool

    def extract_usage_snapshot(
        message: Mapping[str, Any],
        *,
        event_name: str | None = None,
    ) -> UsageSnapshot | None:
            ...

In `apps/api/symphony/orchestrator/recovery.py`, define file-backed recovery helpers equivalent to:

    @dataclass(slots=True, frozen=True)
    class PersistedSessionMetadata: ...

    @dataclass(slots=True, frozen=True)
    class RecoveryState: ...

    def load_recovery_state(path: Path) -> RecoveryState: ...
    def publish_recovery_state(path: Path, state: RecoveryState) -> Path: ...

`apps/api/symphony/orchestrator/core.py` should remain the single owner of live runtime state. The recovery module is only a serializer/deserializer and must not grow orchestration policy.

Revision Note: 2026-03-10 / Codex. Replaced the placeholder active plan with a full ExecPlan driven by `docs/SPEC_GAPS.md`, so the next contributor can implement the remaining spec gaps and recommended extensions without reconstructing context from the audit and roadmap documents.
