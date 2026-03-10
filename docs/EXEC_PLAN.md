# Deliver the 2026-03-10 Roadmap Workstreams

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

`docs/ROADMAP.md` is the repository-level statement of the major work still needed after Symphony’s core execution path landed. The repository can already poll Linear, create workspaces, run the coding agent, reconcile state, publish runtime snapshots, emit structured logs, recover retry/session state across restarts, apply workflow-owned observability settings, serve a real Angular dashboard, and expose a backend-owned tracker write surface.

When this plan is complete, an operator will be able to start the orchestrator, observe stable `key=value` lifecycle logs for dispatch and recovery, restart the process without losing retry timing and session summaries, open an Angular dashboard that consumes the existing `/api/v1/*` runtime endpoints, inspect issue and retry details there, and optionally use backend-owned tracker write endpoints instead of depending only on agent tools for comments or transitions. The proof is behavioral: focused tests pass at each milestone, repository-wide quality gates pass, the docs are updated to match reality, and a human can manually exercise the runtime and UI surfaces without reading the source first.

## Progress

- [x] 2026-03-10 12:14Z: Audited `docs/ROADMAP.md`, `docs/SPEC.md`, `docs/SPEC_GAPS.md`, `.agent/PLANS.md`, the archived ExecPlan in `docs/archive/EXEC_PLAN_SPEC_GAPS_CONFORMANCE_2026-03-10.md`, and the current backend/frontend entrypoints to identify the concrete modules each roadmap workstream touches.
- [x] 2026-03-10 12:14Z: Replaced the placeholder `docs/EXEC_PLAN.md` with a repository-specific ExecPlan that turns the roadmap workstreams into sequenced milestones with commands, acceptance criteria, and file-level orientation.
- [x] 2026-03-10 13:48Z: Re-audited Milestone 1 against `docs/SPEC.md` Sections 13, 17, and 18 plus the current backend code and tests. The runtime already emits structured `key=value` logs for tracker fetch failures, running-state refresh failures, startup cleanup, hook start/failure/timeout, retry scheduling, worker exit, workflow reload failures, and app-server `stderr` diagnostics, so no Milestone 1 backend code changes were required.
- [x] 2026-03-10 14:02Z: Ran the Milestone 1 baseline backend suite from this ExecPlan and observed `155 passed in 13.56s`.
- [x] 2026-03-10 14:18Z: Ran the Milestone 1 focused backend suite serially and observed `109 passed in 12.14s`.
- [x] 2026-03-10 14:23Z: Marked Milestone 1 complete by updating `docs/SPEC_GAPS.md`, `docs/ROADMAP.md`, and this ExecPlan to match the implemented observability baseline and recorded the validation evidence here.
- [x] 2026-03-10 14:44Z: Re-audited Milestone 2 against the current backend code and tests, confirmed that workspace temp-artifact cleanup, prompt parse-versus-render taxonomy, and token accounting hardening were already implemented, and re-ran the Milestone 2 focused suite with `87 passed in 9.48s`.
- [x] 2026-03-10 14:46Z: Re-audited Milestone 3 against the current backend code and tests, confirmed that restart recovery persistence and corrupt-recovery fallback behavior were already implemented, and re-ran the Milestone 3 focused suite with `98 passed in 4.22s`.
- [x] 2026-03-10 14:47Z: Re-audited Milestone 4 against the current backend code and tests, confirmed that workflow-configurable observability settings and reload application behavior were already implemented, and re-ran the Milestone 4 focused suite with `98 passed in 4.22s`.
- [x] 2026-03-10 14:51Z: Updated `docs/SPEC_GAPS.md`, `docs/ROADMAP.md`, and this ExecPlan so milestones 1-4 reflect the actual implemented baseline, leaving only Milestones 5 and 6 as open roadmap work.
- [x] 2026-03-10 12:54Z: Replaced the Angular placeholder bootstrap with a routed standalone app shell, added dashboard/issue/runs feature pages, introduced a shared runtime API/presenter layer, and wired the dev server to proxy `/api/*` traffic to Django during local development.
- [x] 2026-03-10 12:55Z: Ran the Milestone 5 frontend validation commands in `apps/web` and observed `pnpm lint` -> pass, `pnpm typecheck` -> pass, and `pnpm test` -> `1 passed (4 tests)` during the initial implementation pass.
- [x] 2026-03-10 13:08Z: Re-ran the Milestone 5 frontend validation commands during the review/fix loop and observed `pnpm lint` -> pass, `pnpm typecheck` -> pass, `pnpm test` -> `1 passed (5 tests)`, and `pnpm build` -> pass with output written to `apps/web/dist/web`.
- [!] 2026-03-10 13:10Z: Re-ran the repository-wide quality gates after the review fixes using `UV_CACHE_DIR=.uv-cache` because the default `uv` cache path is not writable in this execution environment. `make lint` -> pass and `make typecheck` -> pass. `make test` reached `214 passed, 1 failed`; the remaining failure is `apps/api/tests/unit/api/test_server.py::test_start_runtime_http_server_serves_wsgi_requests_and_closes_cleanly`, which cannot bind a loopback socket in this execution environment (`PermissionError: [Errno 1] Operation not permitted`).
- [x] 2026-03-10 12:58Z: Completed a manual frontend smoke during the initial implementation pass using a temporary runtime snapshot, Django on `127.0.0.1:8000`, Angular dev-server on `127.0.0.1:4200`, and `playwright-cli`. Verified the dashboard count/totals route, issue detail for `SYM-123`, stale-state handling when `/runs` encountered an aged snapshot, fresh `/runs` retry data after renewing the snapshot timestamps, and a proxied `POST /api/v1/refresh` that returned `202 Accepted`, created the refresh-request file, and reloaded the dashboard state.
- [x] 2026-03-10 12:58Z: Marked Milestone 5 complete by updating `docs/ROADMAP.md` and this ExecPlan to match the delivered Angular runtime pages, leaving Milestone 6 as the only remaining roadmap work.
- [x] 2026-03-10 13:43Z: Implemented Milestone 6 with a Symphony-owned tracker mutation contract and service layer under `apps/api/symphony/tracker/`, added Linear-backed comment/state-transition/pull-request attachment support, exposed delegating `POST` endpoints under `apps/api/symphony/api/`, and added focused tracker/API tests for success paths, normalized failures, structured logs, redundant transitions, and repeated pull-request attachment requests.
- [x] 2026-03-10 22:31Z: Completed the Milestone 6 serial review/fix loop. The final focused tracker-write suite passed with `45 passed in 0.06s`, the final repository-wide quality gates passed with `make lint` -> pass, `make typecheck` -> pass, and `make test` -> pass (`240` backend tests plus `5` frontend tests), and the last clean review reported no remaining findings.

