from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest
from django.test import Client
from symphony.api.views import _build_tracker_mutation_service
from symphony.tracker.write_contract import (
    TrackerComment,
    TrackerCommentRequest,
    TrackerCommentResult,
    TrackerInvalidTransitionError,
    TrackerIssueLink,
    TrackerIssueReference,
    TrackerPullRequestRequest,
    TrackerPullRequestResult,
    TrackerTransitionRequest,
    TrackerTransitionResult,
    TrackerWorkflowState,
)
from symphony.tracker.write_service import TrackerMutationService


class FakeTrackerMutationService:
    def __init__(self) -> None:
        pass

    def add_comment(self, request: TrackerCommentRequest) -> TrackerCommentResult:
        return TrackerCommentResult(
            issue_id="issue-123",
            issue_identifier=request.issue_identifier,
            status="applied",
            comment_id="comment-1",
            body=request.body,
            url="https://linear.app/comment-1",
        )

    def transition_issue(self, request: TrackerTransitionRequest) -> TrackerTransitionResult:
        if request.target_state == "Todo":
            return TrackerTransitionResult(
                issue_id="issue-123",
                issue_identifier=request.issue_identifier,
                status="noop",
                from_state="Todo",
                to_state="Todo",
            )
        if request.target_state == "Bad State":
            raise TrackerInvalidTransitionError(
                f"State {request.target_state!r} is not a valid workflow state."
            )
        return TrackerTransitionResult(
            issue_id="issue-123",
            issue_identifier=request.issue_identifier,
            status="applied",
            from_state="Todo",
            to_state=request.target_state,
        )

    def attach_pull_request(self, request: TrackerPullRequestRequest) -> TrackerPullRequestResult:
        return TrackerPullRequestResult(
            issue_id="issue-123",
            issue_identifier=request.issue_identifier,
            status="applied",
            issue_link=TrackerIssueLink(
                id="attachment-1",
                title=request.title,
                url=request.url,
                subtitle=request.subtitle,
                metadata=dict(request.metadata),
            ),
        )


@pytest.fixture
def fake_service(monkeypatch: pytest.MonkeyPatch) -> FakeTrackerMutationService:
    service = FakeTrackerMutationService()
    monkeypatch.setattr("symphony.api.views._build_tracker_mutation_service", lambda: service)
    return service


def test_tracker_comment_endpoint_accepts_post_and_returns_explicit_payload(
    fake_service: FakeTrackerMutationService,
) -> None:
    response = Client().post(
        "/api/v1/tracker/issues/SYM-123/comments",
        data=json.dumps({"body": "Ready for review"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "operation": "comment",
        "status": "applied",
        "issue": {"id": "issue-123", "identifier": "SYM-123"},
        "comment": {
            "id": "comment-1",
            "body": "Ready for review",
            "url": "https://linear.app/comment-1",
        },
    }


def test_tracker_comment_endpoint_rejects_invalid_json() -> None:
    response = Client().post(
        "/api/v1/tracker/issues/SYM-123/comments",
        data="{",
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": "Request body must be valid JSON.",
        }
    }


def test_tracker_transition_endpoint_returns_noop_for_redundant_target_state(
    fake_service: FakeTrackerMutationService,
) -> None:
    response = Client().post(
        "/api/v1/tracker/issues/SYM-123/transition",
        data=json.dumps({"target_state": "Todo"}),
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json() == {
        "operation": "state_transition",
        "status": "noop",
        "issue": {"id": "issue-123", "identifier": "SYM-123"},
        "transition": {"from_state": "Todo", "to_state": "Todo"},
    }


def test_tracker_transition_endpoint_rejects_invalid_transition(
    fake_service: FakeTrackerMutationService,
) -> None:
    response = Client().post(
        "/api/v1/tracker/issues/SYM-123/transition",
        data=json.dumps({"target_state": "Bad State"}),
        content_type="application/json",
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": {
            "code": "invalid_state_transition",
            "message": "State 'Bad State' is not a valid workflow state.",
        }
    }


def test_tracker_pull_request_endpoint_handles_repeated_posts_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IdempotentIssueLinkBackend:
        def __init__(self) -> None:
            self.issue_links: dict[tuple[str, str], TrackerIssueLink] = {}

        def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
            return TrackerIssueReference(
                id="issue-123",
                identifier=issue_identifier,
                state_id="state-todo",
                state_name="Todo",
                workflow_scope_id="team-1",
                project_ref="symphony",
            )

        def list_workflow_states(self) -> list[TrackerWorkflowState]:
            return []

        def create_comment(self, issue_id: str, body: str) -> TrackerComment:
            raise AssertionError("Comment writes are not used in this test.")

        def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference:
            raise AssertionError("State transitions are not used in this test.")

        def create_issue_link(
            self,
            *,
            issue_id: str,
            title: str,
            url: str,
            subtitle: str | None,
            metadata: Mapping[str, str | int | float | bool],
        ) -> TrackerIssueLink:
            key = (issue_id, url)
            issue_link = self.issue_links.get(key)
            if issue_link is None:
                issue_link = TrackerIssueLink(
                    id="attachment-1",
                    title=title,
                    url=url,
                    subtitle=subtitle,
                    metadata=dict(metadata),
                )
            else:
                issue_link = TrackerIssueLink(
                    id=issue_link.id,
                    title=title,
                    url=url,
                    subtitle=subtitle,
                    metadata=dict(metadata),
                )
            self.issue_links[key] = issue_link
            return issue_link

    backend = IdempotentIssueLinkBackend()
    monkeypatch.setattr(
        "symphony.api.views._build_tracker_mutation_service",
        lambda: TrackerMutationService(backend=backend, project_ref="symphony"),
    )

    payload = {
        "title": "PR #1",
        "url": "https://github.com/acme/symphony/pull/1",
        "subtitle": "Open",
        "metadata": {"commit_count": 3},
    }

    first_response = Client().post(
        "/api/v1/tracker/issues/SYM-123/pull-request",
        data=json.dumps(payload),
        content_type="application/json",
    )
    second_response = Client().post(
        "/api/v1/tracker/issues/SYM-123/pull-request",
        data=json.dumps(payload),
        content_type="application/json",
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == second_response.json()
    assert len(backend.issue_links) == 1


def test_tracker_pull_request_endpoint_rejects_get() -> None:
    response = Client().get("/api/v1/tracker/issues/SYM-123/pull-request")

    assert response.status_code == 405
    assert response["Allow"] == "POST"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": (
                "Method 'GET' is not allowed for /api/v1/tracker/issues/SYM-123/pull-request."
            ),
        }
    }


