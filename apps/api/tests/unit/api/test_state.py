from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Generator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from django.test import Client
from symphony.agent_runner import AttemptResult
from symphony.observability.events import (
    clear_runtime_invalidations,
    publish_runtime_invalidation,
    wait_for_runtime_invalidation,
)
from symphony.observability.runtime import (
    DEFAULT_RUNTIME_REFRESH_REQUEST_FILENAME,
    DEFAULT_RUNTIME_SNAPSHOT_FILENAME,
    RuntimeSnapshotUnavailableError,
    clear_runtime_refresh_request_file,
    clear_runtime_snapshot_file,
    clear_runtime_snapshot_provider,
    consume_runtime_refresh_request,
    get_runtime_recovery_path,
    get_runtime_refresh_request_path,
    get_runtime_snapshot_path,
    publish_runtime_snapshot,
)
from symphony.orchestrator import Orchestrator
from symphony.tracker import PlaneTrackerClient, PlaneTransportResponse
from symphony.tracker.models import Issue
from symphony.workflow.config import ServiceConfig, build_service_config
from symphony.workflow.loader import WorkflowDefinition


class SilentTrackerClient:
    def fetch_candidate_issues(self) -> list[Issue]:
        return []

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]:
        return []

    def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]:
        return []


class RecordingPlaneTransport:
    def __init__(self, responses: list[PlaneTransportResponse]) -> None:
        self.responses = list(responses)
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
        if not self.responses:
            raise AssertionError("Test transport expected another configured response.")
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def clear_snapshot_state(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    monkeypatch.delenv("SYMPHONY_RUNTIME_SNAPSHOT_PATH", raising=False)
    monkeypatch.delenv("SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH", raising=False)
    monkeypatch.delenv("SYMPHONY_RUNTIME_RECOVERY_PATH", raising=False)
    monkeypatch.delenv("SYMPHONY_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS", raising=False)
    clear_runtime_invalidations()
    clear_runtime_snapshot_provider()
    _clear_snapshot_file_best_effort()
    _clear_refresh_request_file_best_effort()
    _clear_recovery_file_best_effort()
    yield
    clear_runtime_invalidations()
    clear_runtime_snapshot_provider()
    _clear_snapshot_file_best_effort()
    _clear_refresh_request_file_best_effort()
    _clear_recovery_file_best_effort()


def build_config(*, tmp_path: Path) -> ServiceConfig:
    return build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                },
                "workspace": {"root": str(tmp_path / "workspaces")},
                "agent": {"max_concurrent_agents": 2},
                "codex": {"command": "codex app-server"},
            },
            prompt_template="Prompt body",
        )
    )


def build_plane_config(*, tmp_path: Path) -> ServiceConfig:
    return build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "plane",
                    "api_base_url": "https://plane.example/self-hosted",
                    "api_key": "plane-token",
                    "workspace_slug": "engineering",
                    "project_id": "project-123",
                    "active_states": ["Todo", "In Progress"],
                    "terminal_states": ["Done"],
                },
                "workspace": {"root": str(tmp_path / "workspaces")},
                "agent": {"max_concurrent_agents": 2},
                "codex": {"command": "codex app-server"},
            },
            prompt_template="Prompt body",
        )
    )


def make_plane_issue_payload(
    *,
    issue_id: str,
    sequence_id: int,
    state_id: str,
    state_name: str,
) -> dict[str, object]:
    return {
        "id": issue_id,
        "sequence_id": sequence_id,
        "name": f"Issue {sequence_id}",
        "description_stripped": f"Description {sequence_id}",
        "priority": "high",
        "state": {"id": state_id, "name": state_name},
        "project": {"id": "project-123", "identifier": "ENG"},
        "labels": [],
        "created_at": "2026-03-01T12:00:00Z",
        "updated_at": "2026-03-02T12:00:00Z",
    }