## Surprises & Discoveries

- Observation: the roadmap describes the Angular frontend as “feature placeholders,” but the current application entrypoint is even earlier than that. `apps/web/src/main.ts` bootstraps a single inline standalone component and there is no real router, route tree, or runtime data service yet.
  Evidence: `apps/web/src/main.ts` contains the only frontend component and renders a static “Operator Dashboard Skeleton” card.

- Observation: the repository already contains `apps/api/symphony/observability/logging.py` and `apps/api/symphony/orchestrator/recovery.py`, which means parts of the roadmap’s backend work are not greenfield. Each backend milestone must begin with a brief re-audit against `docs/SPEC.md`, `docs/SPEC_GAPS.md`, and the current code before editing, otherwise the implementation risks duplicating or partially replacing existing behavior.
  Evidence: `apps/api/symphony/orchestrator/core.py` imports both modules today.

- Observation: `docs/ROADMAP.md` is broader than `docs/SPEC_GAPS.md`. Some workstreams are core conformance gaps, some are recommended extensions from `docs/SPEC.md`, and some are product delivery items with no direct spec conformance requirement.
  Evidence: the roadmap explicitly groups work into `Core Conformance Workstreams`, `Recommended Extension Workstreams`, and `Product and UI Workstreams`.

- Observation: Milestone 1 code had already landed before this closeout, but the living docs still described the observability layer as largely unimplemented.
  Evidence: the Milestone 1 focused suite already passes with assertions for `event=tracker_candidate_fetch_failed`, `event=tracker_running_state_refresh_failed`, `event=workflow_reload_failed`, `event=hook_started`, `event=hook_failed`, `event=hook_timed_out`, `event=retry_scheduled`, `event=worker_exit`, and `event=app_server_stderr`.

