from __future__ import annotations

import logging
import math
from collections.abc import Mapping

import pytest
from symphony.tracker.write_contract import (
    TrackerComment,
    TrackerCommentRequest,
    TrackerGraphQLError,
    TrackerInvalidTransitionError,
    TrackerIssueLink,
    TrackerIssueNotFoundError,
    TrackerIssueReference,
    TrackerPullRequestRequest,
    TrackerRequestFailedError,
    TrackerTransitionRequest,
    TrackerValidationError,
    TrackerWorkflowState,
)
from symphony.tracker.write_service import TrackerMutationService


class FakeMutationBackend:
    def __init__(self) -> None:
        self.issue = TrackerIssueReference(
            id="issue-123",
            identifier="SYM-123",
            state_id="state-todo",
            state_name="Todo",
            workflow_scope_id="team-1",
            project_ref="symphony",
        )
        self.workflow_states = [
            TrackerWorkflowState(id="state-todo", name="Todo", workflow_scope_id="team-1"),
            TrackerWorkflowState(
                id="state-progress",
                name="In Progress",
                workflow_scope_id="team-1",
            ),
        ]
        self.comments: list[tuple[str, str]] = []
        self.issue_links: list[dict[str, object]] = []
        self.state_updates: list[tuple[str, str]] = []
        self.fail_with: Exception | None = None

    def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
        if issue_identifier == self.issue.identifier:
            return self.issue
        return None

    def list_workflow_states(self) -> list[TrackerWorkflowState]:
        return list(self.workflow_states)

    def create_comment(self, issue_id: str, body: str) -> TrackerComment:
        if self.fail_with is not None:
            raise self.fail_with
        self.comments.append((issue_id, body))
        return TrackerComment(id="comment-1", body=body, url="https://linear.app/comment-1")

    def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference:
        if self.fail_with is not None:
            raise self.fail_with
        self.state_updates.append((issue_id, state_id))
        matching_state = next(state for state in self.workflow_states if state.id == state_id)
        self.issue = TrackerIssueReference(
            id=self.issue.id,
            identifier=self.issue.identifier,
            state_id=matching_state.id,
            state_name=matching_state.name,
            workflow_scope_id=self.issue.workflow_scope_id,
            project_ref=self.issue.project_ref,
        )
        return self.issue

    def create_issue_link(
        self,
        *,
        issue_id: str,
        title: str,
        url: str,
        subtitle: str | None,
        metadata: Mapping[str, str | int | float | bool],
    ) -> TrackerIssueLink:
        if self.fail_with is not None:
            raise self.fail_with
        issue_link_id = "attachment-1"
        for existing in self.issue_links:
            if existing["url"] == url:
                issue_link_id = str(existing["id"])
                existing.update(
                    {
                        "title": title,
                        "subtitle": subtitle,
                        "metadata": dict(metadata),
                    }
                )
                break
        else:
            self.issue_links.append(
                {
                    "id": issue_link_id,
                    "issue_id": issue_id,
                    "title": title,
                    "url": url,
                    "subtitle": subtitle,
                    "metadata": dict(metadata),
                }
            )
        return TrackerIssueLink(
            id=issue_link_id,
            title=title,
            url=url,
            subtitle=subtitle,
            metadata=dict(metadata),
        )


def test_add_comment_logs_applied_mutation(caplog: pytest.LogCaptureFixture) -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    with caplog.at_level(logging.INFO):
        result = service.add_comment(
            TrackerCommentRequest(issue_identifier="SYM-123", body="Ship it")
        )

    assert result.status == "applied"
    assert result.comment_id == "comment-1"
    assert "event=tracker_comment_mutation" in caplog.text
    assert "status=applied" in caplog.text
    assert "comment_id=comment-1" in caplog.text


def test_transition_issue_returns_noop_for_redundant_target_state(
    caplog: pytest.LogCaptureFixture,
) -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    with caplog.at_level(logging.INFO):
        result = service.transition_issue(
            TrackerTransitionRequest(issue_identifier="SYM-123", target_state="Todo")
        )

    assert result.status == "noop"
    assert result.from_state == "Todo"
    assert result.to_state == "Todo"
    assert "event=tracker_state_transition_mutation" in caplog.text
    assert "status=noop" in caplog.text


def test_transition_issue_mutates_by_internal_issue_id() -> None:
    backend = FakeMutationBackend()
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    result = service.transition_issue(
        TrackerTransitionRequest(issue_identifier="SYM-123", target_state="In Progress")
    )

    assert result.status == "applied"
    assert backend.state_updates == [("issue-123", "state-progress")]