def fresh_snapshot_times(*, revision: int = 1) -> dict[str, str | int]:
    generated_at = datetime.now(UTC)
    expires_at = generated_at + timedelta(minutes=5)
    return {
        "revision": revision,
        "generated_at": generated_at.isoformat().replace("+00:00", "Z"),
        "expires_at": expires_at.isoformat().replace("+00:00", "Z"),
    }


def test_healthz_response_is_preserved() -> None:
    response = Client().get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "symphony-api"}


def test_dashboard_returns_503_html_when_snapshot_is_missing() -> None:
    response = Client().get("/")

    assert response.status_code == 503
    assert response["Content-Type"].startswith("text/html")
    assert "Runtime snapshot unavailable" in response.content.decode("utf-8")


def test_dashboard_renders_runtime_snapshot_html() -> None:
    publish_runtime_snapshot(
        {
            **fresh_snapshot_times(),
            "counts": {"running": 1, "retrying": 1},
            "running": [
                {
                    "issue_id": "issue-123",
                    "issue_identifier": "SYM-123",
                    "attempt": 2,
                    "state": "In Progress",
                    "session_id": "thread-1-turn-2",
                    "turn_count": 7,
                    "last_event": "notification",
                    "last_message": "Working on tests",
                    "started_at": "2026-03-10T09:55:00Z",
                    "last_event_at": "2026-03-10T09:59:30Z",
                    "workspace_path": "/tmp/symphony/SYM-123",
                    "tokens": {
                        "input_tokens": 1200,
                        "output_tokens": 800,
                        "total_tokens": 2000,
                    },
                }
            ],
            "retrying": [
                {
                    "issue_id": "issue-456",
                    "issue_identifier": "SYM-456",
                    "attempt": 3,
                    "due_at": "2026-03-10T10:01:00Z",
                    "error": "no available orchestrator slots",
                    "workspace_path": "/tmp/symphony/SYM-456",
                }
            ],
            "codex_totals": {
                "input_tokens": 1200,
                "output_tokens": 800,
                "total_tokens": 2000,
                "seconds_running": 300.0,
            },
            "rate_limits": None,
        }
    )

    response = Client().get("/")
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/html")
    assert "Symphony Runtime" in body
    assert "Read-only observability view" in body
    assert "SYM-123" in body
    assert "SYM-456" in body
    assert "/api/v1/state" in body


def test_dashboard_rejects_post_with_405_html_response() -> None:
    response = Client(enforce_csrf_checks=True).post("/", data={})

    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"
    assert response["Content-Type"].startswith("text/html")
    assert "Method &#x27;POST&#x27; is not allowed for /." in response.content.decode("utf-8")


def test_state_endpoint_returns_503_error_envelope_when_snapshot_is_missing() -> None:
    response = Client().get("/api/v1/state")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "unavailable",
            "message": f"Runtime snapshot is unavailable at {get_runtime_snapshot_path()}.",
        }
    }