- Observation: the same documentation drift extended beyond Milestone 1. Current code and focused pytest suites show that Milestones 2, 3, and 4 had already landed as well.
  Evidence: `apps/api/symphony/workspace/manager.py` already implements `remove_temporary_artifacts(...)`; `apps/api/symphony/agent_runner/prompting.py` already exposes `PromptTemplateParseError` and `PromptTemplateRenderError`; `apps/api/symphony/orchestrator/core.py` and `apps/api/symphony/orchestrator/recovery.py` already persist and restore recovery state; `apps/api/symphony/workflow/config.py` already defines `ObservabilityConfig`; and the re-run focused suites for Milestones 2-4 all passed on 2026-03-10.

## Decision Log

- Decision: Use one active ExecPlan derived from `docs/ROADMAP.md` to sequence the remaining repository work in priority order, even though individual milestones may later be split into narrower follow-on ExecPlans if review scope or implementation complexity demands it.
  Rationale: the user requested a plan for the tasks described in the roadmap, and the repository currently has no active plan. A single umbrella ExecPlan gives the next contributor a complete map from roadmap to codebase while still allowing later milestone-specific refinement.
  Date/Author: 2026-03-10 / Codex

- Decision: Preserve the roadmap priority order for milestone sequencing: structured logging first, workspace/runtime polish second, restart recovery third, configurable observability fourth, Angular frontend fifth, and tracker write APIs last.
  Rationale: that order matches `docs/ROADMAP.md`, keeps core conformance ahead of extensions, and avoids building the primary UI or a public write API before the backend runtime, logging, and recovery story are stable.
  Date/Author: 2026-03-10 / Codex

- Decision: Require every milestone to finish with documentation synchronization in addition to code and tests.
  Rationale: the repository already contains evidence that docs and code can drift on the same day. A milestone is not complete until `docs/SPEC_GAPS.md`, `docs/ROADMAP.md`, and this ExecPlan describe the actual resulting state.
  Date/Author: 2026-03-10 / Codex

- Decision: Treat the Milestone 1 closeout as a documentation-and-validation update rather than force additional backend changes.
  Rationale: the current implementation and focused pytest coverage already satisfy the observability scope described for Milestone 1. Writing redundant code here would increase risk without adding missing behavior.
  Date/Author: 2026-03-10 / Codex

- Decision: Treat Milestones 2, 3, and 4 the same way after re-audit and focused validation, and collapse the remaining roadmap backlog to Milestones 5 and 6.
  Rationale: the current repository already contains the workspace polish, restart recovery, and workflow-configurable observability behaviors those milestones describe. Leaving them marked open would misstate the codebase and create stale follow-up work.
  Date/Author: 2026-03-10 / Codex

## Outcomes & Retrospective

Milestones 1 through 6 are now recorded as complete. The repository already met the first four backend roadmap goals before this closeout, Milestone 5 adds a real Angular operator surface with routed dashboard, issue detail, and runs pages backed by the existing Django runtime APIs, and Milestone 6 now adds a backend-owned tracker mutation contract plus HTTP endpoints for comments, state transitions, and pull-request metadata attachment. This closeout re-ran the milestone-focused validation commands, synchronized the living docs with the observed behavior, and cleared the remaining roadmap item that previously left tracker writes agent-tool-driven only.

No roadmap workstreams remain open in this ExecPlan after the Milestone 6 implementation pass.

## Context and Orientation

This repository is split into a Django backend under `apps/api` and an Angular frontend under `apps/web`. The backend runtime already exists. `apps/api/symphony/orchestrator/core.py` is the central state machine: it owns polling, dispatch, retries, reconciliation, runtime snapshots, and restart recovery hooks. `apps/api/symphony/agent_runner/harness.py`, `apps/api/symphony/agent_runner/client.py`, `apps/api/symphony/agent_runner/events.py`, and `apps/api/symphony/agent_runner/prompting.py` together manage one issue attempt, app-server session streaming, token accounting, and prompt rendering. `apps/api/symphony/workspace/manager.py` and `apps/api/symphony/workspace/hooks.py` manage per-issue workspaces and lifecycle hooks. `apps/api/symphony/workflow/config.py` and `apps/api/symphony/workflow/loader.py` turn `WORKFLOW.md` into typed runtime settings. `apps/api/symphony/observability/runtime.py`, `apps/api/symphony/observability/snapshots.py`, and `apps/api/symphony/observability/logging.py` own runtime snapshot files and structured logging helpers. `apps/api/symphony/api/views.py` now exposes the operator-facing HTTP surfaces for runtime reads and refreshes plus tracker write endpoints for comments, transitions, and pull-request attachment metadata.

