from __future__ import annotations

import logging
import math
from collections.abc import Iterator, Mapping

import pytest
from symphony.tracker import PlaneTrackerClient
from symphony.tracker.linear_client import LinearAPIRequestError
from symphony.tracker.write_contract import (
    TrackerAttachment,
    TrackerComment,
    TrackerCommentRequest,
    TrackerGraphQLError,
    TrackerInvalidTransitionError,
    TrackerIssueLink,
    TrackerIssueNotFoundError,
    TrackerIssueReference,
    TrackerPullRequestRequest,
    TrackerPullRequestResult,
    TrackerRequestFailedError,
    TrackerTransitionRequest,
    TrackerValidationError,
    TrackerWorkflowState,
)
from symphony.tracker.write_service import (
    TrackerMutationService,
    build_tracker_mutation_service,
)
from symphony.workflow import MissingTrackerWorkspaceSlugError
from symphony.workflow.config import build_service_config
from symphony.workflow.loader import WorkflowDefinition


class RecordingLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def write_service_logs() -> Iterator[list[str]]:
    logger = logging.getLogger("symphony.tracker.write_service")
    handler = RecordingLogHandler()
    original_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(original_level)


class FakeMutationBackend:
    def __init__(self) -> None:
        self.project_ref: str | None = "symphony"
        self.issue = TrackerIssueReference(
            id="issue-123",
            identifier="SYM-123",
            state_id="state-todo",
            state_name="Todo",
            workflow_scope_id="team-1",
            project_ref=self.project_ref,
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


class LegacyAttachmentBackend:
    def __init__(self) -> None:
        self.delegate = FakeMutationBackend()

    @property
    def issue_links(self) -> list[dict[str, object]]:
        return self.delegate.issue_links

    @property
    def project_ref(self) -> str | None:
        return self.delegate.project_ref

    def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
        return self.delegate.get_issue_reference(issue_identifier)

    def list_workflow_states(self) -> list[TrackerWorkflowState]:
        return self.delegate.list_workflow_states()

    def create_comment(self, issue_id: str, body: str) -> TrackerComment:
        return self.delegate.create_comment(issue_id, body)

    def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference:
        return self.delegate.update_issue_state(issue_id, state_id)

    def create_attachment(
        self,
        *,
        issue_id: str,
        title: str,
        url: str,
        subtitle: str | None,
        metadata: Mapping[str, str | int | float | bool],
    ) -> TrackerIssueLink:
        return self.delegate.create_issue_link(
            issue_id=issue_id,
            title=title,
            url=url,
            subtitle=subtitle,
            metadata=metadata,
        )


def test_add_comment_logs_applied_mutation(write_service_logs: list[str]) -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    result = service.add_comment(TrackerCommentRequest(issue_identifier="SYM-123", body="Ship it"))
    logged = "\n".join(write_service_logs)

    assert result.status == "applied"
    assert result.comment_id == "comment-1"
    assert "event=tracker_comment_mutation" in logged
    assert "status=applied" in logged
    assert "comment_id=comment-1" in logged


def test_build_tracker_mutation_service_uses_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = FakeMutationBackend()
    backend.project_ref = "factory-project"
    config = build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                },
                "codex": {"command": "codex app-server"},
            },
            prompt_template="Prompt body",
        ),
        env={},
    )

    monkeypatch.setattr(
        "symphony.tracker.write_service.build_tracker_mutation_backend",
        lambda service_config: backend,
    )

    service = build_tracker_mutation_service(config)

    assert service.backend is backend
    assert service.project_ref == "factory-project"
    assert service.project_slug == "factory-project"


def test_tracker_contracts_accept_legacy_constructor_keywords() -> None:
    issue = TrackerIssueReference(
        id="issue-123",
        identifier="SYM-123",
        state_id="state-todo",
        state_name="Todo",
        team_id="team-1",
        project_slug="symphony",
    )
    state = TrackerWorkflowState(id="state-todo", name="Todo", team_id="team-1")

    assert issue.workflow_scope_id == "team-1"
    assert issue.team_id == "team-1"
    assert issue.project_ref == "symphony"
    assert issue.project_slug == "symphony"
    assert state.workflow_scope_id == "team-1"
    assert state.team_id == "team-1"


def test_tracker_mutation_service_accepts_legacy_project_slug_keyword() -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_slug="symphony")

    assert service.project_ref == "symphony"
    assert service.project_slug == "symphony"


def test_tracker_pull_request_result_accepts_legacy_attachment_fields() -> None:
    result = TrackerPullRequestResult(
        issue_id="issue-123",
        issue_identifier="SYM-123",
        status="applied",
        attachment_id="attachment-1",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open"},
    )

    assert result.issue_link == TrackerIssueLink(
        id="attachment-1",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open"},
    )
    assert result.attachment_id == "attachment-1"
    assert result.title == "PR #1"
    assert result.url == "https://github.com/acme/symphony/pull/1"
    assert result.subtitle == "Open"
    assert result.metadata == {"status": "open"}