def test_state_endpoint_reads_snapshot_written_by_orchestrator(tmp_path: Path) -> None:
    orchestrator = Orchestrator(
        config=build_config(tmp_path=tmp_path),
        tracker_client=SilentTrackerClient(),
    )

    async def run_test() -> None:
        try:
            await orchestrator.startup()
            clear_runtime_snapshot_provider(orchestrator)

            response = Client().get("/api/v1/state")

            assert response.status_code == 200
            assert response.json()["counts"] == {"running": 0, "retrying": 0}
            assert response.json()["revision"] >= 1
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_state_endpoint_reads_default_snapshot_path_across_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYMPHONY_RUNTIME_SNAPSHOT_PATH", raising=False)
    monkeypatch.setattr("symphony.observability.runtime.os.getpid", lambda: 111)

    orchestrator = Orchestrator(
        config=build_config(tmp_path=tmp_path),
        tracker_client=SilentTrackerClient(),
    )

    async def run_test() -> None:
        try:
            await orchestrator.startup()
            clear_runtime_snapshot_provider(orchestrator)
            monkeypatch.setattr("symphony.observability.runtime.os.getpid", lambda: 222)

            response = Client().get("/api/v1/state")

            assert response.status_code == 200
            assert response.json()["counts"] == {"running": 0, "retrying": 0}
            assert response.json()["revision"] >= 1
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_state_and_issue_endpoints_read_plane_backed_snapshot_from_orchestrator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = RecordingPlaneTransport(
        responses=[
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps({"count": 0, "next_cursor": None, "results": []}),
            ),
            PlaneTransportResponse(
                status_code=200,
                body=json.dumps(
                    {
                        "count": 1,
                        "next_cursor": None,
                        "results": [
                            make_plane_issue_payload(
                                issue_id="plane-issue-7",
                                sequence_id=7,
                                state_id="state-progress",
                                state_name="In Progress",
                            )
                        ],
                    }
                ),
            ),
        ]
    )
    monkeypatch.setattr("symphony.tracker.plane_client._default_plane_transport", transport)

    async def successful_worker_runner(**kwargs: object) -> AttemptResult:
        issue = cast(Issue, kwargs["issue"])
        return AttemptResult(
            status="succeeded",
            issue=issue,
            attempt=None,
            workspace_path=tmp_path / "workspaces" / issue.identifier,
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            turns_run=1,
            error_code=None,
            message=None,
        )

    orchestrator = Orchestrator(
        config=build_plane_config(tmp_path=tmp_path),
        worker_runner=successful_worker_runner,
    )

    async def run_test() -> None:
        try:
            assert isinstance(orchestrator.tracker_client, PlaneTrackerClient)

            await orchestrator.run_once()
            await orchestrator.wait_for_running_workers()
            clear_runtime_snapshot_provider(orchestrator)

            state_response = Client().get("/api/v1/state")
            assert state_response.status_code == 200
            state_payload = state_response.json()
            assert state_payload["counts"] == {"running": 0, "retrying": 1}
            assert state_payload["retrying"] == [
                {
                    "issue_id": "plane-issue-7",
                    "issue_identifier": "ENG-7",
                    "attempt": 1,
                    "due_at": state_payload["retrying"][0]["due_at"],
                    "error": None,
                    "workspace_path": str(tmp_path / "workspaces" / "ENG-7"),
                }
            ]

            issue_response = Client().get("/api/v1/ENG-7")
            assert issue_response.status_code == 200
            issue_payload = issue_response.json()
            assert issue_payload["revision"] == state_payload["revision"]
            assert isinstance(issue_payload["generated_at"], str)
            assert issue_payload["expires_at"] == state_payload["expires_at"]
            assert issue_payload["issue_identifier"] == "ENG-7"
            assert issue_payload["issue_id"] == "plane-issue-7"
            assert issue_payload["status"] == "retrying"
            assert issue_payload["workspace"] == {"path": str(tmp_path / "workspaces" / "ENG-7")}
            assert issue_payload["attempts"] == {"restart_count": 0, "current_retry_attempt": 1}
            assert issue_payload["running"] is None
            assert issue_payload["retry"] == {
                "attempt": 1,
                "due_at": state_payload["retrying"][0]["due_at"],
                "error": None,
            }
            assert issue_payload["logs"] == {"codex_session_logs": []}
            assert issue_payload["recent_events"] == []
            assert issue_payload["last_error"] is None
            assert issue_payload["tracked"] == {}
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_state_endpoint_rejects_post_with_405_error_envelope() -> None:
    response = Client(enforce_csrf_checks=True).post("/api/v1/state", data={})

    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method 'POST' is not allowed for /api/v1/state.",
        }
    }