def test_transition_issue_rejects_unknown_target_state() -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    with pytest.raises(TrackerInvalidTransitionError, match="not a valid workflow state"):
        service.transition_issue(
            TrackerTransitionRequest(issue_identifier="SYM-123", target_state="Done")
        )


def test_attach_pull_request_normalizes_metadata_and_supports_repeated_urls() -> None:
    backend = FakeMutationBackend()
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    first = service.attach_pull_request(
        TrackerPullRequestRequest(
            issue_identifier="SYM-123",
            url="https://github.com/acme/symphony/pull/1",
            title="PR #1",
            subtitle="Open",
            branch_name="feature/sym-123",
            repository="acme/symphony",
            status="open",
            metadata={"commit_count": 3},
        )
    )
    second = service.attach_pull_request(
        TrackerPullRequestRequest(
            issue_identifier="SYM-123",
            url="https://github.com/acme/symphony/pull/1",
            title="PR #1",
            subtitle="Open",
            branch_name="feature/sym-123",
            repository="acme/symphony",
            status="open",
            metadata={"commit_count": 3},
        )
    )

    assert first.issue_link.id == "attachment-1"
    assert second.issue_link.id == "attachment-1"
    assert len(backend.issue_links) == 1
    assert second.issue_link.metadata == {
        "commit_count": 3,
        "branch_name": "feature/sym-123",
        "repository": "acme/symphony",
        "status": "open",
    }


def test_attach_pull_request_rejects_digit_prefixed_metadata_keys_before_backend_call() -> None:
    backend = FakeMutationBackend()
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    with pytest.raises(TrackerValidationError, match="must start with a letter or underscore"):
        service.attach_pull_request(
            TrackerPullRequestRequest(
                issue_identifier="SYM-123",
                url="https://github.com/acme/symphony/pull/1",
                title="PR #1",
                subtitle="Open",
                branch_name=None,
                repository=None,
                status=None,
                metadata={"1branch": "feature/sym-123"},
            )
        )

    assert backend.issue_links == []


def test_attach_pull_request_accepts_valid_metadata_keys() -> None:
    backend = FakeMutationBackend()
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    result = service.attach_pull_request(
        TrackerPullRequestRequest(
            issue_identifier="SYM-123",
            url="https://github.com/acme/symphony/pull/2",
            title="PR #2",
            subtitle=None,
            branch_name=None,
            repository=None,
            status=None,
            metadata={"_branch1": "feature/sym-123"},
        )
    )

    assert result.issue_link.metadata == {"_branch1": "feature/sym-123"}


def test_attach_pull_request_rejects_non_finite_metadata_numbers_before_backend_call() -> None:
    backend = FakeMutationBackend()
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    with pytest.raises(TrackerValidationError, match="must be a string, finite number"):
        service.attach_pull_request(
            TrackerPullRequestRequest(
                issue_identifier="SYM-123",
                url="https://github.com/acme/symphony/pull/3",
                title="PR #3",
                subtitle=None,
                branch_name=None,
                repository=None,
                status=None,
                metadata={"build_time_seconds": math.inf},
            )
        )

    assert backend.issue_links == []


def test_service_normalizes_backend_request_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    backend = FakeMutationBackend()
    backend.fail_with = TrackerGraphQLError("Linear GraphQL response returned top-level errors.")
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    with caplog.at_level(logging.WARNING):
        with pytest.raises(TrackerGraphQLError):
            service.add_comment(TrackerCommentRequest(issue_identifier="SYM-123", body="Ship it"))

    assert "event=tracker_comment_mutation" in caplog.text
    assert "status=failed" in caplog.text
    assert "error_code=tracker_graphql_error" in caplog.text


def test_service_rejects_missing_issue() -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    with pytest.raises(TrackerIssueNotFoundError, match="configured tracker project"):
        service.add_comment(TrackerCommentRequest(issue_identifier="SYM-999", body="Ship it"))


def test_service_normalizes_linear_request_failure() -> None:
    backend = FakeMutationBackend()
    backend.fail_with = TrackerRequestFailedError("Linear API request failed.")
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    with pytest.raises(TrackerRequestFailedError):
        service.attach_pull_request(
            TrackerPullRequestRequest(
                issue_identifier="SYM-123",
                url="https://github.com/acme/symphony/pull/1",
                title="PR #1",
                subtitle=None,
                branch_name=None,
                repository=None,
                status=None,
                metadata={},
            )
        )
