from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import urlparse

from symphony.observability.logging import log_event
from symphony.workflow import LinearTrackerConfig, ServiceConfig

from .factory import build_tracker_mutation_backend
from .interfaces import TrackerMutationBackend
from .linear import LinearPayloadError
from .linear_client import (
    LinearAPIError,
    LinearAPIRequestError,
    LinearAPIStatusError,
    LinearGraphQLError,
)
from .write_contract import (
    JsonScalar,
    TrackerCommentRequest,
    TrackerCommentResult,
    TrackerInvalidTransitionError,
    TrackerIssueNotFoundError,
    TrackerIssueReference,
    TrackerPullRequestRequest,
    TrackerPullRequestResult,
    TrackerRequestFailedError,
    TrackerStatusError,
    TrackerTransitionRequest,
    TrackerTransitionResult,
    TrackerValidationError,
    is_valid_json_scalar,
)
from .write_contract import (
    TrackerGraphQLError as TrackerGraphQLMutationError,
)
from .write_contract import (
    TrackerPayloadError as TrackerPayloadMutationError,
)

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


@dataclass(slots=True)
class TrackerMutationService:
    backend: TrackerMutationBackend
    project_slug: str | None

    def add_comment(self, request: TrackerCommentRequest) -> TrackerCommentResult:
        issue_identifier = request.issue_identifier.strip()
        body = request.body.strip()
        if not issue_identifier:
            raise TrackerValidationError("Field 'issue_identifier' must be a non-empty string.")
        if not body:
            raise TrackerValidationError("Field 'body' must be a non-empty string.")

        try:
            issue = self._require_issue_reference(issue_identifier)
            comment = self._call_backend(lambda: self.backend.create_comment(issue.id, body))
            result = TrackerCommentResult(
                issue_id=issue.id,
                issue_identifier=issue.identifier,
                status="applied",
                comment_id=comment.id,
                body=comment.body,
                url=comment.url,
            )
        except Exception as exc:
            self._log_comment(issue_identifier=issue_identifier, status="failed", exc=exc)
            raise

        self._log_comment(
            issue_id=result.issue_id,
            issue_identifier=result.issue_identifier,
            status=result.status,
            comment_id=result.comment_id,
        )
        return result

    def transition_issue(self, request: TrackerTransitionRequest) -> TrackerTransitionResult:
        issue_identifier = request.issue_identifier.strip()
        target_state = request.target_state.strip()
        if not issue_identifier:
            raise TrackerValidationError("Field 'issue_identifier' must be a non-empty string.")
        if not target_state:
            raise TrackerValidationError("Field 'target_state' must be a non-empty string.")

        try:
            issue = self._require_issue_reference(issue_identifier)
            if issue.state_name == target_state:
                result = TrackerTransitionResult(
                    issue_id=issue.id,
                    issue_identifier=issue.identifier,
                    status="noop",
                    from_state=issue.state_name,
                    to_state=target_state,
                )
            else:
                target_state_id = self._resolve_target_state_id(
                    issue=issue, target_state=target_state
                )
                updated_issue = self._call_backend(
                    lambda: self.backend.update_issue_state(issue.id, target_state_id)
                )
                result = TrackerTransitionResult(
                    issue_id=updated_issue.id,
                    issue_identifier=updated_issue.identifier,
                    status="applied",
                    from_state=issue.state_name,
                    to_state=updated_issue.state_name,
                )
        except Exception as exc:
            self._log_transition(
                issue_identifier=issue_identifier,
                target_state=target_state,
                status="failed",
                exc=exc,
            )
            raise

        self._log_transition(
            issue_id=result.issue_id,
            issue_identifier=result.issue_identifier,
            target_state=result.to_state,
            from_state=result.from_state,
            status=result.status,
        )
        return result

    def attach_pull_request(self, request: TrackerPullRequestRequest) -> TrackerPullRequestResult:
        issue_identifier = request.issue_identifier.strip()
        title = request.title.strip()
        url = request.url.strip()
        subtitle = request.subtitle.strip() if request.subtitle is not None else None
        if subtitle == "":
            subtitle = None
        if not issue_identifier:
            raise TrackerValidationError("Field 'issue_identifier' must be a non-empty string.")
        if not title:
            raise TrackerValidationError("Field 'title' must be a non-empty string.")
        if not self._is_valid_http_url(url):
            raise TrackerValidationError("Field 'url' must be an absolute http or https URL.")

        metadata = self._normalize_pull_request_metadata(request)

        try:
            issue = self._require_issue_reference(issue_identifier)
            attachment = self._call_backend(
                lambda: self.backend.create_attachment(
                    issue_id=issue.id,
                    title=title,
                    url=url,
                    subtitle=subtitle,
                    metadata=metadata,
                )
            )
            result = TrackerPullRequestResult(
                issue_id=issue.id,
                issue_identifier=issue.identifier,
                status="applied",
                attachment_id=attachment.id,
                title=attachment.title,
                url=attachment.url,
                subtitle=attachment.subtitle,
                metadata=attachment.metadata,
            )
        except Exception as exc:
            self._log_pull_request(
                issue_identifier=issue_identifier,
                url=url,
                status="failed",
                exc=exc,
            )
            raise

        self._log_pull_request(
            issue_id=result.issue_id,
            issue_identifier=result.issue_identifier,
            url=result.url,
            status=result.status,
            attachment_id=result.attachment_id,
        )
        return result

    def _require_issue_reference(self, issue_identifier: str) -> TrackerIssueReference:
        issue = self._call_backend(lambda: self.backend.get_issue_reference(issue_identifier))
        if issue is None:
            raise TrackerIssueNotFoundError(
                f"Issue {issue_identifier!r} was not found in the configured tracker project."
            )
        if self.project_slug and issue.project_slug != self.project_slug:
            raise TrackerIssueNotFoundError(
                f"Issue {issue_identifier!r} was not found in the configured tracker project."
            )
        return issue

    def _resolve_target_state_id(
        self,
        *,
        issue: TrackerIssueReference,
        target_state: str,
    ) -> str:
        workflow_states = self._call_backend(self.backend.list_workflow_states)
        for state in workflow_states:
            if state.team_id == issue.team_id and state.name == target_state:
                return state.id
        raise TrackerInvalidTransitionError(
            f"State {target_state!r} is not a valid workflow state for {issue.identifier!r}."
        )

    def _normalize_pull_request_metadata(
        self,
        request: TrackerPullRequestRequest,
    ) -> dict[str, JsonScalar]:
        metadata: dict[str, JsonScalar] = {}
        for key, value in request.metadata.items():
            normalized_key = key.strip()
            if not normalized_key:
                raise TrackerValidationError("Metadata keys must be non-empty strings.")
            if not _is_valid_metadata_key(normalized_key):
                raise TrackerValidationError(
                    f"Metadata key {normalized_key!r} must start with a letter or underscore "
                    "and contain only letters, digits, or underscores."
                )
            if not is_valid_json_scalar(value):
                raise TrackerValidationError(
                    f"Metadata value for {normalized_key!r} must be a string, finite number, "
                    "or boolean."
                )
            metadata[normalized_key] = value

        if request.branch_name is not None and request.branch_name.strip():
            metadata["branch_name"] = request.branch_name.strip()
        if request.repository is not None and request.repository.strip():
            metadata["repository"] = request.repository.strip()
        if request.status is not None and request.status.strip():
            metadata["status"] = request.status.strip()
        return metadata

    def _call_backend(self, func: Callable[[], _T]) -> _T:
        try:
            return func()
        except (TrackerValidationError, TrackerIssueNotFoundError, TrackerInvalidTransitionError):
            raise
        except LinearAPIRequestError as exc:
            raise TrackerRequestFailedError(str(exc)) from exc
        except LinearAPIStatusError as exc:
            raise TrackerStatusError(str(exc)) from exc
        except LinearGraphQLError as exc:
            raise TrackerGraphQLMutationError(str(exc)) from exc
        except LinearPayloadError as exc:
            raise TrackerPayloadMutationError(str(exc)) from exc
        except LinearAPIError as exc:
            raise TrackerRequestFailedError(str(exc)) from exc

    def _log_comment(
        self,
        *,
        issue_identifier: str,
        status: str,
        issue_id: str | None = None,
        comment_id: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        fields = {
            "issue_id": issue_id,
            "issue_identifier": issue_identifier,
            "status": status,
            "comment_id": comment_id,
        }
        if exc is not None:
            fields["error_code"] = getattr(exc, "code", exc.__class__.__name__)
            fields["error_message"] = str(exc)
        log_event(
            logger,
            logging.INFO if exc is None else logging.WARNING,
            "tracker_comment_mutation",
            fields=fields,
        )

    def _log_transition(
        self,
        *,
        issue_identifier: str,
        target_state: str,
        status: str,
        issue_id: str | None = None,
        from_state: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        fields = {
            "issue_id": issue_id,
            "issue_identifier": issue_identifier,
            "target_state": target_state,
            "from_state": from_state,
            "status": status,
        }
        if exc is not None:
            fields["error_code"] = getattr(exc, "code", exc.__class__.__name__)
            fields["error_message"] = str(exc)
        log_event(
            logger,
            logging.INFO if exc is None else logging.WARNING,
            "tracker_state_transition_mutation",
            fields=fields,
        )

    def _log_pull_request(
        self,
        *,
        issue_identifier: str,
        url: str,
        status: str,
        issue_id: str | None = None,
        attachment_id: str | None = None,
        exc: Exception | None = None,
    ) -> None:
        fields = {
            "issue_id": issue_id,
            "issue_identifier": issue_identifier,
            "url": url,
            "status": status,
            "attachment_id": attachment_id,
        }
        if exc is not None:
            fields["error_code"] = getattr(exc, "code", exc.__class__.__name__)
            fields["error_message"] = str(exc)
        log_event(
            logger,
            logging.INFO if exc is None else logging.WARNING,
            "tracker_pull_request_mutation",
            fields=fields,
        )

    @staticmethod
    def _is_valid_http_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def build_tracker_mutation_service(config: ServiceConfig) -> TrackerMutationService:
    tracker = config.tracker
    if not isinstance(tracker, LinearTrackerConfig):
        raise ValueError(f"Unsupported tracker kind for mutation service: {tracker.kind!r}.")

    return TrackerMutationService(
        backend=build_tracker_mutation_backend(config),
        project_slug=tracker.project_slug,
    )


def _is_valid_metadata_key(value: str) -> bool:
    return re.fullmatch(r"[_A-Za-z][_0-9A-Za-z]*", value) is not None
