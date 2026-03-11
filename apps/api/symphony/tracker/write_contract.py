from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeGuard

JsonScalar = str | int | float | bool


def is_valid_json_scalar(value: object) -> TypeGuard[JsonScalar]:
    if isinstance(value, float):
        return math.isfinite(value)
    return isinstance(value, str | int | bool)


class TrackerMutationError(Exception):
    code = "tracker_mutation_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TrackerValidationError(TrackerMutationError):
    code = "invalid_request"


class TrackerIssueNotFoundError(TrackerMutationError):
    code = "issue_not_found"


class TrackerInvalidTransitionError(TrackerMutationError):
    code = "invalid_state_transition"


class TrackerRequestFailedError(TrackerMutationError):
    code = "tracker_request_failed"


class TrackerStatusError(TrackerMutationError):
    code = "tracker_http_error"


class TrackerGraphQLError(TrackerMutationError):
    code = "tracker_graphql_error"


class TrackerPayloadError(TrackerMutationError):
    code = "tracker_payload_error"


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
class TrackerComment:
    id: str
    body: str
    url: str | None


@dataclass(slots=True, frozen=True)
class TrackerIssueLink:
    id: str
    title: str
    url: str
    subtitle: str | None
    metadata: dict[str, JsonScalar]


@dataclass(slots=True, frozen=True)
class TrackerCommentRequest:
    issue_identifier: str
    body: str


@dataclass(slots=True, frozen=True)
class TrackerCommentResult:
    issue_id: str
    issue_identifier: str
    status: str
    comment_id: str
    body: str
    url: str | None


@dataclass(slots=True, frozen=True)
class TrackerTransitionRequest:
    issue_identifier: str
    target_state: str


@dataclass(slots=True, frozen=True)
class TrackerTransitionResult:
    issue_id: str
    issue_identifier: str
    status: str
    from_state: str
    to_state: str


@dataclass(slots=True, frozen=True)
class TrackerPullRequestRequest:
    issue_identifier: str
    url: str
    title: str
    subtitle: str | None
    branch_name: str | None
    repository: str | None
    status: str | None
    metadata: Mapping[str, JsonScalar]


@dataclass(slots=True, frozen=True)
class TrackerPullRequestResult:
    issue_id: str
    issue_identifier: str
    status: str
    issue_link: TrackerIssueLink
