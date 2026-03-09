from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from symphony.tracker import (
    DEFAULT_LINEAR_PAGE_SIZE,
    FETCH_CANDIDATE_ISSUES_QUERY,
    FETCH_ISSUE_STATES_BY_IDS_QUERY,
    FETCH_ISSUES_BY_STATES_QUERY,
    LinearAPIRequestError,
    LinearAPIStatusError,
    LinearGraphQLError,
    LinearMissingEndCursorError,
    LinearPayloadError,
    LinearTrackerClient,
    LinearTransportResponse,
)
from symphony.workflow.config import TrackerConfig


class RecordingTransport:
    def __init__(
        self,
        *,
        response: LinearTransportResponse | None = None,
        responses: list[LinearTransportResponse] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.responses = responses or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        *,
        endpoint: str,
        headers: Mapping[str, str],
        query: str,
        variables: Mapping[str, object],
        timeout_ms: int,
    ) -> LinearTransportResponse:
        self.calls.append(
            {
                "endpoint": endpoint,
                "headers": dict(headers),
                "query": query,
                "variables": dict(variables),
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


def make_tracker_config() -> TrackerConfig:
    return TrackerConfig(
        kind="linear",
        endpoint="https://api.linear.app/graphql",
        api_key="linear-token",
        project_slug="symphony",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done",),
    )


def test_fetch_issues_by_states_short_circuits_empty_requests() -> None:
    transport = RecordingTransport()
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issues_by_states([])

    assert issues == []
    assert transport.calls == []


def test_fetch_issues_by_states_sends_project_slug_and_state_names() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "issue-1",
                                    "identifier": "SYM-123",
                                    "title": "Sweep terminal workspaces",
                                    "state": {"name": "Done"},
                                    "labels": {"nodes": [{"name": "Ops"}]},
                                }
                            ]
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issues_by_states([" Done ", "Cancelled"])

    assert [issue.identifier for issue in issues] == ["SYM-123"]
    assert issues[0].labels == ("ops",)
    assert len(transport.calls) == 1
    assert transport.calls[0]["endpoint"] == "https://api.linear.app/graphql"
    assert transport.calls[0]["headers"] == {
        "Authorization": "linear-token",
        "Content-Type": "application/json",
    }
    assert transport.calls[0]["variables"] == {
        "projectSlug": "symphony",
        "stateNames": ["Done", "Cancelled"],
    }
    assert transport.calls[0]["timeout_ms"] == 30_000
    assert transport.calls[0]["query"] == FETCH_ISSUES_BY_STATES_QUERY
    assert "slugId" in FETCH_ISSUES_BY_STATES_QUERY
    assert "$stateNames: [String!]!" in FETCH_ISSUES_BY_STATES_QUERY


def test_fetch_issues_by_states_maps_transport_failures_to_typed_error() -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(error=OSError("network down")),
    )

    with pytest.raises(LinearAPIRequestError, match="Linear API request failed."):
        client.fetch_issues_by_states(["Done"])


def test_fetch_issues_by_states_maps_non_200_status_to_typed_error() -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=LinearTransportResponse(status_code=503, body='{"error":"bad gateway"}')
        ),
    )

    with pytest.raises(LinearAPIStatusError, match="HTTP 503"):
        client.fetch_issues_by_states(["Done"])


def test_fetch_issues_by_states_maps_graphql_errors_to_typed_error() -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=LinearTransportResponse(
                status_code=200,
                body=json.dumps({"errors": [{"message": "forbidden"}]}),
            )
        ),
    )

    with pytest.raises(
        LinearGraphQLError,
        match="Linear GraphQL response returned top-level errors.",
    ):
        client.fetch_issues_by_states(["Done"])


@pytest.mark.parametrize(
    "body",
    [
        "not-json",
        json.dumps({"data": {}}),
        json.dumps({"data": {"issues": {}}}),
        json.dumps({"data": {"issues": {"nodes": ["bad-node"]}}}),
    ],
)
def test_fetch_issues_by_states_maps_malformed_payloads_to_typed_error(body: str) -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=LinearTransportResponse(status_code=200, body=body),
        ),
    )

    with pytest.raises(LinearPayloadError):
        client.fetch_issues_by_states(["Done"])


def test_fetch_candidate_issues_uses_active_states_project_slug_and_page_size() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "issue-10",
                                    "identifier": "SYM-900",
                                    "title": "Dispatch candidate",
                                    "state": {"name": "Todo"},
                                    "labels": {"nodes": [{"name": "Backend"}]},
                                }
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_candidate_issues()

    assert [issue.identifier for issue in issues] == ["SYM-900"]
    assert issues[0].labels == ("backend",)
    assert len(transport.calls) == 1
    assert transport.calls[0]["variables"] == {
        "projectSlug": "symphony",
        "stateNames": ["Todo", "In Progress"],
        "first": DEFAULT_LINEAR_PAGE_SIZE,
        "after": None,
    }
    assert transport.calls[0]["query"] == FETCH_CANDIDATE_ISSUES_QUERY
    assert "slugId" in FETCH_CANDIDATE_ISSUES_QUERY
    assert "$first: Int!" in FETCH_CANDIDATE_ISSUES_QUERY
    assert "pageInfo" in FETCH_CANDIDATE_ISSUES_QUERY


