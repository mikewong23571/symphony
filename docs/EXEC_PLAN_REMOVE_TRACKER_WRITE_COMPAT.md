# Remove Tracker Write Compatibility Layer

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
Maintain this document in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

The tracker write path has already been internally generalized from Linear-specific attachment
language to tracker-neutral issue-link language, but the code still carries a compatibility layer
for older names and older method shapes. That layer now adds branching, duplicate types, and
duplicate test coverage without providing value inside this repository. The remaining compatibility
surface is concentrated in the tracker write contract, the mutation service, the Linear mutation
backend, and the HTTP response shape for pull-request writes.

After this change, the repository will expose exactly one internal write contract:

- issue references use `workflow_scope_id` and `project_ref`
- pull-request results use `TrackerIssueLink` and `issue_link`
- mutation backends implement `create_issue_link()`

The removal is observable in three ways. First, repository searches no longer find the compatibility
entry points in production code. Second, the tracker write API tests pass using only the new
contract. Third, `make lint`, `make typecheck`, and `make test` all pass after the deletion.

## Progress

- [ ] 2026-03-18: Audit all remaining tracker write compatibility entry points and confirm the final
      deletion set.
- [ ] 2026-03-18: Rewrite all production call sites to use only `workflow_scope_id`, `project_ref`,
      `TrackerIssueLink`, `issue_link`, and `create_issue_link()`.
- [ ] 2026-03-18: Remove the compatibility constructors, alias properties, alias exports, and legacy
      backend protocol support from `apps/api/lib/tracker/`.
- [ ] 2026-03-18: Update the tracker pull-request HTTP response shape and its tests so it no longer
      uses attachment terminology.
- [ ] 2026-03-18: Run `make lint`, `make typecheck`, `make test`, and final repository searches to
      confirm the compatibility layer is gone.

## Surprises & Discoveries

- Observation: the remaining compatibility code is tightly clustered rather than spread through the
  repository. The active compatibility points are the write contract, write service, backend
  protocol union, Linear client alias method, package export surface, and the tracker pull-request
  HTTP response.
  Evidence: `apps/api/lib/tracker/write_contract.py`, `apps/api/lib/tracker/write_service.py`,
  `apps/api/lib/tracker/interfaces.py`, `apps/api/lib/tracker/linear_client.py`,
  `apps/api/lib/tracker/__init__.py`, and `apps/api/symphony/api/views.py`.

- Observation: `tracker.project_slug` in workflow config is not compatibility debt in this plan. It
  is still the current Linear configuration field and must remain.
  Evidence: `apps/api/lib/workflow/config.py` defines `LinearTrackerConfig.project_slug` as a first-
  class field, and `docs/SPEC.md` still documents it as the required Linear project selector.

## Decision Log

- Decision: scope this plan only to tracker write compatibility code, not to tracker read config.
  Rationale: the compatibility debt identified in the repository audit is concentrated in write-path
  naming and method aliases. `tracker.project_slug` for Linear configuration is current product
  behavior, not a temporary alias, so deleting it would be an unrelated spec change.
  Date/Author: 2026-03-18 / Codex

- Decision: remove the compatibility layer directly rather than adding a deprecation-only phase.
  Rationale: the user is the sole active contributor in this repository and asked for a code-level
  cleanup plan rather than a staged consumer migration. A direct deletion keeps the codebase
  smaller and avoids maintaining temporary warnings that would themselves need later cleanup.
  Date/Author: 2026-03-18 / Codex

- Decision: treat the HTTP pull-request response as part of the compatibility layer and rename it in
  the same plan.
  Rationale: keeping `attachment_id` and `pull_request_attachment` in the API while deleting the
  internal attachment compatibility code would leave the repository half-migrated and force tests to
  encode old vocabulary. This plan keeps the internal and external names aligned.
  Date/Author: 2026-03-18 / Codex

## Outcomes & Retrospective

No implementation work has started yet. The expected end state is a smaller tracker write surface
with one contract, one backend method name, one result shape, and fewer branches and tests. Update
this section after each milestone with the exact files changed, the final API response shape, and
the validation results.

## Context and Orientation

### What “compatibility layer” means in this repository