def test_refresh_endpoint_queues_runtime_refresh_request() -> None:
    response = Client().post("/api/v1/refresh", data={})

    assert response.status_code == 202
    payload = response.json()
    assert payload["queued"] is True
    assert payload["coalesced"] is False
    assert payload["operations"] == ["poll", "reconcile"]
    assert isinstance(payload["requested_at"], str)
    assert get_runtime_refresh_request_path().is_file()

    consumed_request = consume_runtime_refresh_request()
    assert consumed_request == {
        "requested_at": payload["requested_at"],
        "operations": ["poll", "reconcile"],
    }


def test_refresh_endpoint_publishes_refresh_queued_invalidation_event() -> None:
    response = Client().post("/api/v1/refresh", data={})

    assert response.status_code == 202
    event = wait_for_runtime_invalidation(after_sequence=None, timeout_seconds=0.1)
    assert event is not None
    assert event == {
        "sequence": 1,
        "event": "refresh_queued",
        "emitted_at": event["emitted_at"],
        "queued": True,
        "coalesced": False,
        "requested_at": response.json()["requested_at"],
        "operations": ["poll", "reconcile"],
    }


def test_events_endpoint_streams_runtime_invalidations() -> None:
    publish_runtime_invalidation(
        "snapshot_updated",
        {
            "revision": 7,
            "generated_at": "2026-03-11T11:00:00Z",
            "expires_at": "2026-03-11T11:05:00Z",
        },
    )

    response = Client().get("/api/v1/events")
    try:
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/event-stream")
        chunks = iter(_streaming_content(response))
        assert _stream_chunk_text(next(chunks)) == ": connected\n\n"
        event_chunk = _stream_chunk_text(next(chunks))
        assert "id: 1" in event_chunk
        assert "event: snapshot_updated" in event_chunk
        assert '"revision": 7' in event_chunk
    finally:
        response.close()


def test_events_endpoint_resumes_after_last_event_id_header() -> None:
    publish_runtime_invalidation(
        "snapshot_updated",
        {
            "revision": 4,
            "generated_at": "2026-03-11T11:00:00Z",
            "expires_at": "2026-03-11T11:05:00Z",
        },
    )
    publish_runtime_invalidation(
        "snapshot_updated",
        {
            "revision": 5,
            "generated_at": "2026-03-11T11:01:00Z",
            "expires_at": "2026-03-11T11:06:00Z",
        },
    )

    response = Client().get("/api/v1/events", HTTP_LAST_EVENT_ID="1")
    try:
        assert response.status_code == 200
        chunks = iter(_streaming_content(response))
        assert _stream_chunk_text(next(chunks)) == ": connected\n\n"
        event_chunk = _stream_chunk_text(next(chunks))
        assert "id: 2" in event_chunk
        assert "event: snapshot_updated" in event_chunk
        assert '"revision": 5' in event_chunk
    finally:
        response.close()


def test_events_endpoint_accepts_last_event_id_query_parameter() -> None:
    publish_runtime_invalidation(
        "snapshot_updated",
        {
            "revision": 2,
            "generated_at": "2026-03-11T11:00:00Z",
            "expires_at": "2026-03-11T11:05:00Z",
        },
    )
    publish_runtime_invalidation(
        "issue_changed",
        {
            "revision": 3,
            "issue_identifiers": ["SYM-123"],
        },
    )

    response = Client().get("/api/v1/events?lastEventId=1")
    try:
        assert response.status_code == 200
        chunks = iter(_streaming_content(response))
        assert _stream_chunk_text(next(chunks)) == ": connected\n\n"
        event_chunk = _stream_chunk_text(next(chunks))
        assert "id: 2" in event_chunk
        assert "event: issue_changed" in event_chunk
        assert '"issue_identifiers": ["SYM-123"]' in event_chunk
        assert '"revision": 3' in event_chunk
    finally:
        response.close()


def test_events_endpoint_emits_keepalive_when_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("symphony.api.views.RUNTIME_EVENTS_KEEPALIVE_SECONDS", 0.0)

    response = Client().get("/api/v1/events")
    try:
        assert response.status_code == 200
        chunks = iter(_streaming_content(response))
        assert _stream_chunk_text(next(chunks)) == ": connected\n\n"
        assert _stream_chunk_text(next(chunks)) == ": keepalive\n\n"
    finally:
        response.close()


