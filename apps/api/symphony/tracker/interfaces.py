from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .models import Issue
from .write_contract import (
    JsonScalar,
    TrackerComment,
    TrackerIssueLink,
    TrackerIssueReference,
    TrackerWorkflowState,
)


class TrackerReadClient(Protocol):
    def fetch_candidate_issues(self) -> list[Issue]: ...

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]: ...

    def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]: ...


class _TrackerMutationBackendBase(Protocol):
    @property
    def project_ref(self) -> str | None: ...

    def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None: ...

    def list_workflow_states(self) -> list[TrackerWorkflowState]: ...

    def create_comment(self, issue_id: str, body: str) -> TrackerComment: ...

    def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference: ...


class TrackerIssueLinkMutationBackend(_TrackerMutationBackendBase, Protocol):
    def create_issue_link(
        self,
        *,
        issue_id: str,
        title: str,
        url: str,
        subtitle: str | None,
        metadata: Mapping[str, JsonScalar],
    ) -> TrackerIssueLink: ...


class TrackerAttachmentMutationBackend(_TrackerMutationBackendBase, Protocol):
    def create_attachment(
        self,
        *,
        issue_id: str,
        title: str,
        url: str,
        subtitle: str | None,
        metadata: Mapping[str, JsonScalar],
    ) -> TrackerIssueLink: ...


type TrackerMutationBackend = TrackerIssueLinkMutationBackend | TrackerAttachmentMutationBackend
