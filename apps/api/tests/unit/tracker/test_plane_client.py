from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from symphony.tracker import (
    IssueBlocker,
    PlaneAPIRequestError,
    PlaneAPIStatusError,
    PlanePayloadError,
    PlaneTrackerClient,
    PlaneTransportResponse,
    build_plane_issue_collection_url,
)
from symphony.tracker.plane_client import DEFAULT_PLANE_PAGE_SIZE
from symphony.workflow.config import PlaneTrackerConfig


class RecordingTransport:
    def __init__(
        self,
        *,
        response: PlaneTransportResponse | None = None,
        responses: list[PlaneTransportResponse] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.responses = responses or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        query_params: Mapping[str, object],
        json_body: Mapping[str, object] | None,
        timeout_ms: int,
    ) -> PlaneTransportResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(headers),
                "query_params": dict(query_params),
                "json_body": None if json_body is None else dict(json_body),
                "timeout_ms": timeout_ms,
            }
        )

        if self.error is not None:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        if self.response is None:
            raise AssertionError("Test transport expected a configured response.")
        return self.response


def make_tracker_config() -> PlaneTrackerConfig:
    return PlaneTrackerConfig(
        kind="plane",
        api_base_url="https://plane.example/self-hosted",
        api_key="plane-token",
        workspace_slug="engineering",
        project_id="project-123",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done",),
    )


def make_issue_payload(
    *,
    issue_id: str,
    sequence_id: int,
    name: str,
    state_id: str,
    state_name: str,
    project_id: str = "project-123",
    project_identifier: str = "ENG",
    blocked_by_issues: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": issue_id,
        "sequence_id": sequence_id,
        "name": name,
        "description_stripped": f"Description for {name}",
        "priority": "high",
        "state": {"id": state_id, "name": state_name},
        "project": {"id": project_id, "identifier": project_identifier},
        "labels": [{"name": "Backend"}],
        "created_at": "2026-03-01T12:00:00Z",
        "updated_at": "2026-03-02T12:00:00Z",
    }
    if blocked_by_issues is not None:
        payload["blocked_by_issues"] = blocked_by_issues
    return payload


def make_state_payload(
    *,
    state_id: str,
    state_name: str,
    project_id: str = "project-123",
) -> dict[str, object]:
    return {
        "id": state_id,
        "name": state_name,
        "project": {"id": project_id},
    }


def test_build_plane_issue_collection_url_preserves_base_subpath_and_quotes_segments() -> None:
    config = PlaneTrackerConfig(
        kind="plane",
        api_base_url="https://plane.example/root",
        api_key="plane-token",
        workspace_slug="engineering team",
        project_id="project/123",
        active_states=("Todo",),
        terminal_states=("Done",),
    )

    url = build_plane_issue_collection_url(config)

    assert (
        url
        == "https://plane.example/root/api/v1/workspaces/engineering%20team/projects/project%2F123/issues/"
    )


def test_fetch_issue_page_sends_auth_headers_and_parses_next_offset() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "count": 1,
                    "next": (
                        "https://plane.example/self-hosted/api/v1/workspaces/engineering/"
                        "projects/project-123/issues/?limit=50&offset=50"
                    ),
                    "results": [
                        {
                            "id": "issue-1",
                            "name": "Dispatch candidate",
                        }
                    ],
                }
            ),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    page = client.fetch_issue_page(
        query_params={
            "expand": ["state", "labels", "project"],
            "state": ["state-1", "state-2"],
        }
    )

    assert page.count == 1
    assert page.next_cursor is None
    assert page.next_offset == 50
    assert page.items == ({"id": "issue-1", "name": "Dispatch candidate"},)
    assert len(transport.calls) == 1
    assert (
        transport.calls[0]["url"]
        == "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/project-123/issues/"
    )
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["headers"] == {
        "Accept": "application/json",
        "X-API-Key": "plane-token",
    }
    assert transport.calls[0]["query_params"] == {
        "limit": DEFAULT_PLANE_PAGE_SIZE,
        "offset": 0,
        "expand": ["state", "labels", "project"],
        "state": ["state-1", "state-2"],
    }
    assert transport.calls[0]["json_body"] is None
    assert transport.calls[0]["timeout_ms"] == 30_000


def test_fetch_issue_page_allows_final_page_without_next_link() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(
                status_code=200,
                body=json.dumps({"count": 1, "next": None, "results": [{"id": "issue-1"}]}),
            )
        ),
    )

    page = client.fetch_issue_page()

    assert page.next_cursor is None
    assert page.next_offset is None