This plan uses “compatibility layer” to mean code that accepts older names or older method shapes in
parallel with the current contract. The current contract is already visible in the field names
`workflow_scope_id`, `project_ref`, `TrackerIssueLink`, `issue_link`, and `create_issue_link()`.
The compatibility layer is everything that keeps older names working beside those names.

### Files that currently contain the compatibility layer

The central file is `apps/api/lib/tracker/write_contract.py`. It defines the tracker write data
models. Today it still accepts old constructor names and exposes old alias properties:

- `TrackerIssueReference.__init__` accepts `team_id` and `project_slug` beside
  `workflow_scope_id` and `project_ref`.
- `TrackerWorkflowState.__init__` accepts `team_id` beside `workflow_scope_id`.
- `TrackerAttachment` is an alias for `TrackerIssueLink`.
- `TrackerPullRequestResult.__init__` accepts both the new `issue_link` shape and old
  `attachment_id`-based constructor shapes, including old positional arguments.
- `TrackerPullRequestResult` still exposes alias properties such as `attachment_id`.

The service layer in `apps/api/lib/tracker/write_service.py` still accepts `project_slug` in
`TrackerMutationService.__init__` and still falls back from `create_issue_link()` to the older
`create_attachment()` backend method.

The protocol layer in `apps/api/lib/tracker/interfaces.py` still models two mutation backend
variants:

- `TrackerIssueLinkMutationBackend`
- `TrackerAttachmentMutationBackend`

The Linear implementation in `apps/api/lib/tracker/linear_client.py` still defines
`create_attachment()` as an alias to `create_issue_link()`.

The package export surface in `apps/api/lib/tracker/__init__.py` still re-exports
`TrackerAttachment`.

The HTTP layer in `apps/api/symphony/api/views.py` still returns attachment terminology from the
pull-request endpoint:

- `operation: "pull_request_attachment"`
- `pull_request.attachment_id`

### Files that are intentionally out of scope

`apps/api/lib/workflow/config.py` and the related spec sections for `tracker.project_slug` are not
part of this plan. That field is the current Linear tracker configuration field, not a temporary
write-path alias.

### Tests that currently enforce the compatibility layer

Compatibility-specific tests already exist and must be removed or rewritten as the code is cleaned
up. The most important ones live in:

- `apps/api/tests/unit/tracker/test_write_service.py`
- `apps/api/tests/unit/tracker/test_linear_client.py`
- `apps/api/tests/unit/api/test_tracker_writes.py`

These tests currently assert that old constructor keywords, old positional pull-request result
construction, old `create_attachment()` behavior, and old HTTP response fields still work. After the
cleanup, these tests must either be deleted or rewritten around the final contract.

## Plan of Work

### Milestone 1 — Rewrite all production code to the final tracker write contract

Start by removing all internal dependence on compatibility properties and compatibility method
shapes before deleting the compatibility code itself. The repository should already be able to use
the final contract everywhere.

In `apps/api/lib/tracker/write_service.py`, replace all internal use of `result.attachment_id` with
`result.issue_link.id`. Keep the logic unchanged; only stop depending on alias properties. Confirm
that no other production file still reads `attachment_id` from `TrackerPullRequestResult`.

In all production code that constructs `TrackerIssueReference`, `TrackerWorkflowState`, or
`TrackerPullRequestResult`, update the call sites to use only the new argument names:

- `workflow_scope_id`
- `project_ref`
- `issue_link`

Do not leave mixed constructor styles behind in production code. At the end of this milestone,
searches through non-test source files should find no uses of the old constructor keywords or old
pull-request result aliases.

In any backend implementation that still relies on the compatibility fallback path, rewrite it to
implement only `create_issue_link()`. The concrete production target here is
`apps/api/lib/tracker/linear_client.py`, which already has the final method and only needs the
alias method removed later. This milestone is complete when production code no longer depends on
`create_attachment()` existing anywhere.

### Milestone 2 — Delete the compatibility layer from the tracker write contract and backend

Once all production call sites use the final names, simplify `apps/api/lib/tracker/write_contract.py`
so the code matches the actual contract.

Delete the alias constructor parameters from `TrackerIssueReference` and `TrackerWorkflowState`. Each
class should accept only the current fields. Delete the alias properties `team_id` and
`project_slug`.

Delete `TrackerAttachment = TrackerIssueLink`. The repository should expose only
`TrackerIssueLink`.

