from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Generator, Sequence
from pathlib import Path

import pytest
from django.test import Client
from symphony.observability.runtime import (
    DEFAULT_RUNTIME_REFRESH_REQUEST_FILENAME,
    DEFAULT_RUNTIME_SNAPSHOT_FILENAME,
    RuntimeSnapshotUnavailableError,
    clear_runtime_refresh_request_file,
    clear_runtime_snapshot_file,
    clear_runtime_snapshot_provider,
    consume_runtime_refresh_request,
    get_runtime_refresh_request_path,
    get_runtime_snapshot_path,
    publish_runtime_snapshot,
)
from symphony.orchestrator import Orchestrator
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


@pytest.fixture(autouse=True)
def clear_snapshot_state() -> Generator[None, None, None]:
    clear_runtime_snapshot_provider()
    _clear_snapshot_file_best_effort()
    _clear_refresh_request_file_best_effort()
    yield
    clear_runtime_snapshot_provider()
    _clear_snapshot_file_best_effort()
    _clear_refresh_request_file_best_effort()


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
            "generated_at": "2026-03-10T10:00:00Z",
            "expires_at": "2099-03-10T10:02:00Z",
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
    publish_runtime_snapshot(
        {
            "generated_at": "2026-03-10T10:00:00Z",
            "expires_at": "2099-03-10T10:02:00Z",
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
    assert response.json() == {
        "issue_identifier": "SYM-123",
        "issue_id": "issue-123",
        "status": "running",
        "workspace": {"path": "/tmp/symphony/SYM-123"},
        "attempts": {
            "restart_count": 1,
            "current_retry_attempt": 2,
        },
        "running": {
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
        },
        "retry": None,
        "logs": {"codex_session_logs": []},
        "recent_events": [
            {
                "at": "2026-03-10T09:59:30Z",
                "event": "notification",
                "message": "Working on tests",
            }
        ],
        "last_error": None,
        "tracked": {},
    }


def test_issue_endpoint_returns_retry_issue_details() -> None:
    publish_runtime_snapshot(
        {
            "generated_at": "2026-03-10T10:00:00Z",
            "expires_at": "2099-03-10T10:02:00Z",
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
    assert response.json() == {
        "issue_identifier": "SYM-456",
        "issue_id": "issue-456",
        "status": "retrying",
        "workspace": {"path": "/tmp/symphony/SYM-456"},
        "attempts": {
            "restart_count": 2,
            "current_retry_attempt": 3,
        },
        "running": None,
        "retry": {
            "attempt": 3,
            "due_at": "2026-03-10T10:01:00Z",
            "error": "no available orchestrator slots",
        },
        "logs": {"codex_session_logs": []},
        "recent_events": [],
        "last_error": "no available orchestrator slots",
        "tracked": {},
    }


def test_issue_endpoint_returns_404_for_unknown_issue_in_snapshot() -> None:
    publish_runtime_snapshot(
        {
            "generated_at": "2026-03-10T10:00:00Z",
            "expires_at": "2099-03-10T10:02:00Z",
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