def test_tracker_pull_request_result_accepts_legacy_positional_attachment_fields() -> None:
    result = TrackerPullRequestResult(
        "issue-123",
        "SYM-123",
        "applied",
        "attachment-1",
        "PR #1",
        "https://github.com/acme/symphony/pull/1",
        "Open",
        {"status": "open"},
    )

    assert result.issue_link == TrackerIssueLink(
        id="attachment-1",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open"},
    )
    assert result.attachment_id == "attachment-1"
    assert result.title == "PR #1"
    assert result.url == "https://github.com/acme/symphony/pull/1"
    assert result.subtitle == "Open"
    assert result.metadata == {"status": "open"}


def test_tracker_pull_request_result_accepts_mixed_legacy_attachment_fields() -> None:
    result = TrackerPullRequestResult(
        "issue-123",
        "SYM-123",
        "applied",
        "attachment-1",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open"},
    )

    assert result.issue_link == TrackerIssueLink(
        id="attachment-1",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open"},
    )
    assert result.attachment_id == "attachment-1"
    assert result.title == "PR #1"
    assert result.url == "https://github.com/acme/symphony/pull/1"
    assert result.subtitle == "Open"
    assert result.metadata == {"status": "open"}


def test_build_tracker_mutation_service_builds_plane_backend() -> None:
    config = build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "plane",
                    "api_base_url": "https://plane.example",
                    "api_key": "plane-token",
                    "workspace_slug": "workspace",
                    "project_id": "project-123",
                },
                "codex": {"command": "codex app-server"},
            },
            prompt_template="Prompt body",
        ),
        env={},
    )

    service = build_tracker_mutation_service(config)

    assert isinstance(service.backend, PlaneTrackerClient)
    assert service.project_ref == "project-123"


def test_build_tracker_mutation_service_surfaces_plane_field_errors() -> None:
    config = build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "plane",
                    "api_base_url": "https://plane.example",
                    "api_key": "plane-token",
                    "project_id": "project-123",
                },
                "codex": {"command": "codex app-server"},
            },
            prompt_template="Prompt body",
        ),
        env={},
    )

    with pytest.raises(
        MissingTrackerWorkspaceSlugError,
        match="tracker.workspace_slug is required when tracker.kind is 'plane'.",
    ):
        build_tracker_mutation_service(config)


def test_transition_issue_returns_noop_for_redundant_target_state(
    write_service_logs: list[str],
) -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    result = service.transition_issue(
        TrackerTransitionRequest(issue_identifier="SYM-123", target_state="Todo")
    )
    logged = "\n".join(write_service_logs)

    assert result.status == "noop"
    assert result.from_state == "Todo"
    assert result.to_state == "Todo"
    assert "event=tracker_state_transition_mutation" in logged
    assert "status=noop" in logged


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
    assert first.attachment_id == "attachment-1"
    assert second.issue_link.id == "attachment-1"
    assert second.attachment_id == "attachment-1"
    assert second.title == "PR #1"
    assert second.url == "https://github.com/acme/symphony/pull/1"
    assert second.subtitle == "Open"
    assert len(backend.issue_links) == 1
    assert second.issue_link.metadata == {
        "commit_count": 3,
        "branch_name": "feature/sym-123",
        "repository": "acme/symphony",
        "status": "open",
    }
    assert second.metadata == second.issue_link.metadata


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
    assert result.metadata == {"_branch1": "feature/sym-123"}


def test_attach_pull_request_falls_back_to_legacy_create_attachment() -> None:
    backend = LegacyAttachmentBackend()
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    result = service.attach_pull_request(
        TrackerPullRequestRequest(
            issue_identifier="SYM-123",
            url="https://github.com/acme/symphony/pull/4",
            title="PR #4",
            subtitle="Open",
            branch_name=None,
            repository=None,
            status=None,
            metadata={},
        )
    )

    assert result.issue_link.id == "attachment-1"
    assert backend.issue_links == [
        {
            "id": "attachment-1",
            "issue_id": "issue-123",
            "title": "PR #4",
            "url": "https://github.com/acme/symphony/pull/4",
            "subtitle": "Open",
            "metadata": {},
        }
    ]


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
    write_service_logs: list[str],
) -> None:
    backend = FakeMutationBackend()
    backend.fail_with = TrackerGraphQLError("Linear GraphQL response returned top-level errors.")
    service = TrackerMutationService(backend=backend, project_ref="symphony")

    with pytest.raises(TrackerGraphQLError):
        service.add_comment(TrackerCommentRequest(issue_identifier="SYM-123", body="Ship it"))
    logged = "\n".join(write_service_logs)

    assert "event=tracker_comment_mutation" in logged
    assert "status=failed" in logged
    assert "error_code=tracker_graphql_error" in logged


def test_service_rejects_missing_issue() -> None:
    service = TrackerMutationService(backend=FakeMutationBackend(), project_ref="symphony")

    with pytest.raises(TrackerIssueNotFoundError, match="configured tracker project"):
        service.add_comment(TrackerCommentRequest(issue_identifier="SYM-999", body="Ship it"))


def test_service_normalizes_linear_request_failure() -> None:
    backend = FakeMutationBackend()
    backend.fail_with = LinearAPIRequestError("Linear API request failed.")
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


def test_tracker_attachment_aliases_issue_link() -> None:
    issue_link = TrackerAttachment(
        id="attachment-1",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open"},
    )

    assert isinstance(issue_link, TrackerIssueLink)
