from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TypeVar

from symphony.workflow import ServiceConfig
from symphony.workflow.config import require_linear_tracker_config

from .interfaces import TrackerMutationBackend, TrackerReadClient
from .linear import LinearPayloadError
from .linear_client import (
    LinearAPIError,
    LinearAPIRequestError,
    LinearAPIStatusError,
    LinearGraphQLError,
    LinearTrackerClient,
)
from .write_contract import (
    JsonScalar,
    TrackerComment,
    TrackerGraphQLError,
    TrackerIssueLink,
    TrackerIssueReference,
    TrackerPayloadError,
    TrackerRequestFailedError,
    TrackerStatusError,
    TrackerWorkflowState,
)

_T = TypeVar("_T")


def build_tracker_read_client(config: ServiceConfig) -> TrackerReadClient:
    return _build_linear_tracker_client(config)


def build_tracker_mutation_backend(config: ServiceConfig) -> TrackerMutationBackend:
    return _build_linear_tracker_mutation_backend(config)


def _build_linear_tracker_client(config: ServiceConfig) -> LinearTrackerClient:
    return LinearTrackerClient(require_linear_tracker_config(config.tracker))


def _build_linear_tracker_mutation_backend(config: ServiceConfig) -> TrackerMutationBackend:
    return LinearTrackerMutationBackend(require_linear_tracker_config(config.tracker))


class LinearTrackerMutationBackend(LinearTrackerClient):
    @property
    def project_ref(self) -> str | None:
        return self.tracker_config.project_slug

    def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
        parent_get_issue_reference = super().get_issue_reference
        return self._call_mutation_backend(
            lambda: parent_get_issue_reference(issue_identifier)
        )

    def list_workflow_states(self) -> list[TrackerWorkflowState]:
        parent_list_workflow_states = super().list_workflow_states
        return self._call_mutation_backend(parent_list_workflow_states)

    def create_comment(self, issue_id: str, body: str) -> TrackerComment:
        parent_create_comment = super().create_comment
        return self._call_mutation_backend(lambda: parent_create_comment(issue_id, body))

    def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference:
        parent_update_issue_state = super().update_issue_state
        return self._call_mutation_backend(
            lambda: parent_update_issue_state(issue_id, state_id)
        )

    def create_issue_link(
        self,
        *,
        issue_id: str,
        title: str,
        url: str,
        subtitle: str | None,
        metadata: Mapping[str, JsonScalar],
    ) -> TrackerIssueLink:
        parent_create_issue_link = super().create_issue_link
        return self._call_mutation_backend(
            lambda: parent_create_issue_link(
                issue_id=issue_id,
                title=title,
                url=url,
                subtitle=subtitle,
                metadata=metadata,
            )
        )

    def _call_mutation_backend(self, func: Callable[[], _T]) -> _T:
        try:
            return func()
        except LinearAPIRequestError as exc:
            raise TrackerRequestFailedError(str(exc)) from exc
        except LinearAPIStatusError as exc:
            raise TrackerStatusError(str(exc)) from exc
        except LinearGraphQLError as exc:
            raise TrackerGraphQLError(str(exc)) from exc
        except LinearPayloadError as exc:
            raise TrackerPayloadError(str(exc)) from exc
        except LinearAPIError as exc:
            raise TrackerRequestFailedError(str(exc)) from exc
