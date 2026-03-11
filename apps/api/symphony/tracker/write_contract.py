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


@dataclass(slots=True, frozen=True, init=False)
class TrackerIssueReference:
    id: str
    identifier: str
    state_id: str
    state_name: str
    workflow_scope_id: str
    project_ref: str | None

    def __init__(
        self,
        id: str,
        identifier: str,
        state_id: str,
        state_name: str,
        workflow_scope_id: str | None = None,
        project_ref: str | None = None,
        *,
        team_id: str | None = None,
        project_slug: str | None = None,
    ) -> None:
        resolved_workflow_scope_id = _resolve_aliased_value(
            field_name="workflow_scope_id",
            legacy_name="team_id",
            value=workflow_scope_id,
            legacy_value=team_id,
            required=True,
        )
        resolved_project_ref = _resolve_aliased_value(
            field_name="project_ref",
            legacy_name="project_slug",
            value=project_ref,
            legacy_value=project_slug,
        )
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "identifier", identifier)
        object.__setattr__(self, "state_id", state_id)
        object.__setattr__(self, "state_name", state_name)
        object.__setattr__(self, "workflow_scope_id", resolved_workflow_scope_id)
        object.__setattr__(self, "project_ref", resolved_project_ref)

    @property
    def team_id(self) -> str:
        return self.workflow_scope_id

    @property
    def project_slug(self) -> str | None:
        return self.project_ref


@dataclass(slots=True, frozen=True, init=False)
class TrackerWorkflowState:
    id: str
    name: str
    workflow_scope_id: str

    def __init__(
        self,
        id: str,
        name: str,
        workflow_scope_id: str | None = None,
        *,
        team_id: str | None = None,
    ) -> None:
        resolved_workflow_scope_id = _resolve_aliased_value(
            field_name="workflow_scope_id",
            legacy_name="team_id",
            value=workflow_scope_id,
            legacy_value=team_id,
            required=True,
        )
        object.__setattr__(self, "id", id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "workflow_scope_id", resolved_workflow_scope_id)

    @property
    def team_id(self) -> str:
        return self.workflow_scope_id


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


TrackerAttachment = TrackerIssueLink


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


@dataclass(slots=True, frozen=True, init=False)
class TrackerPullRequestResult:
    issue_id: str
    issue_identifier: str
    status: str
    issue_link: TrackerIssueLink

    def __init__(
        self,
        issue_id: str,
        issue_identifier: str,
        status: str,
        issue_link: TrackerIssueLink | str | None = None,
        *legacy_args: str | Mapping[str, JsonScalar] | None,
        attachment_id: str | None = None,
        title: str | None = None,
        url: str | None = None,
        subtitle: str | None = None,
        metadata: Mapping[str, JsonScalar] | None = None,
    ) -> None:
        (
            resolved_issue_link_arg,
            resolved_attachment_id,
            resolved_title,
            resolved_url,
            resolved_subtitle,
            resolved_metadata,
        ) = _normalize_pull_request_result_init_args(
            issue_link=issue_link,
            legacy_args=legacy_args,
            attachment_id=attachment_id,
            title=title,
            url=url,
            subtitle=subtitle,
            metadata=metadata,
        )
        resolved_issue_link = _resolve_issue_link(
            issue_link=resolved_issue_link_arg,
            attachment_id=resolved_attachment_id,
            title=resolved_title,
            url=resolved_url,
            subtitle=resolved_subtitle,
            metadata=resolved_metadata,
        )
        object.__setattr__(self, "issue_id", issue_id)
        object.__setattr__(self, "issue_identifier", issue_identifier)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "issue_link", resolved_issue_link)

    @property
    def attachment_id(self) -> str:
        return self.issue_link.id

    @property
    def title(self) -> str:
        return self.issue_link.title

    @property
    def url(self) -> str:
        return self.issue_link.url

    @property
    def subtitle(self) -> str | None:
        return self.issue_link.subtitle

    @property
    def metadata(self) -> dict[str, JsonScalar]:
        return self.issue_link.metadata