def test_fetch_issue_page_maps_transport_failures_to_typed_error() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(error=OSError("network down")),
    )

    with pytest.raises(PlaneAPIRequestError, match="Plane API request failed."):
        client.fetch_issue_page()


def test_fetch_issue_page_maps_non_2xx_status_to_typed_error() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(status_code=503, body='{"error":"bad gateway"}')
        ),
    )

    with pytest.raises(PlaneAPIStatusError, match="HTTP 503"):
        client.fetch_issue_page()


@pytest.mark.parametrize(
    "body",
    [
        "not-json",
        json.dumps([]),
        json.dumps({"count": 1}),
        json.dumps({"results": ["bad-node"]}),
        json.dumps({"results": [], "count": "1"}),
        json.dumps({"results": [], "next": "https://plane.example/issues/?limit=50"}),
    ],
)
def test_fetch_issue_page_maps_malformed_payloads_to_typed_error(body: str) -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(status_code=200, body=body),
        ),
    )

    with pytest.raises(PlanePayloadError):
        client.fetch_issue_page()


def test_fetch_candidate_issues_short_circuits_empty_active_states() -> None:
    config = PlaneTrackerConfig(
        kind="plane",
        api_base_url="https://plane.example/self-hosted",
        api_key="plane-token",
        workspace_slug="engineering",
        project_id="project-123",
        active_states=(),
        terminal_states=("Done",),
    )
    transport = RecordingTransport()
    client = PlaneTrackerClient(config, transport=transport)

    issues = client.fetch_candidate_issues()

    assert issues == []
    assert transport.calls == []


def test_fetch_candidate_issues_uses_cursor_pagination_and_filters_active_states() -> None:
    transport = RecordingTransport(
        responses=[
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "count": 2,
                        "next_cursor": "50:1:0",
                        "results": [
                            make_issue_payload(
                                issue_id="issue-1",
                                sequence_id=1,
                                name="First candidate",
                                state_id="state-todo",
                                state_name="Todo",
                            ),
                            make_issue_payload(
                                issue_id="issue-2",
                                sequence_id=2,
                                name="Filtered terminal issue",
                                state_id="state-done",
                                state_name="Done",
                            ),
                        ],
                    }
                ),
            ),
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "count": 1,
                        "next_cursor": None,
                        "results": [
                            make_issue_payload(
                                issue_id="issue-3",
                                sequence_id=3,
                                name="Second candidate",
                                state_id="state-progress",
                                state_name="In Progress",
                                blocked_by_issues=[
                                    {
                                        "id": "issue-4",
                                        "sequence_id": 4,
                                        "project": {"identifier": "ENG"},
                                        "state": {"name": "In Progress"},
                                    }
                                ],
                            )
                        ],
                    }
                ),
            ),
        ]
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_candidate_issues()

    assert [issue.identifier for issue in issues] == ["ENG-1", "ENG-3"]
    assert issues[0].labels == ("backend",)
    assert issues[1].blocked_by == (
        IssueBlocker(id="issue-4", identifier="ENG-4", state="In Progress"),
    )
    assert len(transport.calls) == 2
    assert transport.calls[0]["query_params"] == {
        "per_page": DEFAULT_PLANE_PAGE_SIZE,
        "expand": "state,project,labels,blocked_by_issues",
    }
    assert transport.calls[1]["query_params"] == {
        "per_page": DEFAULT_PLANE_PAGE_SIZE,
        "cursor": "50:1:0",
        "expand": "state,project,labels,blocked_by_issues",
    }


def test_fetch_issues_by_states_short_circuits_empty_requests() -> None:
    transport = RecordingTransport()
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issues_by_states([])

    assert issues == []
    assert transport.calls == []


def test_fetch_issues_by_states_filters_requested_terminal_states() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "count": 3,
                    "next_cursor": None,
                    "results": [
                        make_issue_payload(
                            issue_id="issue-1",
                            sequence_id=1,
                            name="Done issue",
                            state_id="state-done",
                            state_name="Done",
                        ),
                        make_issue_payload(
                            issue_id="issue-2",
                            sequence_id=2,
                            name="Cancelled issue",
                            state_id="state-cancelled",
                            state_name="Cancelled",
                        ),
                        make_issue_payload(
                            issue_id="issue-3",
                            sequence_id=3,
                            name="Ignored issue",
                            state_id="state-progress",
                            state_name="In Progress",
                        ),
                    ],
                }
            ),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issues_by_states([" Done ", "Cancelled"])

    assert [issue.identifier for issue in issues] == ["ENG-1", "ENG-2"]
    assert transport.calls[0]["query_params"] == {
        "per_page": DEFAULT_PLANE_PAGE_SIZE,
        "expand": "state,project,labels,blocked_by_issues",
    }