The frontend is much less complete. `apps/web/src/main.ts` bootstraps a single static standalone component. The intended feature roots exist only as README placeholders under `apps/web/src/app/features/dashboard`, `apps/web/src/app/features/issues`, and `apps/web/src/app/features/runs`. Shared UI and helper areas also exist only as README stubs under `apps/web/src/app/shared`. The design system foundation is already present through Tailwind and tokenized styles, so the frontend work should add real standalone components, routes, and data services rather than invent a second styling stack.

For this plan, a “structured log” means a stable `key=value` log line emitted through the normal Python logging stack and carrying event-specific context such as `issue_id`, `issue_identifier`, `session_id`, hook name, error code, or retry metadata. A “recovery file” means a JSON file written atomically to disk so a new orchestrator process can rebuild retry timing and the last known live-session summary without pretending a dead subprocess is still alive. A “first-class tracker write API” means a Symphony-owned backend interface, exposed through Python services and optionally HTTP endpoints, that performs tracker comments, transitions, or pull-request metadata writes with normalized success and error semantics instead of relying only on whatever tools the coding agent happens to use in a prompt.

The existing tests relevant to this plan already live in the repository and should be extended instead of duplicated. Backend runtime tests are concentrated in `apps/api/tests/unit/orchestrator/test_core.py`, `apps/api/tests/unit/agent_runner/test_harness.py`, `apps/api/tests/unit/agent_runner/test_client.py`, `apps/api/tests/unit/agent_runner/test_events.py`, `apps/api/tests/unit/agent_runner/test_prompting.py`, `apps/api/tests/unit/workspace/test_manager.py`, `apps/api/tests/unit/workspace/test_hooks.py`, `apps/api/tests/unit/workflow/test_config.py`, `apps/api/tests/unit/management/test_run_orchestrator.py`, `apps/api/tests/unit/api/test_server.py`, and `apps/api/tests/unit/api/test_state.py`. Frontend validation will need to extend the Angular source tree and may introduce Vitest coverage for services and pure components once those files exist.

## Plan of Work

### Milestone 1: Finish structured logging and observability maturity

Status: completed on 2026-03-10. The prose below remains as the execution record for what this milestone required.

At the end of this milestone, every operator-significant dispatch, retry, reconciliation, workflow-reload, hook, startup, and app-server diagnostic path described in `docs/ROADMAP.md` will emit stable operator-visible structured logs. This is the first milestone because the rest of the roadmap depends on being able to see what the system is doing and why it failed.

Begin by re-auditing the current logging and observability paths against `docs/SPEC.md` Sections 13, 17, and 18, the open items in `docs/SPEC_GAPS.md`, and the reality of `apps/api/symphony/orchestrator/core.py`, `apps/api/symphony/agent_runner/harness.py`, `apps/api/symphony/agent_runner/client.py`, `apps/api/symphony/workspace/hooks.py`, and `apps/api/symphony/management/commands/run_orchestrator.py`. The repository already has `apps/api/symphony/observability/logging.py`; extend and standardize that helper instead of introducing a second logging format. Confirm that the key lifecycle events called out in the roadmap really emit `key=value` lines with stable field order and enough context for operators to correlate issue, session, hook, retry, and startup failures.

Then close the remaining observability gaps in the runtime code. The orchestrator should log silent tracker fetch and refresh failures, startup terminal-cleanup failures, retry scheduling decisions, worker exits, cancellation reasons, and workflow reload failures. The hook layer should log hook start, completion, timeout, and failure while preserving the spec’s “best effort” behavior for hooks that should not crash the outer action. The app-server client should surface buffered `stderr` lines as diagnostic logs without changing session liveness semantics. Token accounting should become precise enough that later dashboard work can trust the totals it renders. If the spec gap audit is now stale because the code already closes some of these items, update the docs during the milestone instead of carrying stale backlog language forward.

