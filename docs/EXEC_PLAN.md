# Deliver a Plane Self-Host Tracker Adapter Without Semantic Drift

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

After this change, Symphony will be able to read work from a self-hosted Plane instance and execute the same orchestration flow that currently works only with Linear. An operator will be able to point `WORKFLOW.md` at `tracker.kind: plane`, start the orchestrator, watch eligible Plane issues enter the runtime snapshot, and use the existing backend-owned tracker write endpoints to add comments, transition issue state, and attach pull request context in a Plane-compatible way.

The most important outcome is architectural, not cosmetic. The repository must stop treating “tracker” as a synonym for Linear. A contributor should be able to add or evolve tracker kinds by implementing a bounded adapter layer, not by scattering tracker-specific conditionals across orchestration, API views, or Angular state. This plan therefore starts by defining stable interfaces and typed configuration boundaries before any Plane transport code is added.

## Progress

- [x] 2026-03-11 03:22Z: Read `.agent/PLANS.md`, the tracker sections of `docs/SPEC.md`, the current `docs/EXEC_PLAN.md`, and the relevant backend modules to identify where tracker behavior is coupled to Linear today.
- [x] 2026-03-11 03:22Z: Used Context7 to capture the current Plane API facts needed for planning: self-hosted instances use a deployment-specific base URL, server-to-server requests authenticate with `X-API-Key`, issues are exposed through REST paths under `/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/`, comments are exposed under `/comments/`, and issue links are exposed under `/links/`.
- [x] 2026-03-11 03:22Z: Replaced the completed roadmap closeout plan with this new active ExecPlan focused on Plane integration and tracker abstraction.
- [x] 2026-03-11 05:14Z: Completed Milestone 1. Added `apps/api/symphony/tracker/interfaces.py` and `apps/api/symphony/tracker/factory.py`, routed `apps/api/symphony/orchestrator/core.py` and `apps/api/symphony/tracker/write_service.py` through those shared seams, and added focused tests for the new factory path.
- [x] 2026-03-11 05:14Z: Validated Milestone 1 in a sanitized shell environment that unsets inherited `LINEAR_API_KEY`, `SYMPHONY_RUNTIME_*`, `SYMPHONY_WORKFLOW_PATH`, and `VIRTUAL_ENV` exports. Evidence: pre-change baseline `114 passed in 4.12s`; post-change milestone suite `107 passed in 4.15s`; focused factory tests `2 passed in 0.04s`; combined regression check `109 passed in 4.12s`; `uv run ruff check ...` and `uv run mypy apps/api` both passed.
- [ ] Extend workflow configuration and validation so `tracker.kind: plane` is a first-class typed configuration with self-host-friendly fields.
- [ ] Add a Plane adapter for issue reads, issue normalization, issue comments, issue state transitions, and pull request link attachment.
- [ ] Update tests, docs, and operator-facing examples so the repository describes a pluggable tracker system instead of a Linear-only system.

## Surprises & Discoveries

- Observation: the runtime state itself is already close to tracker-neutral. `apps/api/symphony/orchestrator/core.py` consumes a normalized `Issue` model and does not rely on GraphQL cursors, Linear team IDs, or other transport details during dispatch, retry, reconciliation, or snapshot publication.
  Evidence: `apps/api/symphony/orchestrator/core.py` only requires `Issue.id`, `Issue.identifier`, `Issue.state`, `Issue.priority`, and `Issue.blocked_by` from tracker reads, while `apps/api/symphony/observability/runtime.py` currently emits `tracked: {}` rather than tracker-specific payloads.

- Observation: the strongest coupling is concentrated in three places: workflow validation, adapter construction, and the write contract’s state-scope vocabulary.
  Evidence: `apps/api/symphony/workflow/config.py` only validates `tracker.kind == "linear"` and falls back to `LINEAR_API_KEY`; `apps/api/symphony/orchestrator/core.py` and `apps/api/symphony/tracker/write_service.py` instantiate `LinearTrackerClient` directly; `apps/api/symphony/tracker/write_contract.py` exposes `team_id` and `project_slug`, which are Linear-flavored names.

- Observation: Plane’s published API shape is REST-first, not GraphQL-first, and self-hosting changes the base URL story materially.
  Evidence: Context7’s Plane developer docs describe issue reads under `/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/`, comments under `/comments/`, links under `/links/`, and `X-API-Key` authentication, while the self-hosting docs note that the effective base URL depends on the deployment domain and setup.