def test_fetch_issue_states_by_ids_short_circuits_empty_requests() -> None:
    transport = RecordingTransport()
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issue_states_by_ids([])

    assert issues == []
    assert transport.calls == []


def test_fetch_issue_states_by_ids_fetches_issue_detail_and_skips_missing_ids() -> None:
    transport = RecordingTransport(
        responses=[
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    make_issue_payload(
                        issue_id="issue-1",
                        sequence_id=1,
                        name="Refresh first issue",
                        state_id="state-todo",
                        state_name="Todo",
                    )
                ),
            ),
            PlaneTransportResponse(status_code=404, body='{"detail":"Not found."}'),
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    make_issue_payload(
                        issue_id="issue-3",
                        sequence_id=3,
                        name="Refresh third issue",
                        state_id="state-progress",
                        state_name="In Progress",
                    )
                ),
            ),
        ]
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issue_states_by_ids([" issue-1 ", "missing-issue", "issue-3"])

    assert [issue.identifier for issue in issues] == ["ENG-1", "ENG-3"]
    assert [call["url"] for call in transport.calls] == [
        (
            "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
            "project-123/issues/issue-1/"
        ),
        (
            "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
            "project-123/issues/missing-issue/"
        ),
        (
            "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
            "project-123/issues/issue-3/"
        ),
    ]
    assert all(
        call["query_params"] == {"expand": "state,project,labels,blocked_by_issues"}
        for call in transport.calls
    )


def test_get_issue_reference_queries_by_human_identifier() -> None:
    transport = RecordingTransport(
        responses=[
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "count": 1,
                        "next_cursor": "50:1:0",
                        "results": [
                            make_issue_payload(
                                issue_id="issue-1",
                                sequence_id=1,
                                name="First issue",
                                state_id="state-todo",
                                state_name="Todo",
                            )
                        ],
                    }
                ),
            ),
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "count": 1,
                        "next_cursor": None,
                        "results": [
                            make_issue_payload(
                                issue_id="issue-42",
                                sequence_id=42,
                                name="Lookup issue",
                                state_id="state-progress",
                                state_name="In Progress",
                            )
                        ],
                    }
                ),
            ),
        ]
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issue = client.get_issue_reference(" ENG-42 ")

    assert issue is not None
    assert issue.id == "issue-42"
    assert issue.identifier == "ENG-42"
    assert issue.state_id == "state-progress"
    assert issue.state_name == "In Progress"
    assert issue.workflow_scope_id == "project-123"
    assert issue.project_ref == "project-123"
    assert transport.calls[0]["query_params"] == {
        "per_page": DEFAULT_PLANE_PAGE_SIZE,
        "expand": "state,project,labels,blocked_by_issues",
    }
    assert transport.calls[1]["query_params"] == {
        "per_page": DEFAULT_PLANE_PAGE_SIZE,
        "cursor": "50:1:0",
        "expand": "state,project,labels,blocked_by_issues",
    }


def test_get_issue_reference_returns_none_for_blank_or_missing_identifier() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps({"count": 0, "next_cursor": None, "results": []}),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    assert client.get_issue_reference("   ") is None
    assert client.get_issue_reference("ENG-404") is None
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "payload_override",
    [
        {"state": {"id": None, "name": "Todo"}},
        {"state": {"id": "   ", "name": "Todo"}},
        {"state": {"id": 42, "name": "Todo"}},
    ],
)
def test_get_issue_reference_raises_for_missing_state_id(
    payload_override: dict[str, object],
) -> None:
    base = make_issue_payload(
        issue_id="issue-1",
        sequence_id=1,
        name="Bad state issue",
        state_id="state-todo",
        state_name="Todo",
    )
    payload = {**base, **payload_override}
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps({"count": 1, "next_cursor": None, "results": [payload]}),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    with pytest.raises(PlanePayloadError, match="state.id"):
        client.get_issue_reference("ENG-1")