The milestone is complete only when the focused backend tests assert log output, the runtime snapshot still behaves as before, and `docs/SPEC_GAPS.md` and `docs/ROADMAP.md` clearly show which observability items are closed and which remain.

### Milestone 2: Close workspace and runtime polish gaps

Status: completed on 2026-03-10. The prose below remains as the execution record for what this milestone required.

At the end of this milestone, the smaller remaining core-runtime mismatches from the roadmap will be closed so the backend behavior matches the spec surface more exactly rather than only “in spirit.” This work is intentionally grouped because these gaps are small but easy to lose if they are scattered across unrelated feature work.

Start in `apps/api/symphony/workspace/manager.py` and `apps/api/symphony/agent_runner/harness.py`. Ensure every attempt performs a safe pre-run cleanup of repository-local temporary artifacts such as `tmp` and `.elixir_ls` directly inside the per-issue workspace before hooks or the agent run. The cleanup must prove the target still sits under the intended workspace root before removing anything, and repeated attempts must be safe. Failures in this preparation step should be typed and operator-visible, not silently ignored.

Then refine prompt rendering in `apps/api/symphony/agent_runner/prompting.py` so parse failures and render failures are distinguishable. The plan requires separate error classes and separate error codes, because the operator response is different when the template is invalid versus when the input data cannot satisfy a valid template. Tighten token accounting in `apps/api/symphony/agent_runner/events.py` and the orchestrator so repeated absolute totals do not double-count and lower-quality delta payloads do not pollute the runtime aggregates. When this milestone ends, the smaller core items tracked in `docs/SPEC_GAPS.md` should be closed or explicitly reworded if the implementation uncovered a narrower remaining issue.

### Milestone 3: Complete restart recovery and state persistence

Status: completed on 2026-03-10. The prose below remains as the execution record for what this milestone required.

At the end of this milestone, restarting the Symphony process will no longer drop retry timing and live-session summary state. This is the largest recommended extension in the roadmap and the one with the clearest operator value after core conformance work is finished.

Treat `apps/api/symphony/orchestrator/core.py` as the owner of live policy and `apps/api/symphony/orchestrator/recovery.py` as a pure serializer/deserializer. Persist the minimal durable runtime state needed to recover the retry queue and last known session metadata: retry attempt number, due time, workspace path, last error, and the summary of the session fields already tracked on `RunningEntry`. Use atomic write-then-replace semantics, the same style already used for runtime snapshot files, so a crash cannot leave a half-written recovery file.

On startup, load the recovery file before the first steady-state poll. Missing recovery state should mean “nothing to restore.” Corrupt recovery state must produce a warning log and then continue with a clean in-memory state. Persisted retry entries should restore their timers using wall-clock due times. Persisted running entries must not be treated as resumed processes; convert them into retry entries with an explicit restart error and preserve the last session summary so operators can still see what had been running. End this milestone by updating the recovery-related docs and by proving the behavior with focused restart tests, including overdue retries and corrupt recovery files.

### Milestone 4: Add workflow-configurable observability settings

Status: completed on 2026-03-10. The prose below remains as the execution record for what this milestone required.

At the end of this milestone, observability settings that matter to operators will be configurable from `WORKFLOW.md` front matter while still allowing environment variable overrides where needed for tests or host-level control. This work comes after recovery because the recovery and snapshot files are the first settings that obviously benefit from a typed configuration surface.

Implement a typed `observability` section in `apps/api/symphony/workflow/config.py` and thread it through the backend without falling back to implicit globals scattered across the codebase. The first supported settings should cover snapshot path, refresh-request path, recovery path, snapshot freshness, and any logging verbosity or sink settings that can be expressed without redesigning the whole runtime. Apply the settings through explicit configuration plumbing in `apps/api/symphony/observability/runtime.py` and the orchestrator’s workflow reload path so a workflow reload updates future writes predictably.

This milestone also closes the loop on documentation hygiene. `WORKFLOW.md` configuration examples, `docs/ROADMAP.md`, and any lingering “environment variable only” wording in the code comments or docs must be updated so the repository has one coherent story about where observability behavior is configured.