- Observation: Plane has an obvious match for comments and a plausible match for pull request metadata, but the current Symphony “attachment” naming no longer fits the external system cleanly.
  Evidence: Context7 exposes Plane comment endpoints and issue link endpoints, but the current Symphony write contract is named around `TrackerAttachment` and serializes `attachment_id`, which reflects Linear `attachmentCreate` rather than a tracker-neutral concept.

- Observation: the focused Milestone 1 pytest baselines are sensitive to inherited shell exports from another live Symphony workspace, even before tracker refactor code changes.
  Evidence: running the documented pre-change suite in the inherited shell failed with `16 failed, 98 passed in 3.60s` because `LINEAR_API_KEY` changed workflow-config expectations and `SYMPHONY_RUNTIME_*` plus `SYMPHONY_WORKFLOW_PATH` pointed at another workspace’s live runtime files; rerunning the exact suite with those variables unset passed with `114 passed in 4.12s`.

## Decision Log

- Decision: Introduce a tracker adapter framework before adding any Plane transport code.
  Rationale: the current repository couples tracker selection to direct `LinearTrackerClient(...)` construction in runtime code. Adding Plane without a factory and protocols would spread tracker conditionals into the orchestrator and API layer, which is the semantic drift this plan is intended to prevent.
  Date/Author: 2026-03-11 / Codex

- Decision: Replace the single flat Linear-shaped tracker configuration with distinct typed tracker config dataclasses for Linear and Plane, kept behind a shared `ServiceConfig.tracker` union.
  Rationale: reusing fields like `endpoint` and `project_slug` for Plane would overload names and force future readers to remember tracker-specific reinterpretations. Separate dataclasses keep the meaning of each field stable.
  Date/Author: 2026-03-11 / Codex

- Decision: Generalize mutation scope names from `team_id` and `project_slug` to neutral identifiers such as `workflow_scope_id` and `project_ref`.
  Rationale: state transitions need a way to say “which state list applies to this issue,” but that concept is not always a Linear team. Renaming the contract at the boundary avoids baking Linear vocabulary into every future adapter.
  Date/Author: 2026-03-11 / Codex

- Decision: Keep the existing repository-owned `/pull-request` endpoint, but migrate its internal storage model from “attachment” to “link-backed pull request artifact,” using Plane issue links as the first target implementation.
  Rationale: the user-facing action remains “attach pull request context to an issue,” but Plane exposes issue links rather than Linear attachments. Preserving the endpoint behavior while neutralizing internal terminology gives the system a stable purpose and a tracker-specific implementation detail.
  Date/Author: 2026-03-11 / Codex

- Decision: Preserve the runtime snapshot and Angular API response shapes for issue execution state unless a Plane requirement forces a change.
  Rationale: the runtime UI is already tracker-neutral enough. Changing it during the adapter refactor would expand the scope without helping the main integration goal.
  Date/Author: 2026-03-11 / Codex

## Outcomes & Retrospective

Milestone 1 is now complete on this branch. The repository has a concrete tracker extension seam: `apps/api/symphony/tracker/interfaces.py` defines the shared read and mutation protocols, `apps/api/symphony/tracker/factory.py` is the single runtime selector for tracker adapters, and the orchestrator plus write service no longer construct `LinearTrackerClient` directly outside the tracker package. The main lesson from this milestone is that the adapter boundary was genuinely low-risk: the Linear implementation stayed intact while the call sites became tracker-neutral. The remaining work is now concentrated in configuration typing, Plane transport, and write-contract neutralization rather than in runtime wiring.

## Context and Orientation

Symphony is a long-running service that polls a tracker, decides which issues are eligible to run, starts a Codex-backed worker for each eligible issue, keeps runtime state in memory, and publishes a read-only runtime snapshot for the HTTP API and Angular UI. In this repository, the “orchestrator” is the scheduling and retry loop in `apps/api/symphony/orchestrator/core.py`. A “tracker adapter” is the module that knows how to talk to one external issue tracker and convert its payloads into Symphony’s normalized domain models.