def test_fetch_candidate_issues_preserves_order_across_multiple_pages() -> None:
    transport = RecordingTransport(
        responses=[
            LinearTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "data": {
                            "issues": {
                                "nodes": [
                                    {
                                        "id": "issue-1",
                                        "identifier": "SYM-001",
                                        "title": "First issue",
                                        "state": {"name": "Todo"},
                                    }
                                ],
                                "pageInfo": {"hasNextPage": True, "endCursor": "cursor-1"},
                            }
                        }
                    }
                ),
            ),
            LinearTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "data": {
                            "issues": {
                                "nodes": [
                                    {
                                        "id": "issue-2",
                                        "identifier": "SYM-002",
                                        "title": "Second issue",
                                        "state": {"name": "In Progress"},
                                    }
                                ],
                                "pageInfo": {"hasNextPage": False, "endCursor": "cursor-2"},
                            }
                        }
                    }
                ),
            ),
        ]
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_candidate_issues()

    assert [issue.identifier for issue in issues] == ["SYM-001", "SYM-002"]
    assert len(transport.calls) == 2
    assert transport.calls[0]["variables"]["after"] is None
    assert transport.calls[1]["variables"]["after"] == "cursor-1"


def test_fetch_candidate_issues_raises_when_next_page_is_missing_end_cursor() -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(
            response=LinearTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "data": {
                            "issues": {
                                "nodes": [],
                                "pageInfo": {"hasNextPage": True, "endCursor": None},
                            }
                        }
                    }
                ),
            )
        ),
    )

    with pytest.raises(
        LinearMissingEndCursorError,
        match="missing pageInfo.endCursor",
    ):
        client.fetch_candidate_issues()


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (
            LinearTransportResponse(status_code=503, body='{"error":"bad gateway"}'),
            LinearAPIStatusError,
        ),
        (
            LinearTransportResponse(
                status_code=200,
                body=json.dumps({"errors": [{"message": "forbidden"}]}),
            ),
            LinearGraphQLError,
        ),
        (
            LinearTransportResponse(status_code=200, body=json.dumps({"data": {"issues": {}}})),
            LinearPayloadError,
        ),
    ],
)
def test_fetch_candidate_issues_reuses_existing_typed_error_handling(
    response: LinearTransportResponse,
    error_type: type[Exception],
) -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(response=response),
    )

    with pytest.raises(error_type):
        client.fetch_candidate_issues()


def test_fetch_issue_states_by_ids_short_circuits_empty_requests() -> None:
    transport = RecordingTransport()
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issue_states_by_ids([])

    assert issues == []
    assert transport.calls == []


def test_fetch_issue_states_by_ids_uses_graphql_id_variable_type() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "issues": {
                            "nodes": [
                                {
                                    "id": "issue-42",
                                    "identifier": "SYM-042",
                                    "title": "Reconcile running issue",
                                    "state": {"name": "In Progress"},
                                }
                            ]
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issues = client.fetch_issue_states_by_ids([" issue-42 ", "issue-43"])

    assert [issue.identifier for issue in issues] == ["SYM-042"]
    assert issues[0].description is None
    assert issues[0].labels == ()
    assert transport.calls[0]["variables"] == {"issueIds": ["issue-42", "issue-43"]}
    assert transport.calls[0]["query"] == FETCH_ISSUE_STATES_BY_IDS_QUERY
    assert "$issueIds: [ID!]!" in FETCH_ISSUE_STATES_BY_IDS_QUERY


@pytest.mark.parametrize(
    ("response", "error_type"),
    [
        (
            LinearTransportResponse(status_code=503, body='{"error":"bad gateway"}'),
            LinearAPIStatusError,
        ),
        (
            LinearTransportResponse(
                status_code=200,
                body=json.dumps({"errors": [{"message": "forbidden"}]}),
            ),
            LinearGraphQLError,
        ),
        (
            LinearTransportResponse(status_code=200, body=json.dumps({"data": {"issues": {}}})),
            LinearPayloadError,
        ),
    ],
)
def test_fetch_issue_states_by_ids_reuses_existing_typed_error_handling(
    response: LinearTransportResponse,
    error_type: type[Exception],
) -> None:
    client = LinearTrackerClient(
        make_tracker_config(),
        transport=RecordingTransport(response=response),
    )

    with pytest.raises(error_type):
        client.fetch_issue_states_by_ids(["issue-42"])
