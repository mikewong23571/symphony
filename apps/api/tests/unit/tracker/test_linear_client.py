from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

import pytest
from symphony.tracker import (
    CREATE_ATTACHMENT_MUTATION,
    CREATE_COMMENT_MUTATION,
    DEFAULT_LINEAR_PAGE_SIZE,
    FETCH_CANDIDATE_ISSUES_QUERY,
    FETCH_ISSUE_STATES_BY_IDS_QUERY,
    FETCH_ISSUES_BY_STATES_QUERY,
    FETCH_TRACKER_ISSUE_REFERENCE_QUERY,
    FETCH_WORKFLOW_STATES_QUERY,
    UPDATE_ISSUE_STATE_MUTATION,
    LinearAPIRequestError,
    LinearAPIStatusError,
    LinearGraphQLError,
    LinearMissingEndCursorError,
    LinearPayloadError,
    LinearTrackerClient,
    LinearTransportResponse,
)
from symphony.workflow.config import LinearTrackerConfig


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


def make_tracker_config() -> LinearTrackerConfig:
    return LinearTrackerConfig(
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


def test_get_issue_reference_queries_by_human_identifier() -> None:
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
                                    "state": {"id": "state-1", "name": "Todo"},
                                    "team": {"id": "team-1"},
                                    "project": {"slugId": "symphony"},
                                }
                            ]
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issue = client.get_issue_reference(" SYM-042 ")

    assert issue is not None
    assert issue.identifier == "SYM-042"
    assert issue.state_name == "Todo"
    assert issue.workflow_scope_id == "team-1"
    assert issue.team_id == "team-1"
    assert issue.project_ref == "symphony"
    assert issue.project_slug == "symphony"
    assert transport.calls[0]["variables"] == {
        "projectSlug": "symphony",
        "issueIdentifier": "SYM-042",
    }
    assert transport.calls[0]["query"] == FETCH_TRACKER_ISSUE_REFERENCE_QUERY


def test_list_workflow_states_returns_workflow_scoped_state_records() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "workflowStates": {
                            "nodes": [
                                {"id": "state-1", "name": "Todo", "team": {"id": "team-1"}},
                                {
                                    "id": "state-2",
                                    "name": "In Progress",
                                    "team": {"id": "team-1"},
                                },
                            ],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    states = client.list_workflow_states()

    assert [(state.id, state.name, state.workflow_scope_id) for state in states] == [
        ("state-1", "Todo", "team-1"),
        ("state-2", "In Progress", "team-1"),
    ]
    assert [state.team_id for state in states] == ["team-1", "team-1"]
    assert transport.calls[0]["query"] == FETCH_WORKFLOW_STATES_QUERY
    assert transport.calls[0]["variables"] == {
        "first": DEFAULT_LINEAR_PAGE_SIZE,
        "after": None,
    }
    assert "$first: Int!" in FETCH_WORKFLOW_STATES_QUERY
    assert "pageInfo" in FETCH_WORKFLOW_STATES_QUERY


def test_list_workflow_states_paginates_across_pages() -> None:
    transport = RecordingTransport(
        responses=[
            LinearTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "data": {
                            "workflowStates": {
                                "nodes": [
                                    {"id": "state-1", "name": "Todo", "team": {"id": "team-1"}},
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
                            "workflowStates": {
                                "nodes": [
                                    {
                                        "id": "state-99",
                                        "name": "Human Review",
                                        "team": {"id": "team-1"},
                                    },
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

    states = client.list_workflow_states()

    assert [(state.id, state.name) for state in states] == [
        ("state-1", "Todo"),
        ("state-99", "Human Review"),
    ]
    assert len(transport.calls) == 2
    assert transport.calls[0]["variables"]["after"] is None
    assert transport.calls[1]["variables"]["after"] == "cursor-1"


def test_create_comment_returns_normalized_comment_record() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "commentCreate": {
                            "success": True,
                            "comment": {
                                "id": "comment-1",
                                "body": "Ready for review",
                                "url": "https://linear.app/comment-1",
                            },
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    comment = client.create_comment("issue-42", "Ready for review")

    assert comment.id == "comment-1"
    assert comment.body == "Ready for review"
    assert transport.calls[0]["query"] == CREATE_COMMENT_MUTATION
    assert transport.calls[0]["variables"] == {
        "issueId": "issue-42",
        "body": "Ready for review",
    }


def test_update_issue_state_returns_updated_issue_reference() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "issueUpdate": {
                            "success": True,
                            "issue": {
                                "id": "issue-42",
                                "identifier": "SYM-042",
                                "state": {"id": "state-2", "name": "In Progress"},
                                "team": {"id": "team-1"},
                                "project": {"slugId": "symphony"},
                            },
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issue = client.update_issue_state("issue-42", "state-2")

    assert issue.state_id == "state-2"
    assert issue.state_name == "In Progress"
    assert transport.calls[0]["query"] == UPDATE_ISSUE_STATE_MUTATION
    assert transport.calls[0]["variables"] == {"issueId": "issue-42", "stateId": "state-2"}


def test_create_issue_link_sends_scalar_inputs_as_variables() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "attachmentCreate": {
                            "success": True,
                            "attachment": {
                                "id": "attachment-1",
                                "title": "PR #1",
                                "url": "https://github.com/acme/symphony/pull/1",
                                "subtitle": "Open",
                                "metadata": {
                                    "branch_name": "feature/sym-123",
                                    "status": "open",
                                },
                            },
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    issue_link = client.create_issue_link(
        issue_id="issue-42",
        title="PR #1",
        url="https://github.com/acme/symphony/pull/1",
        subtitle="Open",
        metadata={"branch_name": "feature/sym-123", "status": "open"},
    )

    assert issue_link.id == "attachment-1"
    assert issue_link.metadata["branch_name"] == "feature/sym-123"
    assert transport.calls[0]["query"] == CREATE_ATTACHMENT_MUTATION
    assert transport.calls[0]["variables"] == {
        "issueId": "issue-42",
        "title": "PR #1",
        "url": "https://github.com/acme/symphony/pull/1",
        "subtitle": "Open",
        "metadata": {"branch_name": "feature/sym-123", "status": "open"},
    }


def test_create_issue_link_rejects_non_finite_metadata_before_transport() -> None:
    transport = RecordingTransport()
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    with pytest.raises(LinearPayloadError, match="request contains malformed metadata"):
        client.create_issue_link(
            issue_id="issue-42",
            title="PR #2",
            url="https://github.com/acme/symphony/pull/2",
            subtitle=None,
            metadata={"build_time_seconds": math.nan},
        )

    assert transport.calls == []


def test_create_attachment_aliases_create_issue_link() -> None:
    transport = RecordingTransport(
        response=LinearTransportResponse(
            status_code=200,
            body=json.dumps(
                {
                    "data": {
                        "attachmentCreate": {
                            "success": True,
                            "attachment": {
                                "id": "attachment-9",
                                "title": "PR #9",
                                "url": "https://github.com/acme/symphony/pull/9",
                                "subtitle": "Merged",
                                "metadata": {"status": "merged"},
                            },
                        }
                    }
                }
            ),
        )
    )
    client = LinearTrackerClient(make_tracker_config(), transport=transport)

    attachment = client.create_attachment(
        issue_id="issue-42",
        title="PR #9",
        url="https://github.com/acme/symphony/pull/9",
        subtitle="Merged",
        metadata={"status": "merged"},
    )

    assert attachment.id == "attachment-9"
    assert attachment.metadata == {"status": "merged"}