The repository is now partly through the abstraction work. The normalized `Issue` model lives in `apps/api/symphony/tracker/models.py`. `apps/api/symphony/tracker/interfaces.py` defines `TrackerReadClient` and `TrackerMutationBackend`, and `apps/api/symphony/tracker/factory.py` is now the only runtime place that chooses the concrete tracker adapter. `TrackerMutationService` in `apps/api/symphony/tracker/write_service.py` already hides some write orchestration details behind that backend protocol. The remaining coupling is no longer runtime construction; it is mainly configuration shape and Linear-flavored write-contract vocabulary.

The current hot spots are these:

`apps/api/symphony/workflow/config.py` defines `TrackerConfig` with Linear-shaped fields, defaults the endpoint to `https://api.linear.app/graphql`, validates only `tracker.kind == "linear"`, and falls back only to `LINEAR_API_KEY`.

`apps/api/symphony/tracker/linear_client.py` owns all tracker reads and writes, including candidate issue fetch, issue-state refresh, issue lookup, workflow-state listing, comment creation, attachment creation, and issue state update. It assumes Linear GraphQL queries, GraphQL pagination, and Linear-specific error codes.

`apps/api/symphony/tracker/linear.py` normalizes Linear issue payloads into `Issue`, including label, blocker, branch, and timestamp extraction.

`apps/api/symphony/orchestrator/core.py` now imports `TrackerReadClient` and `build_tracker_read_client` from the tracker package, so future tracker kinds can plug in without changing orchestration code.

`apps/api/symphony/tracker/write_contract.py` and `apps/api/symphony/tracker/write_service.py` present a partly generic write contract, but that contract still carries Linear vocabulary through `team_id`, `project_slug`, `TrackerAttachment`, GraphQL-oriented metadata validation language, and direct normalization of Linear exception types.

`apps/api/symphony/api/views.py` exposes backend-owned write endpoints. These views are already useful because they speak in tracker-neutral user actions such as “comment,” “state transition,” and “pull request attachment.” They should remain thin request/response adapters and must not grow tracker business logic.

The Context7 research adds the key external facts that shape this plan. Plane’s public API uses REST paths under `/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/`. Self-hosted instances do not use a universal cloud hostname; the operator supplies the base URL for their own deployment. Authentication for server-side API calls is done with `X-API-Key`. Plane exposes issue comments under `/comments/` and issue links under `/links/`. Those facts make Plane a good fit for a dedicated adapter, but they also confirm that overloading Linear’s GraphQL-oriented config and naming would create confusion.

## Plan of Work

The strict adapter boundary is now in place. `apps/api/symphony/tracker/interfaces.py` defines the read protocol used by the orchestrator and the mutation backend protocol used by `TrackerMutationService`. `apps/api/symphony/tracker/factory.py` is the only runtime module that chooses a concrete tracker implementation from `ServiceConfig`. `apps/api/symphony/orchestrator/core.py` now depends on the read protocol and the factory, and `apps/api/symphony/tracker/write_service.py` now depends on the mutation backend protocol and the factory. No runtime module outside the tracker package imports `LinearTrackerClient` directly anymore. Future milestones must preserve this boundary instead of reintroducing tracker selection elsewhere.

At the same time, reshape workflow configuration to stop reinterpreting Linear names as generic concepts. In `apps/api/symphony/workflow/config.py`, replace the single flat tracker dataclass with a small family of typed dataclasses. `LinearTrackerConfig` should keep the existing GraphQL endpoint and `project_slug` semantics. `PlaneTrackerConfig` should carry `api_base_url`, `api_key`, `workspace_slug`, and `project_id`, plus the shared `active_states` and `terminal_states`. `ServiceConfig.tracker` becomes a union of those dataclasses. `build_service_config(...)` and `validate_dispatch_config(...)` must branch by tracker kind and produce precise error messages for missing Plane fields without disturbing Linear behavior. This is the core design move that prevents later semantic drift.

With the boundary in place, build the Plane read path. Add `apps/api/symphony/tracker/plane.py` for payload normalization and `apps/api/symphony/tracker/plane_client.py` for HTTP transport. The client must implement the same read protocol as Linear: fetch candidate issues, fetch issues by states, and fetch issue states by IDs. Use the REST paths from the Plane docs: list issues under `/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/`, paginate using the API’s cursor fields, and authenticate every request with `X-API-Key`. Keep Plane-specific parsing and error mapping inside the tracker package. The normalized `Issue` model should not change unless the new tracker truly requires one additional field that both trackers can provide meaningfully.