def _resolve_aliased_value(
    *,
    field_name: str,
    legacy_name: str,
    value: str | None,
    legacy_value: str | None,
    required: bool = False,
) -> str | None:
    if value is not None and legacy_value is not None and value != legacy_value:
        raise TypeError(
            f"{field_name!r} and legacy alias {legacy_name!r} received conflicting values."
        )
    if value is not None:
        return value
    if required and legacy_value is None:
        raise TypeError(f"Missing required argument: {field_name!r}.")
    return legacy_value


def _normalize_pull_request_result_init_args(
    *,
    issue_link: TrackerIssueLink | str | None,
    legacy_args: tuple[str | Mapping[str, JsonScalar] | None, ...],
    attachment_id: str | None,
    title: str | None,
    url: str | None,
    subtitle: str | None,
    metadata: Mapping[str, JsonScalar] | None,
) -> tuple[
    TrackerIssueLink | None,
    str | None,
    str | None,
    str | None,
    str | None,
    Mapping[str, JsonScalar] | None,
]:
    if not legacy_args:
        if isinstance(issue_link, str):
            if attachment_id is not None and attachment_id != issue_link:
                raise TypeError(
                    "'attachment_id' received conflicting positional and keyword values."
                )
            return None, issue_link, title, url, subtitle, metadata
        if issue_link is not None and not isinstance(issue_link, TrackerIssueLink):
            raise TypeError(
                "'issue_link' must be a TrackerIssueLink when using the new constructor shape."
            )
        return issue_link, attachment_id, title, url, subtitle, metadata

    if len(legacy_args) != 4:
        raise TypeError(
            "Legacy positional construction requires title, url, subtitle, and metadata after "
            "the attachment_id positional argument."
        )
    if issue_link is not None and isinstance(issue_link, TrackerIssueLink):
        raise TypeError(
            "Legacy positional pull-request result construction cannot also pass 'issue_link'."
        )

    legacy_title, legacy_url, legacy_subtitle, legacy_metadata = legacy_args
    if not isinstance(issue_link, str):
        raise TypeError(
            "Legacy positional pull-request result construction requires a string attachment_id."
        )
    if not isinstance(legacy_title, str):
        raise TypeError(
            "Legacy positional pull-request result construction requires a string title."
        )
    if not isinstance(legacy_url, str):
        raise TypeError("Legacy positional pull-request result construction requires a string url.")
    if legacy_subtitle is not None and not isinstance(legacy_subtitle, str):
        raise TypeError(
            "Legacy positional pull-request result construction requires subtitle to be a string "
            "or None."
        )
    if legacy_metadata is None or not isinstance(legacy_metadata, Mapping):
        raise TypeError(
            "Legacy positional pull-request result construction requires mapping metadata."
        )

    return None, issue_link, legacy_title, legacy_url, legacy_subtitle, legacy_metadata


def _resolve_issue_link(
    *,
    issue_link: TrackerIssueLink | None,
    attachment_id: str | None,
    title: str | None,
    url: str | None,
    subtitle: str | None,
    metadata: Mapping[str, JsonScalar] | None,
) -> TrackerIssueLink:
    if issue_link is not None:
        if attachment_id is not None and attachment_id != issue_link.id:
            raise TypeError(
                "'issue_link.id' and legacy alias 'attachment_id' received conflicting values."
            )
        if title is not None and title != issue_link.title:
            raise TypeError(
                "'issue_link.title' and legacy alias 'title' received conflicting values."
            )
        if url is not None and url != issue_link.url:
            raise TypeError("'issue_link.url' and legacy alias 'url' received conflicting values.")
        if subtitle is not None and subtitle != issue_link.subtitle:
            raise TypeError(
                "'issue_link.subtitle' and legacy alias 'subtitle' received conflicting values."
            )
        if metadata is not None and dict(metadata) != issue_link.metadata:
            raise TypeError(
                "'issue_link.metadata' and legacy alias 'metadata' received conflicting values."
            )
        return issue_link

    if attachment_id is None:
        raise TypeError("Missing required argument: 'issue_link' or legacy alias 'attachment_id'.")
    if title is None:
        raise TypeError("Missing required argument: legacy alias 'title'.")
    if url is None:
        raise TypeError("Missing required argument: legacy alias 'url'.")
    if metadata is None:
        raise TypeError("Missing required argument: legacy alias 'metadata'.")
    return TrackerIssueLink(
        id=attachment_id,
        title=title,
        url=url,
        subtitle=subtitle,
        metadata=dict(metadata),
    )