### Milestone 5: Build the Angular runtime pages

Status: completed on 2026-03-10. The prose below remains as the execution record for what this milestone required.

At the end of this milestone, the operator-facing web experience will no longer be the server-rendered fallback alone. The Angular app will have real routes, real data fetching, and clear runtime state handling while still consuming the existing backend APIs rather than duplicating orchestrator logic in the browser.

Begin by turning the current single-component bootstrap in `apps/web/src/main.ts` into a conventional Angular standalone application with a route tree. Create an app shell and route definitions under `apps/web/src/app`, then implement feature slices under `apps/web/src/app/features/dashboard`, `apps/web/src/app/features/issues`, and `apps/web/src/app/features/runs`. Add a small shared API layer under `apps/web/src/app/shared` that reads `/api/v1/state`, `/api/v1/refresh`, and `/api/v1/<issue_identifier>`, normalizes the response shapes used by the UI, and keeps the Angular app as a consumer of backend state only.

The dashboard route should show aggregate counts, workflow status, runtime totals, and active issue rows. The issue detail route should show issue-specific runtime details and the last session summary. The runs route should show retry queue and active-run information derived from existing API responses. Each route must handle loading, empty, unavailable, and stale-state scenarios deliberately. Preserve the design-token approach already set up in `apps/web/src/styles/tokens.css` and `apps/web/src/styles/globals.css`, and keep the server-rendered Django dashboard as a fallback until the Angular UI is production-ready. Finish by adding frontend lint, typecheck, build, and test coverage for the new shared services and any pure transformation logic introduced.

### Milestone 6: Add first-class tracker write APIs

Status: completed on 2026-03-10. The prose below remains as the execution record for what this milestone required.

At the end of this milestone, Symphony will expose an explicit backend-owned write surface for tracker mutations that currently depend on agent tools alone. This milestone is deliberately last, because it should build on a stable observability story, clear runtime state, and an operator UI that can eventually consume or trigger those writes.

Keep the orchestrator boundary intact. Do not move tracker business logic into Django request handlers or Angular state. Instead, extend the tracker integration layer under `apps/api/symphony/tracker/` with a clear write contract for comments, state transitions, and pull-request metadata attachment, then decide whether to expose that contract through management commands, Python service entrypoints, HTTP endpoints under `apps/api/symphony/api/`, or a combination. The important point is that Symphony owns the write semantics and error normalization rather than leaving them implicit in prompts.

Define explicit request and response shapes, normalize tracker-side failures into stable error codes, and log the mutations with the same structured logging layer built earlier in this plan. If any write endpoint becomes user-facing during this milestone, add acceptance coverage that proves the mutation path is idempotent where appropriate, rejects invalid state transitions safely, and emits operator-visible logs. Finish by documenting what still remains agent-tool-driven and what is now backed by Symphony itself.

## Concrete Steps

Work from the repository root, `/Users/mike/projs/main/symphony`, unless a step explicitly says otherwise.

Before starting Milestone 1, run the current backend-focused baseline so new failures can be attributed to the roadmap work:

    uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/agent_runner/test_client.py apps/api/tests/unit/agent_runner/test_events.py apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/workspace/test_manager.py apps/api/tests/unit/workspace/test_hooks.py apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/management/test_run_orchestrator.py apps/api/tests/unit/api/test_state.py apps/api/tests/unit/api/test_server.py -q

Expect the suite to exit with `0 failed`. Record the exact passing summary in `Progress` once it is run.

After Milestone 1 edits, run:

    uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/agent_runner/test_client.py apps/api/tests/unit/workspace/test_hooks.py apps/api/tests/unit/management/test_run_orchestrator.py apps/api/tests/unit/api/test_state.py -q

Expect focused assertions proving that tracker, hook, startup, retry, and app-server diagnostic failures are logged in a stable operator-visible format.

After Milestone 2 edits, run:

    uv run pytest apps/api/tests/unit/agent_runner/test_events.py apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_harness.py apps/api/tests/unit/workspace/test_manager.py apps/api/tests/unit/orchestrator/test_core.py -q

Expect explicit cases for temporary-artifact cleanup, parse-versus-render prompt failures, and token-total aggregation without double counting.