Before the Plane write path lands, neutralize the write contract language. In `apps/api/symphony/tracker/write_contract.py`, rename `team_id` to `workflow_scope_id` and rename `project_slug` to `project_ref`. Replace `TrackerAttachment` with a neutral link-oriented model such as `TrackerArtifactLink` or `TrackerIssueLink`, then update `TrackerPullRequestResult` to refer to that neutral model. The API view in `apps/api/symphony/api/views.py` may preserve the existing response envelope for one transition period if compatibility is required, but the internal contract must stop pretending that every tracker has Linear attachments. Update the write service to resolve transition targets by `workflow_scope_id` rather than by Linear team ID.

After that refactor, implement Plane writes inside `apps/api/symphony/tracker/plane_client.py`. Use the Plane comment endpoint for `add_comment`, the issue update endpoint with a new state UUID for `transition_issue`, and the Plane issue links endpoint to store pull request URLs. The plan assumes that a pull request “attachment” in Plane is best modeled as a link plus optional metadata carried in a bounded, repository-owned encoding. If the issue link API cannot store all of the current metadata fields natively, add a small normalization rule in the Plane adapter and document it clearly in tests and docs. Do not push that workaround into `TrackerMutationService` or the HTTP views.

The last code milestone is repository-wide cleanup. Update `apps/api/symphony/tracker/__init__.py` and `apps/api/symphony/tracker/README.md` to export and describe the generic adapter framework. Update `apps/api/symphony/agent_runner/prompting.py` so the fallback prompt says “issue from the configured tracker” or includes the tracker kind rather than naming Linear. Update `docs/SPEC.md`, `docs/development.md`, and any tests that currently assert Linear-only behavior. The finished repository must describe tracker support accurately: Linear remains supported, Plane is added, and new adapters are expected to plug in through the same interfaces.

### Milestone 1: Establish the adapter framework

At the end of this milestone, the repository still behaves exactly as a Linear-only system, but the code structure no longer hard-codes that fact in the orchestrator or API layer. A contributor will be able to point to a single factory and two small protocols as the extension points for any tracker kind.

Create `apps/api/symphony/tracker/interfaces.py` and `apps/api/symphony/tracker/factory.py`. Move the read protocol out of `apps/api/symphony/orchestrator/core.py` into the tracker package, move the mutation backend protocol out of `apps/api/symphony/tracker/write_service.py` into the same shared interface module, and update both callers to consume those definitions. In the factory module, define one builder for read clients and one builder for mutation backends. Both builders should switch on the typed tracker config, returning `LinearTrackerClient` for existing workflows. Update `apps/api/symphony/orchestrator/core.py` and `apps/api/symphony/tracker/write_service.py` to use those builders. The proof for this milestone is behavioral: every existing Linear-focused unit test still passes, but no module outside `apps/api/symphony/tracker/` constructs a tracker client directly.

### Milestone 2: Add typed tracker configuration

At the end of this milestone, `WORKFLOW.md` can express either a Linear config or a Plane config without reusing misleading field names. The repository still only needs to run Linear code paths at this moment, but the config layer is ready for Plane.

Refactor `apps/api/symphony/workflow/config.py` so `ServiceConfig.tracker` is a union of `LinearTrackerConfig` and `PlaneTrackerConfig`. Keep shared state lists in both dataclasses so the orchestrator remains generic. Add Plane-specific validation errors such as missing API base URL, missing workspace slug, and missing project ID. Update the relevant workflow config tests in `apps/api/tests/unit/workflow/test_config.py`, `apps/api/tests/unit/workflow/test_runtime.py`, `apps/api/tests/unit/orchestrator/test_core.py`, and `apps/api/tests/unit/management/test_run_orchestrator.py`. The proof for this milestone is that invalid Plane configs fail early with precise messages and valid Linear configs remain unchanged.

### Milestone 3: Implement Plane reads and runtime dispatch

At the end of this milestone, a self-hosted Plane workflow can populate the runtime snapshot and drive dispatch decisions. Starting the orchestrator with `tracker.kind: plane` and valid Plane credentials will fetch eligible issues, normalize them into `Issue`, and let the scheduler claim, run, retry, and reconcile them exactly as it does for Linear.