Rewrite `TrackerPullRequestResult` so its initializer accepts only:

    issue_id: str
    issue_identifier: str
    status: str
    issue_link: TrackerIssueLink

Delete the old `attachment_id` constructor path, the old positional constructor path, the alias
properties, and the helper functions that exist only to normalize old constructor forms.

Then simplify `apps/api/lib/tracker/interfaces.py` so there is one mutation backend protocol with
one method for pull-request links: `create_issue_link()`.

In `apps/api/lib/tracker/write_service.py`, remove the `project_slug` compatibility parameter from
`TrackerMutationService.__init__` and delete the fallback path that looks for
`create_attachment()`. The service should require backends that implement the single final method.

In `apps/api/lib/tracker/linear_client.py`, delete `create_attachment()`.

In `apps/api/lib/tracker/__init__.py`, remove `TrackerAttachment` from imports and from `__all__`.

At the end of this milestone, the compatibility layer should no longer exist anywhere inside
`apps/api/lib/tracker/`.

### Milestone 3 — Rename the HTTP pull-request response to issue-link language

The internal contract cleanup is incomplete if the HTTP response still uses attachment language.
Update `apps/api/symphony/api/views.py` so the pull-request mutation response uses the final naming.

This plan intentionally chooses one final shape rather than a dual-shape transition period. Use this
response:

    {
      "operation": "pull_request_link",
      "status": "...",
      "issue": {"id": "...", "identifier": "..."},
      "pull_request": {
        "issue_link_id": "...",
        "title": "...",
        "url": "...",
        "subtitle": null,
        "metadata": {...}
      }
    }

This keeps the existing envelope and nested object structure so the endpoint remains recognizable,
but it removes the old attachment vocabulary entirely.

After updating the view, rewrite the API tests to assert the final response shape and remove tests
that still assert `attachment_id` or `pull_request_attachment`.

### Milestone 4 — Rewrite and delete tests so they enforce only the final contract

Open `apps/api/tests/unit/tracker/test_write_service.py` and remove every test whose sole purpose
is to prove compatibility behavior. Replace them only when the final behavior still needs direct
coverage.

Delete or rewrite tests for:

- legacy constructor keywords (`team_id`, `project_slug`)
- legacy `TrackerPullRequestResult` constructor forms
- legacy `create_attachment()` fallback in `TrackerMutationService`
- alias type `TrackerAttachment`

Open `apps/api/tests/unit/tracker/test_linear_client.py` and delete the test that asserts
`create_attachment()` aliases `create_issue_link()`.

Open `apps/api/tests/unit/api/test_tracker_writes.py` and update the expected pull-request response
to the new issue-link vocabulary.

If any fixture or fake backend still uses the old names, rewrite it to the final contract rather
than preserving adapter behavior inside tests.

### Milestone 5 — Validate and search for leftovers

Run the repository quality gates and then run focused searches that prove the compatibility layer is
gone from production code.

The final production-code searches should show no matches for:

- `TrackerAttachment`
- `create_attachment(`
- `attachment_id`
- `team_id=` in tracker write contract usage
- `project_slug=` in tracker write contract usage

`tracker.project_slug` in workflow configuration is allowed to remain. The validation searches must
therefore target the tracker write surface rather than treating every `project_slug` use as a bug.

## Concrete Steps

Run every command from the repository root.

Before any edits, capture the current compatibility footprint:

    rg -n "TrackerAttachment|create_attachment\\(|attachment_id|team_id|project_slug" apps/api/lib/tracker apps/api/symphony/api apps/api/tests/unit/tracker apps/api/tests/unit/api

While implementing Milestone 1, use narrower searches to confirm production code is converging on
the final contract:

    rg -n "attachment_id|create_attachment\\(" apps/api/lib/tracker apps/api/symphony/api
    rg -n "team_id=|project_slug=" apps/api/lib/tracker apps/api/symphony/api

After Milestones 2 through 4, run the full project checks:

    make lint
    make typecheck
    make test

Then run the final searches. These searches are deliberately split so the current Linear workflow
config field is not treated as a failure:

    rg -n "TrackerAttachment|create_attachment\\(|attachment_id" apps/api/lib/tracker apps/api/symphony/api apps/api/tests/unit
    rg -n "team_id=|project_slug=" apps/api/lib/tracker apps/api/symphony/api apps/api/tests/unit