def test_events_endpoint_rejects_post_with_405_error_envelope() -> None:
    response = Client().post("/api/v1/events", data={})

    assert response.status_code == 405
    assert response["Allow"] == "GET"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method 'POST' is not allowed for /api/v1/events.",
        }
    }


def test_refresh_endpoint_is_csrf_exempt_for_api_clients() -> None:
    response = Client(enforce_csrf_checks=True).post("/api/v1/refresh", data={})

    assert response.status_code == 202
    assert response.json()["queued"] is True


def test_refresh_endpoint_coalesces_repeated_requests() -> None:
    first_response = Client().post("/api/v1/refresh", data={})
    second_response = Client().post("/api/v1/refresh", data={})

    assert first_response.status_code == 202
    assert second_response.status_code == 202
    assert first_response.json()["coalesced"] is False
    assert second_response.json()["coalesced"] is True

    # Coalesced response reflects the existing (first) request, not a new timestamp.
    assert second_response.json()["requested_at"] == first_response.json()["requested_at"]
    assert second_response.json()["operations"] == first_response.json()["operations"]

    consumed_request = consume_runtime_refresh_request()
    assert consumed_request is not None
    assert consumed_request["requested_at"] == first_response.json()["requested_at"]


def test_refresh_endpoint_rejects_get_with_405_error_envelope() -> None:
    response = Client().get("/api/v1/refresh")

    assert response.status_code == 405
    assert response["Allow"] == "POST"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method 'GET' is not allowed for /api/v1/refresh.",
        }
    }


def test_issue_endpoint_returns_503_error_envelope_when_snapshot_is_missing() -> None:
    response = Client().get("/api/v1/SYM-123")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "unavailable",
            "message": f"Runtime snapshot is unavailable at {get_runtime_snapshot_path()}.",
        }
    }


def test_issue_endpoint_returns_running_issue_details() -> None:
    snapshot_times = fresh_snapshot_times(revision=7)
    publish_runtime_snapshot(
        {
            **snapshot_times,
            "counts": {"running": 1, "retrying": 0},
            "running": [
                {
                    "issue_id": "issue-123",
                    "issue_identifier": "SYM-123",
                    "attempt": 2,
                    "state": "In Progress",
                    "session_id": "thread-1-turn-2",
                    "turn_count": 7,
                    "last_event": "notification",
                    "last_message": "Working on tests",
                    "started_at": "2026-03-10T09:55:00Z",
                    "last_event_at": "2026-03-10T09:59:30Z",
                    "workspace_path": "/tmp/symphony/SYM-123",
                    "tokens": {
                        "input_tokens": 1200,
                        "output_tokens": 800,
                        "total_tokens": 2000,
                    },
                }
            ],
            "retrying": [],
            "codex_totals": {
                "input_tokens": 1200,
                "output_tokens": 800,
                "total_tokens": 2000,
                "seconds_running": 300.0,
            },
            "rate_limits": None,
        }
    )

    response = Client().get("/api/v1/SYM-123")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 7
    assert isinstance(payload["generated_at"], str)
    assert payload["expires_at"] == snapshot_times["expires_at"]
    assert payload["issue_identifier"] == "SYM-123"
    assert payload["issue_id"] == "issue-123"
    assert payload["status"] == "running"
    assert payload["workspace"] == {"path": "/tmp/symphony/SYM-123"}
    assert payload["attempts"] == {
        "restart_count": 1,
        "current_retry_attempt": 2,
    }
    assert payload["running"] == {
        "session_id": "thread-1-turn-2",
        "turn_count": 7,
        "state": "In Progress",
        "started_at": "2026-03-10T09:55:00Z",
        "last_event": "notification",
        "last_message": "Working on tests",
        "last_event_at": "2026-03-10T09:59:30Z",
        "tokens": {
            "input_tokens": 1200,
            "output_tokens": 800,
            "total_tokens": 2000,
        },
    }
    assert payload["retry"] is None
    assert payload["logs"] == {"codex_session_logs": []}
    assert payload["recent_events"] == [
        {
            "at": "2026-03-10T09:59:30Z",
            "event": "notification",
            "message": "Working on tests",
        }
    ]
    assert payload["last_error"] is None
    assert payload["tracked"] == {}