@pytest.mark.parametrize(
    "payload_override",
    [
        {"project": None, "project_id": None},
        {"project": {"id": None, "identifier": "ENG"}, "project_id": None},
        {"project": {"id": "   ", "identifier": "ENG"}, "project_id": None},
    ],
)
def test_get_issue_reference_raises_for_missing_project_id(
    payload_override: dict[str, object],
) -> None:
    base = make_issue_payload(
        issue_id="issue-1",
        sequence_id=1,
        name="Bad project issue",
        state_id="state-todo",
        state_name="Todo",
    )
    payload = {**base, **payload_override}
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps({"count": 1, "next_cursor": None, "results": [payload]}),
        )
    )
    config = PlaneTrackerConfig(
        kind="plane",
        api_base_url="https://plane.example/self-hosted",
        api_key="plane-token",
        workspace_slug="engineering",
        project_id=None,
        active_states=("Todo",),
        terminal_states=("Done",),
    )
    client = PlaneTrackerClient(config, transport=transport)

    with pytest.raises(PlanePayloadError, match="project.id"):
        client.get_issue_reference("ENG-1")


def test_list_workflow_states_fetches_project_states() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps(
                [
                    make_state_payload(state_id="state-todo", state_name="Todo"),
                    make_state_payload(state_id="state-progress", state_name="In Progress"),
                ]
            ),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    states = client.list_workflow_states()

    assert [(state.id, state.name, state.workflow_scope_id) for state in states] == [
        ("state-todo", "Todo", "project-123"),
        ("state-progress", "In Progress", "project-123"),
    ]
    assert transport.calls == [
        {
            "method": "GET",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/"
                "projects/project-123/states/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": None,
            "timeout_ms": 30_000,
        }
    ]


def test_list_workflow_states_rejects_malformed_payload() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(
                status_code=200,
                body=json.dumps({"results": [{"id": "state-todo"}]}),
            )
        ),
    )

    with pytest.raises(PlanePayloadError, match="missing name"):
        client.list_workflow_states()


def test_create_comment_posts_comment_html_and_normalizes_response() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=201,
            body=json.dumps(
                {
                    "id": "comment-123",
                    "comment_stripped": "Ready for review\nShip it <soon>",
                    "url": "https://plane.example/comments/comment-123",
                }
            ),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    comment = client.create_comment("issue-123", "Ready for review\nShip it <soon>")

    assert comment.id == "comment-123"
    assert comment.body == "Ready for review\nShip it <soon>"
    assert comment.url == "https://plane.example/comments/comment-123"
    assert transport.calls == [
        {
            "method": "POST",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/work-items/issue-123/comments/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": {"comment_html": "<p>Ready for review<br />Ship it &lt;soon&gt;</p>"},
            "timeout_ms": 30_000,
        }
    ]


def test_create_comment_uses_request_body_when_response_omits_comment_text() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(
                status_code=200,
                body=json.dumps({"id": "comment-123", "url": None}),
            )
        ),
    )

    comment = client.create_comment("issue-123", "Fallback body")

    assert comment.body == "Fallback body"
    assert comment.url is None


def test_create_comment_rejects_malformed_payload() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=PlaneTransportResponse(
                status_code=201,
                body=json.dumps({"comment_stripped": "Ready for review"}),
            )
        ),
    )

    with pytest.raises(PlanePayloadError, match="missing id"):
        client.create_comment("issue-123", "Ready for review")


def test_create_issue_link_posts_title_and_url_with_explicit_metadata_limitations() -> None:
    transport = RecordingTransport(
        responses=[
            PlaneTransportResponse(status_code=200, body=json.dumps([])),
            PlaneTransportResponse(
                status_code=201,
                body=json.dumps(
                    {
                        "id": "link-123",
                        "title": "PR #1",
                        "url": "https://github.com/acme/symphony/pull/1",
                        "metadata": {"provider": "github"},
                    }
                ),
            ),
        ]
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issue_link = client.create_issue_link(
        issue_id="issue-123",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"status": "open", "commit_count": 3},
    )

    assert issue_link.id == "link-123"
    assert issue_link.title == "PR #1"
    assert issue_link.url == "https://github.com/acme/symphony/pull/1"
    assert issue_link.subtitle is None
    assert issue_link.metadata == {}
    assert transport.calls == [
        {
            "method": "GET",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/work-items/issue-123/links/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": None,
            "timeout_ms": 30_000,
        },
        {
            "method": "POST",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/work-items/issue-123/links/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": {
                "title": "PR #1",
                "url": "https://github.com/acme/symphony/pull/1",
            },
            "timeout_ms": 30_000,
        },
    ]


