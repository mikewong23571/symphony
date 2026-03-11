# Add Backend-Driven Runtime Auto-Refresh for the Angular Dashboard

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

After this change, an operator can leave the runtime dashboard or an issue detail page open and watch backend-owned runtime state update without manually reloading the browser. The backend remains the only authority for runtime state: the browser keeps reading canonical REST snapshots, while optional server-sent events (SSE) only act as lightweight invalidation nudges that trigger another REST fetch.

The user-visible proof is straightforward. Start the runtime sidecar, open the Angular dashboard, let the orchestrator change runtime state, and observe running or retrying rows update on their own. Open an issue detail page for a running or retrying issue and observe its status-related fields refresh without a full page reload. Trigger `POST /api/v1/refresh` and observe the UI catch up automatically.

## Progress

- [x] 2026-03-11 11:35Z: Routed the ticket from `Todo` to `In Progress`, created the Linear workpad, and synced the repository from `origin/main`.
- [x] 2026-03-11 11:42Z: Audited the current runtime fetch flow. Confirmed that Angular runtime pages use one-shot `HttpClient` requests with no shared polling, focus recovery, or `EventSource` handling.
- [x] 2026-03-11 11:44Z: Audited the backend runtime surface. Confirmed that the orchestrator already republishes the snapshot on meaningful state changes and that `/api/v1/state`, `/api/v1/<issue_identifier>`, and `/api/v1/refresh` are the existing REST contracts.
- [ ] Add monotonic snapshot revision metadata, issue-detail freshness metadata, and a lightweight SSE invalidation bus plus `/api/v1/events`.
- [ ] Add a shared Angular runtime session service that owns polling, focus/visibility recovery, and SSE-triggered revalidation.
- [ ] Rewire dashboard and issue detail to consume the shared runtime session service instead of owning fetch state directly.
- [ ] Add focused backend and frontend tests plus docs for the refresh model and WSGI streaming tradeoff.

## Surprises & Discoveries

- Observation: the backend already refreshes the in-memory and on-disk runtime snapshot on every meaningful orchestrator transition, so the missing behavior is propagation to the browser rather than backend publication.
  Evidence: `apps/api/symphony/orchestrator/core.py` calls `_refresh_runtime_snapshot()` from startup, dispatch, running-state reconciliation, retry scheduling, retry release, and heartbeat paths.

- Observation: the issue detail endpoint currently omits snapshot freshness metadata even though dashboard state already exposes `generated_at` and `expires_at`.
  Evidence: `apps/api/symphony/observability/runtime.py:get_runtime_issue_snapshot(...)` returns issue-specific details only, while `apps/api/symphony/api/views.py:runtime_issue(...)` forwards that object directly.

- Observation: the current frontend has no reusable runtime data layer; dashboard and issue detail each own their own initial load and error state.
  Evidence: `apps/web/src/app/features/dashboard/dashboard-page.component.ts` and `apps/web/src/app/features/issues/issue-detail-page.component.ts` both subscribe directly to `RuntimeApiService`.

## Decision Log

- Decision: keep REST snapshots as the canonical read contract and use SSE only for invalidation, never for full runtime payloads.
  Rationale: this preserves backend authority, keeps the current API contract central, and matches the ticket’s architectural constraints.
  Date/Author: 2026-03-11 / Codex

- Decision: add a monotonic `revision` field to runtime snapshot responses and mirror snapshot freshness metadata onto issue-detail responses.
  Rationale: the frontend needs a stable deduplication key and a consistent way to schedule the next refresh for both summary and issue-specific views.
  Date/Author: 2026-03-11 / Codex

- Decision: introduce one shared Angular runtime session service rather than embedding timers, browser lifecycle listeners, or `EventSource` instances in page components.
  Rationale: the ticket explicitly rejects per-component unmanaged timers, and a root-provided service is the narrowest way to keep revalidation policy centralized.
  Date/Author: 2026-03-11 / Codex

## Outcomes & Retrospective

Work is in progress. The implementation target is clear: backend publication is already present, but browser revalidation is not. The remaining risk is making freshness metadata, SSE invalidation, and Angular scheduling line up cleanly without weakening the existing REST semantics.

## Context and Orientation

The backend runtime sidecar lives under `apps/api/symphony/api/` and `apps/api/symphony/observability/`. `apps/api/symphony/api/views.py` defines the HTTP endpoints for the dashboard HTML view, runtime JSON state, issue detail JSON, and the manual refresh trigger. `apps/api/symphony/observability/runtime.py` loads and shapes runtime snapshot data for those views. `apps/api/symphony/orchestrator/core.py` is the scheduler loop that owns the live runtime state and republishes the snapshot whenever the runtime changes.

The Angular frontend lives under `apps/web/src/app/`. `apps/web/src/app/shared/api/runtime-api.service.ts` is the current stateless transport layer. `apps/web/src/app/features/dashboard/dashboard-page.component.ts` and `apps/web/src/app/features/issues/issue-detail-page.component.ts` are the two runtime pages that currently fetch once and then stop. `apps/web/src/app/shared/lib/runtime-presenters.ts` maps raw REST payloads into display-oriented view models.

A “runtime snapshot” in this repository is the backend-owned JSON representation of running issues, retrying issues, aggregate Codex totals, rate limits, and freshness timestamps. “Freshness metadata” means `generated_at`, `expires_at`, and the new monotonic `revision` field this task adds. “Invalidation” means a tiny backend-to-browser signal that tells the browser “re-fetch the REST snapshot now”; it does not carry the full runtime state itself.

## Plan of Work