def test_tracker_pull_request_endpoint_rejects_non_finite_metadata_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class IssueLinkBackend:
        def __init__(self) -> None:
            self.issue_link_calls = 0

        def get_issue_reference(self, issue_identifier: str) -> TrackerIssueReference | None:
            return TrackerIssueReference(
                id="issue-123",
                identifier=issue_identifier,
                state_id="state-todo",
                state_name="Todo",
                workflow_scope_id="team-1",
                project_ref="symphony",
            )

        def list_workflow_states(self) -> list[TrackerWorkflowState]:
            return []

        def create_comment(self, issue_id: str, body: str) -> TrackerComment:
            raise AssertionError("Comment writes are not used in this test.")

        def update_issue_state(self, issue_id: str, state_id: str) -> TrackerIssueReference:
            raise AssertionError("State transitions are not used in this test.")

        def create_issue_link(
            self,
            *,
            issue_id: str,
            title: str,
            url: str,
            subtitle: str | None,
            metadata: Mapping[str, str | int | float | bool],
        ) -> TrackerIssueLink:
            self.issue_link_calls += 1
            return TrackerIssueLink(
                id="attachment-1",
                title=title,
                url=url,
                subtitle=subtitle,
                metadata=dict(metadata),
            )

    backend = IssueLinkBackend()
    monkeypatch.setattr(
        "symphony.api.views._build_tracker_mutation_service",
        lambda: TrackerMutationService(backend=backend, project_ref="symphony"),
    )

    response = Client().post(
        "/api/v1/tracker/issues/SYM-123/pull-request",
        data='{"title":"PR #1","url":"https://github.com/acme/symphony/pull/1","metadata":{"build_time_seconds":Infinity}}',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_request",
            "message": (
                "Metadata value for 'build_time_seconds' must be a string, finite number, "
                "or boolean."
            ),
        }
    }
    assert backend.issue_link_calls == 0


def test_build_tracker_mutation_service_uses_env_workflow_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_path = tmp_path / "runtime" / "WORKFLOW.md"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(
        """---
tracker:
  kind: linear
  api_key: env-linear-token
  project_slug: runtime-project
---
# Prompt body
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("SYMPHONY_WORKFLOW_PATH", str(workflow_path))
    _build_tracker_mutation_service.cache_clear()

    service = _build_tracker_mutation_service()

    assert service.project_ref == "runtime-project"
    _build_tracker_mutation_service.cache_clear()