After Milestone 3 edits, run:

    uv run pytest apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/management/test_run_orchestrator.py apps/api/tests/unit/api/test_state.py -q

Expect restart-recovery reconstruction, overdue retry restoration, corrupt recovery-file fallback, and persisted session-summary assertions.

After Milestone 4 edits, run:

    uv run pytest apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/management/test_run_orchestrator.py apps/api/tests/unit/api/test_state.py -q

Expect configuration parsing, workflow reload, and runtime file-path application coverage for observability settings.

After Milestone 5 edits, change to `apps/web` and run:

    pnpm lint
    pnpm typecheck
    pnpm test
    pnpm build

Then, from the repository root, run:

    make lint
    make typecheck
    make test

Expect the Angular app to build cleanly, frontend checks to pass, and the repository-wide gates to remain green. Record both command summaries and a short manual smoke transcript in `Progress`.

For the manual frontend smoke after Milestone 5, run the backend and frontend in separate terminals:

    make dev-api
    make dev-web

Open the Angular app in a browser and verify that the dashboard route loads runtime counts, the issue detail route loads an existing issue snapshot, the runs route shows retry data, and the refresh action issues a `POST` to `/api/v1/refresh` and updates the displayed state. If the Angular app proxies API traffic through a dev-server configuration introduced during the milestone, document that configuration in `Artifacts and Notes`.

After Milestone 6 edits, run the focused tracker-write backend tests that are added during implementation, followed by:

    make lint
    make typecheck
    make test

Expect the new write path to have explicit success and failure tests, structured logs for each mutation category, and no regression in the existing runtime behavior.

## Validation and Acceptance

Acceptance is behavioral and must be demonstrable without reading the implementation.

- After Milestone 1, a failed tracker fetch, failed running-state refresh, failed startup cleanup, hook timeout, hook failure, workflow reload failure, or app-server `stderr` diagnostic produces an operator-visible structured log line with the appropriate issue and session context when available.
- After Milestone 2, a workspace containing `tmp` or `.elixir_ls` is cleaned before the next run, prompt compilation failures report a different error code than prompt render failures, and repeated absolute token totals do not inflate the runtime snapshot.
- After Milestone 3, restarting the orchestrator preserves retry timing and last known session summaries through the recovery file, while corrupted recovery state produces a warning and a safe empty recovery instead of a crash.
- After Milestone 4, `WORKFLOW.md` can define the effective snapshot, refresh-request, and recovery file paths, and a workflow reload changes future writes without requiring a process restart.
- After Milestone 5, a human can open the Angular UI and use real routes to inspect the runtime dashboard, an issue detail view, and retry/run state backed by `/api/v1/state`, `/api/v1/<issue_identifier>`, and `/api/v1/refresh`. The server-rendered dashboard still works as a fallback.
- After Milestone 6, a Symphony-owned mutation path can add a tracker comment, perform a state transition, or attach pull-request metadata with normalized error handling and structured audit logs, and invalid or redundant mutations are handled safely.

The full plan is complete only when repository-wide `make lint`, `make typecheck`, and `make test` pass after the final milestone, and the roadmap and gap docs accurately describe the implemented state.

## Idempotence and Recovery

Every milestone in this plan must be safe to run more than once. Logging changes are additive and should not require destructive migration. Workspace cleanup must remove only known temporary artifacts inside validated per-issue workspace roots, which makes repeated cleanup a no-op once the directory is clean. Recovery-file and runtime-snapshot writes must continue to use atomic replace semantics so an interrupted write never leaves a partial JSON file behind. Workflow-configured observability settings must be applied through typed config and reload-safe plumbing instead of hidden global mutation.

The Angular work should be introduced incrementally so the existing Django dashboard remains a fallback until the frontend routes are ready. Tracker write APIs must begin behind explicit server-side contracts and tests; do not make destructive tracker mutations part of startup or implicit background behavior. If a milestone uncovers a schema or interface change that cannot remain backward compatible during implementation, update this ExecPlan with the safe retry and rollback story before merging the code.

## Artifacts and Notes