Start by extending the backend snapshot contract. In `apps/api/symphony/orchestrator/core.py`, add a runtime revision counter that increments every time `_refresh_runtime_snapshot()` rebuilds the canonical snapshot. Include that `revision` in the `/api/v1/state` payload and pass the snapshot’s `generated_at`, `expires_at`, and `revision` through `get_runtime_issue_snapshot(...)` so issue detail responses can schedule their own refreshes with the same freshness window.

Next, add a small invalidation event broker under `apps/api/symphony/observability/`. It should keep a short in-memory history of lightweight events and allow waiting for the next event after a given sequence number. Expose it through a new `/api/v1/events` endpoint in `apps/api/symphony/api/views.py` and `apps/api/config/urls.py` using Django `StreamingHttpResponse` with `text/event-stream`. This endpoint should publish only invalidation events such as `snapshot_updated`, `issue_changed`, and `refresh_queued`, with concise JSON payloads that include the latest snapshot revision and any directly relevant issue identifiers. Document clearly that each connected browser consumes one WSGI worker thread for the life of the stream, which is acceptable only for a small internal operator audience.

Then add a shared Angular runtime session service, likely alongside `RuntimeApiService` in `apps/web/src/app/shared/api/`. This service should own one shared subscription to `/api/v1/state` plus keyed issue-detail resources. It should compute the next polling deadline from `expires_at`, trigger immediate revalidation on `visibilitychange` or `focus`, and optionally use a single `EventSource` connection to `/api/v1/events` to trigger early revalidation when the backend publishes an invalidation event. Page-local view concerns such as expanded dashboard cards stay in the components, but fetch lifecycle, polling, and SSE handling move into this shared service.

Finally, rewire the runtime pages to consume the shared service and add tests. Backend tests should prove the new `revision` and issue freshness metadata, the refresh-queued invalidation path, and SSE event formatting or wait behavior. Frontend tests should prove that the shared runtime service polls from `expires_at`, reacts to focus or visibility recovery, deduplicates repeated invalidations by revision, and keeps dashboard plus issue detail pages updating from the same policy.

## Concrete Steps

Work from the repository root, `/Users/mike/code/symphony-workspaces/MIK-47`.

Before editing backend code, review the existing runtime endpoints and snapshot builder:

    rg -n "runtime_state|runtime_issue|runtime_refresh|_refresh_runtime_snapshot|_build_runtime_snapshot" apps/api

Before editing frontend code, review the current one-shot fetch flow:

    rg -n "loadDashboard|loadIssue|requestRefresh|constructor\\(|paramMap" apps/web/src/app

During validation, run these commands from the repository root:

    make lint
    make typecheck
    make test

Run focused backend coverage while iterating:

    uv run pytest apps/api/tests/unit/api/test_state.py apps/api/tests/unit/orchestrator/test_core.py -q

Run focused frontend coverage while iterating:

    pnpm --dir apps/web test -- --runInBand

If a command fails because of unrelated inherited environment variables, sanitize the shell by unsetting `SYMPHONY_RUNTIME_*`, `SYMPHONY_WORKFLOW_PATH`, `LINEAR_API_KEY`, and `VIRTUAL_ENV` for the focused test invocation.

## Validation and Acceptance

Acceptance is behavioral. The dashboard should load once, then continue updating as backend state changes while the page remains open. Issue detail pages should do the same for the specific issue being viewed. The Angular code must use one shared refresh policy rather than page-specific timers.

Run the backend and frontend test commands above and expect them to pass. Then exercise the runtime UI manually by starting the runtime sidecar, opening the dashboard, and causing a runtime state transition. The visible running or retrying counts should update without browser reload. Trigger `POST /api/v1/refresh` and observe a subsequent automatic refresh. If SSE is enabled in the final implementation, restart the runtime sidecar while the page is open and verify that the browser reconnects or falls back to polling without getting stuck on stale data.

## Idempotence and Recovery

The code changes in this plan are additive and can be applied incrementally. The SSE endpoint must tolerate clients disconnecting at any point. The Angular runtime session service must be safe to start and stop repeatedly as routes mount and unmount. If the SSE stream fails or the browser does not support `EventSource`, polling based on `expires_at` remains the fallback path, so the UI continues to converge to backend state.

## Artifacts and Notes

Current reproduction signal, captured before implementation:

    apps/web/src/app/shared/api/runtime-api.service.ts only exposes cold REST reads.
    apps/web/src/app/features/dashboard/dashboard-page.component.ts loads once in the constructor and reloads only after the manual Refresh button succeeds.
    apps/web/src/app/features/issues/issue-detail-page.component.ts reloads only when the route parameter changes.
    Repository search found no EventSource, visibilitychange, focus, or polling logic in apps/web/src/app.

## Interfaces and Dependencies

The backend should continue using Django’s built-in HTTP response primitives. The SSE endpoint should use `StreamingHttpResponse` with `text/event-stream`, `Cache-Control: no-cache`, and a small keepalive cadence so idle streams stay open through internal proxies.

The backend invalidation broker should expose a small, testable API similar to:

    publish_runtime_invalidation(event_type: str, payload: Mapping[str, Any]) -> dict[str, Any]
    wait_for_runtime_invalidation(after_sequence: int | None, timeout_seconds: float) -> dict[str, Any] | None

The Angular shared runtime service should remain built on the existing `RuntimeApiService` transport boundary and Angular signals. It should expose shared state and issue-detail resources, plus explicit methods for manual refresh and lifecycle attachment, while keeping `RuntimeApiService` responsible for HTTP transport and `toRuntimeUiError(...)` normalization.

Plan revision note: 2026-03-11 11:45Z / Codex. Created this ticket-specific ExecPlan because `docs/EXEC_PLAN.md` currently tracks separate Plane tracker work and cannot be repurposed without losing the active plan for that effort.
