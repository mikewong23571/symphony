from __future__ import annotations

from datetime import UTC, datetime

import pytest
from lib.tracker import IssueBlocker, LinearPayloadError, normalize_linear_issue


def test_normalize_linear_issue_normalizes_full_candidate_payload() -> None:
    issue = normalize_linear_issue(
        {
            "id": "issue-1",
            "identifier": "SYM-101",
            "title": "Normalize issue payloads",
            "description": "Implement tracker normalization",
            "priority": 2,
            "state": {"name": "Todo"},
            "branchName": "feature/sym-101",
            "url": "https://linear.app/acme/issue/SYM-101",
            "labels": {
                "nodes": [
                    {"name": "Backend"},
                    {"name": "Needs Review"},
                ]
            },
            "inverseRelations": {
                "nodes": [
                    {
                        "type": "blocks",
                        "issue": {
                            "id": "issue-2",
                            "identifier": "SYM-099",
                            "state": {"name": "In Progress"},
                        },
                    },
                    {
                        "type": "relates_to",
                        "issue": {
                            "id": "issue-3",
                            "identifier": "SYM-050",
                            "state": {"name": "Done"},
                        },
                    },
                ]
            },
            "createdAt": "2026-03-01T12:00:00Z",
            "updatedAt": "2026-03-02T15:30:00Z",
        }
    )

    assert issue.id == "issue-1"
    assert issue.identifier == "SYM-101"
    assert issue.title == "Normalize issue payloads"
    assert issue.description == "Implement tracker normalization"
    assert issue.priority == 2
    assert issue.state == "Todo"
    assert issue.branch_name == "feature/sym-101"
    assert issue.url == "https://linear.app/acme/issue/SYM-101"
    assert issue.labels == ("backend", "needs review")
    assert issue.blocked_by == (
        IssueBlocker(
            id="issue-2",
            identifier="SYM-099",
            state="In Progress",
        ),
    )
    assert issue.created_at == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert issue.updated_at == datetime(2026, 3, 2, 15, 30, tzinfo=UTC)


def test_normalize_linear_issue_supports_related_issue_blocker_shape() -> None:
    issue = normalize_linear_issue(
        {
            "id": "issue-1",
            "identifier": "SYM-201",
            "title": "Refresh issue state",
            "state": {"name": "In Progress"},
            "inverseRelations": {
                "nodes": [
                    {
                        "type": "blocks",
                        "relatedIssue": {
                            "id": "issue-9",
                            "identifier": "SYM-001",
                            "state": {"name": "Todo"},
                        },
                    }
                ]
            },
        }
    )

    assert len(issue.blocked_by) == 1
    assert issue.blocked_by[0].id == "issue-9"
    assert issue.blocked_by[0].identifier == "SYM-001"
    assert issue.blocked_by[0].state == "Todo"


def test_normalize_linear_issue_uses_none_for_non_integer_priority() -> None:
    issue = normalize_linear_issue(
        {
            "id": "issue-1",
            "identifier": "SYM-301",
            "title": "Priority coercion",
            "priority": "2",
            "state": {"name": "Todo"},
        }
    )

    assert issue.priority is None


def test_normalize_linear_issue_accepts_missing_optional_fields() -> None:
    issue = normalize_linear_issue(
        {
            "id": "issue-1",
            "identifier": "SYM-401",
            "title": "Minimal payload",
            "state": {"name": "Todo"},
        }
    )

    assert issue.description is None
    assert issue.branch_name is None
    assert issue.url is None
    assert issue.labels == ()
    assert issue.blocked_by == ()
    assert issue.created_at is None
    assert issue.updated_at is None


@pytest.mark.parametrize("missing_key", ["id", "identifier", "title"])
def test_normalize_linear_issue_requires_core_string_fields(missing_key: str) -> None:
    payload = {
        "id": "issue-1",
        "identifier": "SYM-501",
        "title": "Required fields",
        "state": {"name": "Todo"},
    }
    del payload[missing_key]

    with pytest.raises(LinearPayloadError, match=missing_key):
        normalize_linear_issue(payload)


def test_normalize_linear_issue_requires_state_name() -> None:
    with pytest.raises(LinearPayloadError, match="state.name"):
        normalize_linear_issue(
            {
                "id": "issue-1",
                "identifier": "SYM-601",
                "title": "Missing state",
            }
        )


def test_normalize_linear_issue_rejects_invalid_timestamps() -> None:
    with pytest.raises(LinearPayloadError, match="invalid timestamp"):
        normalize_linear_issue(
            {
                "id": "issue-1",
                "identifier": "SYM-701",
                "title": "Bad timestamps",
                "state": {"name": "Todo"},
                "createdAt": "not-a-timestamp",
            }
        )