Add `apps/api/symphony/tracker/plane.py` and `apps/api/symphony/tracker/plane_client.py`. Keep HTTP transport details and Plane error mapping inside the client. Plane reads must use the deployment-specific base URL, prepend the documented `/api/v1/...` paths, send `X-API-Key`, and normalize the API’s pagination responses. Add focused tests under `apps/api/tests/unit/tracker/` for issue list pagination, issue state refresh, issue lookup, and normalization. Then add an orchestrator-focused test that proves a mocked Plane client can drive dispatch without changing orchestration semantics.

### Milestone 4: Neutralize and implement the write contract

At the end of this milestone, the backend-owned write surface can target either tracker kind without leaking Linear concepts into its internal types. The `/comments`, `/transition`, and `/pull-request` endpoints still exist, but their backing contract is tracker-neutral and Plane-backed when `tracker.kind: plane`.

Refactor `apps/api/symphony/tracker/write_contract.py` and `apps/api/symphony/tracker/write_service.py` first. Rename state-scope fields to neutral names, generalize the pull request link model, and update the service to resolve transition states by a generic workflow scope. Then implement the Plane backend methods in `apps/api/symphony/tracker/plane_client.py`: use the comment endpoint for comments, issue `PATCH` for state updates, and issue link endpoints for pull request URLs. If the Plane link API cannot store arbitrary metadata fields directly, restrict the metadata contract deliberately and encode only the fields the adapter can round-trip safely; record that choice in tests and docs rather than leaving it implicit. Add API endpoint tests under `apps/api/tests/unit/api/test_tracker_writes.py` for the Plane path as well as the existing service tests.

### Milestone 5: Documentation, examples, and cleanup

At the end of this milestone, a new contributor can discover the Plane integration path from repository docs alone. The spec, development notes, tracker README, and prompt fallback language all describe the repository’s actual design rather than the older Linear-only baseline.

Update `docs/SPEC.md` so the tracker section describes Linear and Plane as supported kinds, and move any remaining Linear-only details into kind-specific subsections. Update the optional `linear_graphql` tool language so it is explicitly Linear-only rather than described as the generic tracker extension path. Update `docs/development.md` with a Plane example that uses a self-hosted base URL, `PLANE_API_KEY`, workspace slug, and project ID. Update `apps/api/symphony/tracker/README.md` to describe the factory, protocols, and per-tracker adapter files. Finally, update `apps/api/symphony/agent_runner/prompting.py` to stop naming Linear in the fallback prompt.

## Concrete Steps

Work from the repository root, `/Users/mike/projs/main/symphony`, unless a step says otherwise.

Before implementation begins, run the current focused baseline to freeze the existing behavior:

    uv run pytest apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/tracker/test_linear.py apps/api/tests/unit/tracker/test_linear_client.py apps/api/tests/unit/tracker/test_write_service.py apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/api/test_tracker_writes.py -q

Expect the suite to pass with no failures. Record the exact summary in `Progress` before editing any tracker code.

After Milestone 1, run:

    uv run pytest apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/tracker/test_linear_client.py apps/api/tests/unit/tracker/test_write_service.py apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/api/test_tracker_writes.py -q

Expect all existing Linear-path tests to remain green and import paths to no longer require direct `LinearTrackerClient` construction outside `apps/api/symphony/tracker/`.

After Milestone 2, run:

    uv run pytest apps/api/tests/unit/workflow/test_config.py apps/api/tests/unit/workflow/test_runtime.py apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/management/test_run_orchestrator.py -q

Expect new Plane config cases to pass and invalid Plane workflow definitions to fail with precise error codes and messages.

After Milestone 3, run:

    uv run pytest apps/api/tests/unit/tracker/test_plane.py apps/api/tests/unit/tracker/test_plane_client.py apps/api/tests/unit/orchestrator/test_core.py apps/api/tests/unit/api/test_state.py -q

Expect focused Plane read-path tests to pass and at least one orchestrator test to prove that a Plane-backed config can populate runtime state without touching Linear code paths.

After Milestone 4, run:

    uv run pytest apps/api/tests/unit/tracker/test_write_service.py apps/api/tests/unit/api/test_tracker_writes.py apps/api/tests/unit/tracker/test_plane_client.py -q

Expect comment creation, state transition, and pull request link attachment to pass for Plane-backed tests, including idempotent repeated pull request submissions against the same issue URL.

