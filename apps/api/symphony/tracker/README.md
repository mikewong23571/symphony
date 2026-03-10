# Tracker Module

Owns issue tracker adapters, normalized issue models, and the Symphony-owned tracker mutation
contract.

Current write surfaces:
- `write_contract.py`: explicit request/result dataclasses and stable mutation error codes
- `write_service.py`: tracker mutation orchestration, validation, no-op handling, and structured
  mutation logs
- `linear_client.py`: Linear-backed read and write transport implementation used by the service

Write-path notes:
- issue lookup resolves the human `SYM-123` style identifier into a normalized tracker issue
  reference before mutating, and state transitions are sent back through the backend using the
  resolved tracker issue id
- pull-request attachment safety relies on the backend attachment contract being URL-idempotent for
  a given issue, so repeated requests with the same issue/url pair update the tracked attachment
  instead of requiring the API layer to invent its own duplicate state
