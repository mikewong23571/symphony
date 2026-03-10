from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Generator, Sequence
from pathlib import Path

import pytest
from django.test import Client
from symphony.observability.runtime import (
    DEFAULT_RUNTIME_SNAPSHOT_FILENAME,
    RuntimeSnapshotUnavailableError,
    clear_runtime_snapshot_file,
    clear_runtime_snapshot_provider,
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
    yield
    clear_runtime_snapshot_provider()
    _clear_snapshot_file_best_effort()


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
    response = Client().post("/api/v1/state", data={})

    assert response.status_code == 405
    assert response["Allow"] == "GET, HEAD"
    assert response.json() == {
        "error": {
            "code": "method_not_allowed",
            "message": "Method 'POST' is not allowed for /api/v1/state.",
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