Expected final result:

- no matches in production code under `apps/api/lib/tracker/` and `apps/api/symphony/api/`
- no compatibility-only tests remaining under `apps/api/tests/unit/tracker/` and
  `apps/api/tests/unit/api/`
- `make lint`, `make typecheck`, and `make test` all succeed

## Validation and Acceptance

This plan is complete only when all of the following are true.

Run `make lint` and expect it to finish successfully with no lint errors.

Run `make typecheck` and expect mypy to finish successfully with no type errors.

Run `make test` and expect the unit suite to pass after the compatibility tests have been rewritten
to the final contract.

Then inspect the codebase with the focused searches in `Concrete Steps` and confirm that the tracker
write compatibility vocabulary no longer exists in production code. The accepted end state is:

- `apps/api/lib/tracker/write_contract.py` contains no alias constructor logic
- `apps/api/lib/tracker/interfaces.py` contains no `TrackerAttachmentMutationBackend`
- `apps/api/lib/tracker/write_service.py` contains no `project_slug` init alias and no
  `create_attachment()` fallback
- `apps/api/lib/tracker/linear_client.py` contains no `create_attachment()` method
- `apps/api/lib/tracker/__init__.py` exports no `TrackerAttachment`
- `apps/api/symphony/api/views.py` returns `pull_request_link` and `issue_link_id`

Finally, run the tracker write API tests and inspect the expected response body in the assertions.
The pull-request response must use the final issue-link language and must no longer mention
attachments anywhere.

## Idempotence and Recovery

The edits in this plan are safe to repeat because they are subtractive simplifications rather than
data migrations. Running the searches multiple times is harmless. Re-running `make lint`,
`make typecheck`, and `make test` is harmless and expected.

If a deletion breaks a test unexpectedly, restore the final contract rather than restoring the
compatibility layer. The safe retry pattern is:

1. re-open the failing test and confirm whether it still encodes an old name
2. rewrite the test or fake backend to the final contract
3. re-run the narrow search and the affected test file
4. re-run the full project checks

Do not reintroduce a temporary alias to make one test pass. That would leave the repository in the
same mixed state this plan is trying to remove.

## Artifacts and Notes

The repository audit that motivated this plan identified the active compatibility layer in these
specific locations:

    apps/api/lib/tracker/write_contract.py
    apps/api/lib/tracker/write_service.py
    apps/api/lib/tracker/interfaces.py
    apps/api/lib/tracker/linear_client.py
    apps/api/lib/tracker/__init__.py
    apps/api/symphony/api/views.py

The compatibility-specific tests currently live in these files:

    apps/api/tests/unit/tracker/test_write_service.py
    apps/api/tests/unit/tracker/test_linear_client.py
    apps/api/tests/unit/api/test_tracker_writes.py

The final HTTP response chosen by this plan is:

    {
      "operation": "pull_request_link",
      "status": "applied",
      "issue": {"id": "issue-123", "identifier": "ENG-123"},
      "pull_request": {
        "issue_link_id": "link-123",
        "title": "PR #1",
        "url": "https://github.com/acme/symphony/pull/1",
        "subtitle": null,
        "metadata": {}
      }
    }

This example is intentionally close to the existing response so that the cleanup stays focused on
terminology and contract simplification rather than introducing a broader API redesign.

## Interfaces and Dependencies

At the end of this plan, these interfaces must exist.

In `apps/api/lib/tracker/write_contract.py`, define tracker write models with only the final field
names. In particular:

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
    class TrackerPullRequestResult:
        issue_id: str
        issue_identifier: str
        status: str
        issue_link: TrackerIssueLink

In `apps/api/lib/tracker/interfaces.py`, expose a single mutation backend protocol with
`create_issue_link(...) -> TrackerIssueLink`.

In `apps/api/lib/tracker/write_service.py`, `TrackerMutationService` must accept:

    TrackerMutationService(backend: TrackerMutationBackend, project_ref: str | None = None)

with no legacy alias parameters and no fallback to an old backend method.

Plan revision note: 2026-03-18 / Codex. Created this ExecPlan from a repository audit of the
remaining tracker write compatibility layer. The document is intentionally scoped to code-level
cleanup and omits multi-contributor rollout concerns because the active contributor asked for a
single-user code-focused plan.