def test_issue_endpoint_returns_retry_issue_details() -> None:
    snapshot_times = fresh_snapshot_times(revision=4)
    publish_runtime_snapshot(
        {
            **snapshot_times,
            "counts": {"running": 0, "retrying": 1},
            "running": [],
            "retrying": [
                {
                    "issue_id": "issue-456",
                    "issue_identifier": "SYM-456",
                    "attempt": 3,
                    "due_at": "2026-03-10T10:01:00Z",
                    "error": "no available orchestrator slots",
                    "workspace_path": "/tmp/symphony/SYM-456",
                }
            ],
            "codex_totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "seconds_running": 0.0,
            },
            "rate_limits": None,
        }
    )

    response = Client().get("/api/v1/SYM-456")

    assert response.status_code == 200
    payload = response.json()
    assert payload["revision"] == 4
    assert isinstance(payload["generated_at"], str)
    assert payload["expires_at"] == snapshot_times["expires_at"]
    assert payload["issue_identifier"] == "SYM-456"
    assert payload["issue_id"] == "issue-456"
    assert payload["status"] == "retrying"
    assert payload["workspace"] == {"path": "/tmp/symphony/SYM-456"}
    assert payload["attempts"] == {
        "restart_count": 2,
        "current_retry_attempt": 3,
    }
    assert payload["running"] is None
    assert payload["retry"] == {
        "attempt": 3,
        "due_at": "2026-03-10T10:01:00Z",
        "error": "no available orchestrator slots",
    }
    assert payload["logs"] == {"codex_session_logs": []}
    assert payload["recent_events"] == []
    assert payload["last_error"] == "no available orchestrator slots"
    assert payload["tracked"] == {}


def test_issue_endpoint_returns_404_for_unknown_issue_in_snapshot() -> None:
    publish_runtime_snapshot(
        {
            **fresh_snapshot_times(),
            "counts": {"running": 0, "retrying": 0},
            "running": [],
            "retrying": [],
            "codex_totals": {
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "seconds_running": 0.0,
            },
            "rate_limits": None,
        }
    )

    response = Client().get("/api/v1/SYM-999")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "issue_not_found",
            "message": "Issue 'SYM-999' is not present in the current runtime snapshot.",
        }
    }


def test_issue_endpoint_rejects_post_with_405_error_envelope() -> None:
    response = Client(enforce_csrf_checks=True).post("/api/v1/SYM-123", data={})

    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method 'POST' is not allowed for /api/v1/SYM-123.",
        }
    }


def test_state_endpoint_uses_live_provider_when_snapshot_file_is_missing(tmp_path: Path) -> None:
    orchestrator = Orchestrator(
        config=build_config(tmp_path=tmp_path),
        tracker_client=SilentTrackerClient(),
    )

    async def run_test() -> None:
        try:
            await orchestrator.startup()
            clear_runtime_snapshot_file()
            response = Client().get("/api/v1/state")

            assert response.status_code == 200
            assert response.json()["counts"] == {"running": 0, "retrying": 0}
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_state_endpoint_rejects_stale_snapshot_files() -> None:
    snapshot_path = get_runtime_snapshot_path()
    snapshot_path.write_text(
        json.dumps(
            {
                "generated_at": "2026-03-10T00:00:00Z",
                "expires_at": "2026-03-10T00:00:01Z",
                "counts": {"running": 0, "retrying": 0},
                "running": [],
                "retrying": [],
                "codex_totals": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "seconds_running": 0.0,
                },
                "rate_limits": None,
            }
        ),
        encoding="utf-8",
    )

    response = Client().get("/api/v1/state")

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "unavailable",
            "message": (
                f"Runtime snapshot at {snapshot_path} is stale (expired at 2026-03-10T00:00:01Z)."
            ),
        }
    }