def test_create_issue_link_reuses_existing_url_without_posting_duplicate() -> None:
    transport = RecordingTransport(
        response=PlaneTransportResponse(
            status_code=200,
            body=json.dumps(
                [
                    {
                        "id": "link-123",
                        "title": "PR #1",
                        "url": "https://github.com/acme/symphony/pull/1",
                        "metadata": {"provider": "github"},
                    }
                ]
            ),
        )
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issue_link = client.create_issue_link(
        issue_id="issue-123",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Merged",
        metadata={"status": "merged"},
    )

    assert issue_link.id == "link-123"
    assert issue_link.title == "PR #1"
    assert issue_link.url == "https://github.com/acme/symphony/pull/1"
    assert issue_link.subtitle is None
    assert issue_link.metadata == {}
    assert [call["method"] for call in transport.calls] == ["GET"]


def test_create_issue_link_patches_existing_url_when_title_changes() -> None:
    transport = RecordingTransport(
        responses=[
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    [
                        {
                            "id": "link-123",
                            "title": "Old PR title",
                            "url": "https://github.com/acme/symphony/pull/1",
                            "metadata": {"provider": "github"},
                        }
                    ]
                ),
            ),
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "id": "link-123",
                        "title": "PR #1",
                        "url": "https://github.com/acme/symphony/pull/1",
                        "metadata": {"provider": "github"},
                    }
                ),
            ),
        ]
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issue_link = client.create_issue_link(
        issue_id="issue-123",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Merged",
        metadata={"status": "merged"},
    )

    assert issue_link.id == "link-123"
    assert issue_link.title == "PR #1"
    assert issue_link.url == "https://github.com/acme/symphony/pull/1"
    assert issue_link.subtitle is None
    assert issue_link.metadata == {}
    assert transport.calls == [
        {
            "method": "GET",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/work-items/issue-123/links/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": None,
            "timeout_ms": 30_000,
        },
        {
            "method": "PATCH",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/work-items/issue-123/links/link-123/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": {
                "title": "PR #1",
            },
            "timeout_ms": 30_000,
        },
    ]


def test_update_issue_state_patches_work_item_and_refetches_issue() -> None:
    transport = RecordingTransport(
        responses=[
            PlaneTransportResponse(status_code=200, body=json.dumps({"id": "issue-123"})),
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    make_issue_payload(
                        issue_id="issue-123",
                        sequence_id=123,
                        name="Transitioned issue",
                        state_id="state-progress",
                        state_name="In Progress",
                    )
                ),
            ),
        ]
    )
    client = PlaneTrackerClient(make_tracker_config(), transport=transport)

    issue = client.update_issue_state("issue-123", "state-progress")

    assert issue.id == "issue-123"
    assert issue.identifier == "ENG-123"
    assert issue.state_id == "state-progress"
    assert issue.state_name == "In Progress"
    assert transport.calls == [
        {
            "method": "PATCH",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/work-items/issue-123/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {},
            "json_body": {"state": "state-progress"},
            "timeout_ms": 30_000,
        },
        {
            "method": "GET",
            "url": (
                "https://plane.example/self-hosted/api/v1/workspaces/engineering/projects/"
                "project-123/issues/issue-123/"
            ),
            "headers": {
                "Accept": "application/json",
                "X-API-Key": "plane-token",
            },
            "query_params": {"expand": "state,project,labels,blocked_by_issues"},
            "json_body": None,
            "timeout_ms": 30_000,
        },
    ]


def test_update_issue_state_surfaces_refetch_payload_errors() -> None:
    client = PlaneTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            responses=[
                PlaneTransportResponse(status_code=200, body=json.dumps({"id": "issue-123"})),
                PlaneTransportResponse(
                    status_code=200,
                    body=json.dumps(
                        {
                            "id": "issue-123",
                            "sequence_id": 123,
                            "name": "Bad transitioned issue",
                            "state": {"name": "In Progress"},
                            "project": {"id": "project-123", "identifier": "ENG"},
                            "labels": [],
                            "created_at": "2026-03-01T12:00:00Z",
                            "updated_at": "2026-03-02T12:00:00Z",
                        }
                    ),
                ),
            ]
        ),
    )

    with pytest.raises(PlanePayloadError, match="state.id"):
        client.update_issue_state("issue-123", "state-progress")