After Milestone 5, run the repository-wide checks:

    make format
    make lint
    make typecheck
    make test

Expect all checks to pass. If `make test` depends on environment-specific networking, document the exact failing test and the environment limitation in `Progress` and `Surprises & Discoveries`.

For a manual smoke with a real self-hosted Plane instance after Milestone 4, prepare a repository-local `WORKFLOW.md` whose front matter resembles this:

    ---
    tracker:
      kind: plane
      api_base_url: https://plane.example.com
      api_key: $PLANE_API_KEY
      workspace_slug: engineering
      project_id: 88c2d97c-a6ad-4012-b526-5577c0d7c769
      active_states: Todo, In Progress
      terminal_states: Done, Canceled
    ---
    # Prompt body
    Continue working on {{ issue.identifier }}.

Then export credentials and run the backend:

    export PLANE_API_KEY=plane_api_example
    make dev-api

In another terminal, verify the read-only snapshot and one write path:

    curl http://127.0.0.1:8000/api/v1/state
    curl -X POST http://127.0.0.1:8000/api/v1/tracker/issues/ENG-123/comments -H 'Content-Type: application/json' -d '{"body":"Ready for review"}'

Expect the runtime state response to include Plane-backed issue identifiers and the comment endpoint to return HTTP `200` with the normalized Symphony response envelope.

## Validation and Acceptance

Acceptance is behavioral and must be observable without reading the source.

After Milestone 1, the orchestrator and API code still pass all existing Linear tests, but the only modules allowed to know about `LinearTrackerClient` are inside `apps/api/symphony/tracker/`.

After Milestone 2, a workflow with `tracker.kind: plane` and missing `api_base_url`, `workspace_slug`, `project_id`, or `api_key` fails validation immediately, while the existing Linear workflow examples remain valid.

After Milestone 3, a valid Plane workflow can fetch active issues from a self-hosted Plane instance, convert them into `Issue`, and expose them through `/api/v1/state` and `/api/v1/<issue_identifier>` using the existing runtime snapshot shapes.

After Milestone 4, the backend-owned write endpoints can create a Plane comment, perform a Plane issue state transition, and attach a pull request URL to a Plane issue in a repeatable way. Repeating the same `/pull-request` request for the same issue and URL must not create duplicate logical records in Symphony’s view of the world.

After Milestone 5, `docs/SPEC.md`, `docs/development.md`, and `apps/api/symphony/tracker/README.md` describe both Linear and Plane accurately, and the fallback prompt no longer tells the agent it is always working on a Linear issue.

The plan is complete only when `make lint`, `make typecheck`, and `make test` pass after the final milestone and the repository docs no longer describe tracker support as Linear-only.

## Idempotence and Recovery

Every milestone in this plan must remain safe to apply incrementally. The factory and interface refactor is additive and can coexist with the Linear implementation until all callers have moved. The config refactor must preserve the ability to parse existing Linear workflows unchanged. Plane tests should use mocked transports by default so they remain deterministic and rerunnable without a live Plane instance.

If a milestone lands partially, keep the factory returning only the fully implemented adapters and fail unsupported paths explicitly rather than leaving a half-wired tracker kind silently selected. For write-path work, preserve the repository-owned `/pull-request` endpoint and make any compatibility aliases explicit in tests so the team can safely tighten them later. For docs, update examples only after the corresponding behavior exists; do not publish Plane workflow examples that the code cannot yet execute.

## Artifacts and Notes

The current repository locations that must be revisited during implementation are:

`apps/api/symphony/workflow/config.py` for typed tracker config and validation.

`apps/api/symphony/tracker/models.py` for the normalized `Issue` model that must remain tracker-neutral.

`apps/api/symphony/tracker/linear.py` and `apps/api/symphony/tracker/linear_client.py` for the Linear reference implementation that the new Plane adapter should mirror structurally, not semantically.

`apps/api/symphony/tracker/write_contract.py` and `apps/api/symphony/tracker/write_service.py` for mutation contract neutralization.

`apps/api/symphony/orchestrator/core.py` for replacing direct adapter construction with factory usage.

`apps/api/symphony/api/views.py` for preserving thin HTTP request/response handling while the backend implementation changes underneath.

`apps/api/tests/unit/tracker/` and `apps/api/tests/unit/api/` for focused regression coverage.

