from __future__ import annotations

from datetime import UTC, datetime

import pytest
from lib.tracker import IssueBlocker, PlanePayloadError, normalize_plane_issue


def test_normalize_plane_issue_normalizes_full_issue_payload() -> None:
    issue = normalize_plane_issue(
        {
            "id": "issue-1",
            "sequence_id": 123,
            "name": "Normalize Plane payloads",
            "description_stripped": "Implement tracker normalization",
            "priority": "high",
            "state": {"name": "Todo"},
            "branch_name": "feature/eng-123",
            "url": "https://plane.example/engineering/work-items/ENG-123",
            "project": {"identifier": "ENG"},
            "labels": [
                {"name": "Backend"},
                {"name": "Needs Review"},
            ],
            "blocked_by": [
                {
                    "id": "issue-2",
                    "sequence_id": 99,
                    "project": {"identifier": "ENG"},
                    "state": {"name": "In Progress"},
                }
            ],
            "created_at": "2026-03-01T12:00:00Z",
            "updated_at": "2026-03-02T15:30:00Z",
        }
    )

    assert issue.id == "issue-1"
    assert issue.identifier == "ENG-123"
    assert issue.title == "Normalize Plane payloads"
    assert issue.description == "Implement tracker normalization"
    assert issue.priority == 2
    assert issue.state == "Todo"
    assert issue.branch_name == "feature/eng-123"
    assert issue.url == "https://plane.example/engineering/work-items/ENG-123"
    assert issue.labels == ("backend", "needs review")
    assert issue.blocked_by == (
        IssueBlocker(
            id="issue-2",
            identifier="ENG-99",
            state="In Progress",
        ),
    )
    assert issue.created_at == datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
    assert issue.updated_at == datetime(2026, 3, 2, 15, 30, tzinfo=UTC)


def test_normalize_plane_issue_accepts_project_identifier_override() -> None:
    issue = normalize_plane_issue(
        {
            "id": "issue-7",
            "sequenceId": "44",
            "title": "Use project override",
            "state_name": "In Progress",
            "labels": {"results": [{"name": "Ops"}]},
        },
        project_identifier="OPS",
    )

    assert issue.identifier == "OPS-44"
    assert issue.title == "Use project override"
    assert issue.labels == ("ops",)


def test_normalize_plane_issue_accepts_missing_optional_fields() -> None:
    issue = normalize_plane_issue(
        {
            "id": "issue-8",
            "sequence_id": 8,
            "name": "Minimal payload",
            "state": {"name": "Todo"},
            "project": {"identifier": "ENG"},
        }
    )

    assert issue.description is None
    assert issue.priority is None
    assert issue.branch_name is None
    assert issue.url is None
    assert issue.labels == ()
    assert issue.blocked_by == ()
    assert issue.created_at is None
    assert issue.updated_at is None


def test_normalize_plane_issue_falls_back_to_supported_work_item_html_description() -> None:
    issue = normalize_plane_issue(
        {
            "id": "issue-9",
            "sequence_id": 9,
            "name": "Work item payload",
            "description_html": "<div>First line</div><p>Second &amp; third</p>",
            "state": {"name": "Todo"},
            "project": {"identifier": "ENG"},
            "blockedBy": {
                "nodes": [
                    {
                        "relatedIssue": {
                            "id": "issue-7",
                            "sequenceId": "7",
                            "projectDetail": {"identifier": "ENG"},
                            "stateDetail": {"name": "Blocked"},
                        }
                    }
                ]
            },
        }
    )

    assert issue.description == "First line\nSecond & third"
    assert issue.blocked_by == (
        IssueBlocker(
            id="issue-7",
            identifier="ENG-7",
            state="Blocked",
        ),
    )


def test_normalize_plane_issue_maps_named_priorities_and_blank_values() -> None:
    high = normalize_plane_issue(
        {
            "id": "issue-high",
            "sequence_id": 9,
            "name": "Priority high",
            "priority": "urgent",
            "state": {"name": "Todo"},
            "project": {"identifier": "ENG"},
        }
    )
    none = normalize_plane_issue(
        {
            "id": "issue-none",
            "sequence_id": 10,
            "name": "Priority none",
            "priority": "none",
            "state": {"name": "Todo"},
            "project": {"identifier": "ENG"},
        }
    )

    assert high.priority == 1
    assert none.priority is None


@pytest.mark.parametrize("missing_key", ["id", "name", "sequence_id"])
def test_normalize_plane_issue_requires_core_fields(missing_key: str) -> None:
    payload = {
        "id": "issue-1",
        "sequence_id": 12,
        "name": "Required fields",
        "state": {"name": "Todo"},
        "project": {"identifier": "ENG"},
    }
    del payload[missing_key]

    with pytest.raises(PlanePayloadError, match=missing_key):
        normalize_plane_issue(payload)


def test_normalize_plane_issue_requires_state_name() -> None:
    with pytest.raises(PlanePayloadError, match="state.name"):
        normalize_plane_issue(
            {
                "id": "issue-1",
                "sequence_id": 12,
                "name": "Missing state",
                "project": {"identifier": "ENG"},
            }
        )


def test_normalize_plane_issue_requires_project_identifier() -> None:
    with pytest.raises(PlanePayloadError, match="project.identifier"):
        normalize_plane_issue(
            {
                "id": "issue-1",
                "sequence_id": 12,
                "name": "Missing project",
                "state": {"name": "Todo"},
            }
        )


def test_normalize_plane_issue_rejects_invalid_timestamps() -> None:
    with pytest.raises(PlanePayloadError, match="invalid timestamp"):
        normalize_plane_issue(
            {
                "id": "issue-1",
                "sequence_id": 12,
                "name": "Bad timestamps",
                "state": {"name": "Todo"},
                "project": {"identifier": "ENG"},
                "created_at": "not-a-timestamp",
            }
        )