Representative structured log lines should follow this shape:

    event=tracker_candidate_fetch_failed error_code=linear_api_request message="Linear request timed out"

    event=hook_failed hook=after_run issue_id=lin_123 issue_identifier=SYM-123 session_id=thread-1-turn-2 error_code=hook_execution message="Hook 'after_run' failed with exit code 1."

    event=app_server_stderr issue_id=lin_123 issue_identifier=SYM-123 session_id=thread-1-turn-2 line="warning: tool schema mismatch"

Representative recovery-file content should stay compact and inspectable:

    {
      "running": [
        {
          "issue_id": "lin_123",
          "issue_identifier": "SYM-123",
          "attempt": null,
          "workspace_path": "/tmp/.../SYM-123",
          "started_at": "2026-03-10T08:00:00Z",
          "session": {
            "session_id": "thread-1-turn-2",
            "thread_id": "thread-1",
            "turn_id": "turn-2",
            "turn_count": 2,
            "last_event": "turn_completed",
            "last_event_at": "2026-03-10T08:03:00Z",
            "tokens": {
              "input": 100,
              "output": 40,
              "total": 140
            }
          }
        }
      ],
      "retrying": [
        {
          "issue_id": "lin_124",
          "issue_identifier": "SYM-124",
          "attempt": 2,
          "due_at": "2026-03-10T08:05:00Z",
          "workspace_path": "/tmp/.../SYM-124",
          "error": "orchestrator_restarted"
        }
      ]
    }

The Angular route tree introduced in Milestone 5 should end up conceptually like this:

    /              -> dashboard overview
    /issues/:id    -> issue runtime detail
    /runs          -> active runs and retry queue

If a later milestone needs to add more routes or tracker-mutation controls, document them here as they are introduced rather than leaving them implicit in the source tree.

For local frontend development after Milestone 5, `apps/web/proxy.conf.json` proxies `/api/*` requests from Angular dev-server to `http://127.0.0.1:8000`, which keeps the browser app same-origin from the developer’s perspective while preserving Django as the owner of the runtime API surface.

## Interfaces and Dependencies

`docs/SPEC.md` remains the normative behavior contract. `docs/ROADMAP.md` is the prioritization source for this plan. `docs/SPEC_GAPS.md` is the authoritative gap audit that must be updated as milestones close.

The backend should keep using Python 3.12, Django, `ruff`, `mypy`, and pytest as described in `AGENTS.md`. The frontend should keep using Angular standalone components, strict TypeScript, Tailwind, ESLint, Prettier, and Vitest.

Revision note (2026-03-10 / Codex): Updated the ExecPlan after a broader re-audit showed that Milestones 1 through 4 were already implemented. Recorded the re-run focused pytest results for Milestones 2-4, marked those milestones complete, and synchronized the living-document sections to match the actual codebase state.

For Milestones 1 through 4, keep `apps/api/symphony/orchestrator/core.py` as the single owner of live runtime state and policy decisions. `apps/api/symphony/observability/logging.py` should remain the sole formatting boundary for structured backend logs. `apps/api/symphony/orchestrator/recovery.py` should remain a serializer/deserializer module rather than becoming a second orchestrator. `apps/api/symphony/workflow/config.py` should remain the typed home for workflow-derived settings, including any new observability configuration.

For Milestone 5, introduce explicit Angular application structure under `apps/web/src/app` rather than continuing to inline the app in `apps/web/src/main.ts`. At minimum, create a route definition module and standalone feature entrypoints for dashboard, issue detail, and runs. Shared HTTP access should live in `apps/web/src/app/shared` so each feature does not reimplement fetch logic or response normalization. Prefer a small typed client around the existing backend endpoints over ad hoc `fetch` calls spread across components.

For Milestone 6, define a stable tracker write contract in the tracker integration layer before exposing any HTTP surface. One acceptable shape is a protocol or service in `apps/api/symphony/tracker/` with explicit methods for adding comments, changing state, and attaching pull-request metadata, plus normalized result types and error codes. Any HTTP or CLI surface added on top of that contract should delegate to the same service and should not embed tracker-specific mutation logic directly in views.

Revision Note: 2026-03-10 / Codex. Replaced the placeholder active plan with a roadmap-derived ExecPlan so the tasks described in `docs/ROADMAP.md` are now sequenced into concrete milestones with repository context, commands, validation, and documentation-sync requirements.