def test_runtime_snapshot_default_path_uses_shared_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYMPHONY_RUNTIME_SNAPSHOT_PATH", raising=False)

    path = get_runtime_snapshot_path()

    assert path.parent == Path(tempfile.gettempdir())
    assert path.name.startswith(f"{Path(DEFAULT_RUNTIME_SNAPSHOT_FILENAME).stem}-")
    assert path.suffix == Path(DEFAULT_RUNTIME_SNAPSHOT_FILENAME).suffix


def test_runtime_refresh_request_default_path_uses_shared_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH", raising=False)

    path = get_runtime_refresh_request_path()

    assert path.parent == Path(tempfile.gettempdir())
    assert path.name.startswith(f"{Path(DEFAULT_RUNTIME_REFRESH_REQUEST_FILENAME).stem}-")
    assert path.suffix == Path(DEFAULT_RUNTIME_REFRESH_REQUEST_FILENAME).suffix


def test_consume_runtime_refresh_request_returns_none_when_parent_is_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_path = tmp_path / "missing" / "runtime-refresh.json"
    monkeypatch.setenv("SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH", str(missing_path))

    assert consume_runtime_refresh_request() is None


def test_runtime_snapshot_default_path_is_namespaced_per_installation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SYMPHONY_RUNTIME_SNAPSHOT_PATH", raising=False)
    monkeypatch.setattr(
        "symphony.observability.runtime._resolve_runtime_snapshot_scope_root",
        lambda: Path("/tmp/checkout-a"),
    )
    path_a = get_runtime_snapshot_path()

    monkeypatch.setattr(
        "symphony.observability.runtime._resolve_runtime_snapshot_scope_root",
        lambda: Path("/tmp/checkout-b"),
    )
    path_b = get_runtime_snapshot_path()

    assert path_a != path_b
    assert path_a.parent == path_b.parent == Path(tempfile.gettempdir())


def test_publish_runtime_snapshot_wraps_invalid_path_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_parent = tmp_path / "snapshot-parent"
    invalid_parent.write_text("not a directory", encoding="utf-8")
    invalid_path = invalid_parent / "runtime-snapshot.json"
    monkeypatch.setenv("SYMPHONY_RUNTIME_SNAPSHOT_PATH", str(invalid_path))

    with pytest.raises(
        RuntimeSnapshotUnavailableError,
        match="Runtime snapshot could not be written",
    ):
        publish_runtime_snapshot(
            {
                "generated_at": "2026-03-10T00:00:00Z",
                "expires_at": "2026-03-10T00:02:00Z",
                "counts": {"running": 0, "retrying": 0},
                "running": [],
                "retrying": [],
                "codex_totals": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "seconds_running": 0.0,
                },
                "rate_limits": None,
            }
        )


def _clear_snapshot_file_best_effort() -> None:
    try:
        clear_runtime_snapshot_file()
    except RuntimeSnapshotUnavailableError:
        pass


def _clear_refresh_request_file_best_effort() -> None:
    try:
        clear_runtime_refresh_request_file()
    except RuntimeSnapshotUnavailableError:
        pass


def _clear_recovery_file_best_effort() -> None:
    get_runtime_recovery_path().unlink(missing_ok=True)


def _stream_chunk_text(chunk: bytes | str) -> str:
    if isinstance(chunk, bytes):
        return chunk.decode("utf-8")
    return chunk


def _streaming_content(response: object) -> Any:
    return cast(Any, response).streaming_content
