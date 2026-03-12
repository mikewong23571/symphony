# Tracker Module

Owns the tracker-facing boundary: normalized issue models, tracker protocols, factory entry
points, and the Symphony-owned tracker mutation contract.

## Main entry points

- `factory.py`: caller-facing constructors for tracker read and mutation backends. Keep tracker-kind
  branching here instead of teaching orchestrator or API callers about specific adapters. Today the
  runtime factories still return Linear-backed implementations, while preserving typed config
  errors when a Plane config reaches an unwired path.
- `interfaces.py`: tracker-neutral protocols (`TrackerReadClient`, `TrackerMutationBackend`, and
  the link/attachment capability variants) that higher layers should code against.
- `write_contract.py`: neutral request/result dataclasses and stable mutation error codes used by
  the backend-owned tracker write surface.
- `write_service.py`: tracker mutation orchestration, validation, no-op handling, and structured
  mutation logs.
- `models.py`: normalized issue and blocker dataclasses shared by all tracker adapters.

## Per-tracker adapter files

- `linear.py`: Linear payload normalization into the shared `Issue` model.
- `linear_client.py`: Linear GraphQL transport, pagination helpers, read operations, and the
  current mutation backend implementation used by the factory.
- `plane.py`: Plane payload normalization into the shared `Issue` model.
- `plane_client.py`: Plane REST transport and issue-page helpers built around `api_base_url`,
  `workspace_slug`, `project_id`, and `X-API-Key`.

## Design notes

- Tracker-specific transport details belong in the adapter files; the orchestrator and API layers
  should consume `TrackerReadClient` / `TrackerMutationBackend`.
- New tracker kinds should add their own normalizer and transport file pair, then plug selection
  into `factory.py` rather than branching in callers.
- Linear-only features such as raw GraphQL access belong in Linear-specific surfaces, not in the
  generic tracker protocols.
- Issue lookup resolves the human `SYM-123` style identifier into a normalized tracker issue
  reference before mutating, and state transitions flow back through the backend using the resolved
  tracker issue id.
- Pull-request link safety depends on the backend link/attachment contract being URL-idempotent for
  a given issue, so repeated requests with the same issue/url pair update the tracked artifact
  instead of forcing API callers to invent duplicate detection.