`docs/SPEC.md` and `docs/development.md` for repository-facing documentation cleanup.

The key external facts that should be treated as locked for this plan are these. Plane server-to-server calls use a deployment-specific base URL in self-hosted installations, not a single cloud hostname. API authentication uses `X-API-Key`. Issue reads live under `/api/v1/workspaces/{workspace_slug}/projects/{project_id}/issues/`. Comments live under `/comments/`. Issue links live under `/links/`. Those facts came from the 2026-03-11 Context7 research and should be rechecked only if the implementation uncovers a documented mismatch.

## Interfaces and Dependencies

In `apps/api/symphony/tracker/interfaces.py`, define:

    class TrackerReadClient(Protocol):
        def fetch_candidate_issues(self) -> list[Issue]: ...
        def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]: ...
        def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]: ...

    class TrackerMutationBackend(Protocol):
        def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None: ...
        def list_workflow_states(self) -> list[TrackerWorkflowState]: ...
        def create_comment(self, issue_id: str, body: str) -> TrackerComment: ...
        def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference: ...
        def create_pull_request_link(
            self,
            *,
            issue_id: str,
            title: str,
            url: str,
            subtitle: str | None,
            metadata: Mapping[str, JsonScalar],
        ) -> TrackerIssueLink: ...

In `apps/api/symphony/tracker/factory.py`, define:

    def build_tracker_read_client(config: ServiceConfig) -> TrackerReadClient: ...
    def build_tracker_mutation_backend(config: ServiceConfig) -> TrackerMutationBackend: ...

`build_tracker_mutation_service(config: ServiceConfig)` should remain in `apps/api/symphony/tracker/write_service.py`, but it must call `build_tracker_mutation_backend(...)` instead of constructing tracker clients directly.

In `apps/api/symphony/workflow/config.py`, define at minimum:

    @dataclass(slots=True, frozen=True)
    class LinearTrackerConfig:
        kind: Literal["linear"]
        endpoint: str
        api_key: str | None
        project_slug: str | None
        active_states: tuple[str, ...]
        terminal_states: tuple[str, ...]

    @dataclass(slots=True, frozen=True)
    class PlaneTrackerConfig:
        kind: Literal["plane"]
        api_base_url: str
        api_key: str | None
        workspace_slug: str | None
        project_id: str | None
        active_states: tuple[str, ...]
        terminal_states: tuple[str, ...]

    TrackerConfig = LinearTrackerConfig | PlaneTrackerConfig

In `apps/api/symphony/tracker/write_contract.py`, the neutral mutation scope and pull request link types must look like this at the end of the refactor:

    @dataclass(slots=True, frozen=True)
    class TrackerIssueReference:
        id: str
        identifier: str
        state_id: str
        state_name: str
        workflow_scope_id: str
        project_ref: str | None

    @dataclass(slots=True, frozen=True)
    class TrackerWorkflowState:
        id: str
        name: str
        workflow_scope_id: str

    @dataclass(slots=True, frozen=True)
    class TrackerIssueLink:
        id: str
        title: str
        url: str
        subtitle: str | None
        metadata: dict[str, JsonScalar]

In `apps/api/symphony/tracker/plane_client.py`, define:

    @dataclass(slots=True)
    class PlaneTrackerClient(TrackerReadClient, TrackerMutationBackend):
        tracker_config: PlaneTrackerConfig
        timeout_ms: int = DEFAULT_PLANE_TIMEOUT_MS
        transport: PlaneTransport | None = None

This client must be the single owner of Plane URL construction, authentication headers, payload parsing, pagination handling, and Plane-specific exception mapping.

Plan revision note: 2026-03-11 / Codex. Replaced the completed roadmap closeout plan with a new active ExecPlan focused on introducing a tracker adapter framework and a Plane self-host integration path, because the repository’s next major change is no longer roadmap closeout work but a tracker abstraction and second adapter implementation.

Plan revision note: 2026-03-11 05:15Z / Codex. Updated the living plan after Milestone 1 landed so `Progress`, `Surprises & Discoveries`, `Outcomes & Retrospective`, and the current repository orientation match the branch state. Added the adapter-factory completion evidence and documented that inherited `LINEAR_API_KEY` plus `SYMPHONY_RUNTIME_*` exports from another workspace must be unset for the focused tracker baseline to be deterministic.
