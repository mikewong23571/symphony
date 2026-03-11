from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest
from symphony.workflow import UnsupportedTrackerKindError, WorkflowRuntime


def write_workflow(
    path: Path,
    *,
    prompt_template: str = "Prompt body",
    poll_interval_ms: int = 30_000,
) -> Path:
    path.write_text(
        (
            "---\n"
            "tracker:\n"
            "  kind: linear\n"
            "  api_key: linear-token\n"
            "  project_slug: symphony\n"
            "polling:\n"
            f"  interval_ms: {poll_interval_ms}\n"
            "---\n"
            f"{prompt_template}\n"
        ),
        encoding="utf-8",
    )
    return path


def write_plane_workflow(path: Path, *, prompt_template: str = "Prompt body") -> Path:
    path.write_text(
        (
            "---\n"
            "tracker:\n"
            "  kind: plane\n"
            "  api_base_url: https://plane.example\n"
            "  api_key: plane-token\n"
            "  workspace_slug: workspace\n"
            "  project_id: project-123\n"
            "---\n"
            f"{prompt_template}\n"
        ),
        encoding="utf-8",
    )
    return path


def test_workflow_runtime_reloads_changed_workflow_file(tmp_path: Path) -> None:
    workflow_path = write_workflow(
        tmp_path / "WORKFLOW.md",
        prompt_template="Prompt body v1",
        poll_interval_ms=30_000,
    )
    runtime = WorkflowRuntime(workflow_path)

    initial_config = runtime.load_initial()
    write_workflow(
        workflow_path,
        prompt_template="Prompt body v2",
        poll_interval_ms=1_234,
    )

    changed = runtime.reload_if_changed()

    assert changed is True
    assert initial_config.prompt_template == "Prompt body v1"
    assert runtime.config.prompt_template == "Prompt body v2"
    assert runtime.config.polling.interval_ms == 1_234
    assert runtime.last_error is None


def test_workflow_runtime_preserves_last_good_config_when_reload_is_invalid(tmp_path: Path) -> None:
    workflow_path = write_workflow(
        tmp_path / "WORKFLOW.md",
        prompt_template="Prompt body v1",
        poll_interval_ms=30_000,
    )
    runtime = WorkflowRuntime(workflow_path)
    runtime.load_initial()

    workflow_path.write_text(
        "---\ntracker: [unterminated\n---\nPrompt body invalid\n",
        encoding="utf-8",
    )

    changed = runtime.reload_if_changed()

    assert changed is False
    assert runtime.config.prompt_template == "Prompt body v1"
    assert runtime.config.polling.interval_ms == 30_000
    assert runtime.last_error is not None
    assert runtime.last_error.code == "workflow_parse_error"

    write_workflow(
        workflow_path,
        prompt_template="Prompt body v2",
        poll_interval_ms=2_468,
    )

    recovered = runtime.reload_if_changed()

    assert recovered is True
    assert runtime.config.prompt_template == "Prompt body v2"
    assert runtime.config.polling.interval_ms == 2_468
    assert runtime.last_error is None


def test_workflow_runtime_detects_same_size_edits_with_restored_mtime(tmp_path: Path) -> None:
    workflow_path = write_workflow(
        tmp_path / "WORKFLOW.md",
        prompt_template="Prompt body a",
    )
    runtime = WorkflowRuntime(workflow_path)
    runtime.load_initial()
    initial_stat = workflow_path.stat()

    write_workflow(
        workflow_path,
        prompt_template="Prompt body b",
    )
    os.utime(
        workflow_path,
        ns=(initial_stat.st_atime_ns, initial_stat.st_mtime_ns),
    )

    changed = runtime.reload_if_changed()

    assert changed is True
    assert runtime.config.prompt_template == "Prompt body b"


def test_workflow_runtime_does_not_reparse_unchanged_invalid_file(tmp_path: Path) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md")
    runtime = WorkflowRuntime(workflow_path)
    runtime.load_initial()

    workflow_path.write_text(
        "---\ntracker: [unterminated\n---\nPrompt body invalid\n",
        encoding="utf-8",
    )

    first_changed = runtime.reload_if_changed()
    first_error = runtime.last_error
    second_changed = runtime.reload_if_changed()
    second_error = runtime.last_error

    assert first_changed is False
    assert second_changed is False
    assert first_error is not None
    assert second_error is not None
    assert first_error.code == "workflow_parse_error"
    assert second_error.observed_at == first_error.observed_at


def test_workflow_runtime_requires_explicit_initial_load(tmp_path: Path) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md")
    runtime = WorkflowRuntime(workflow_path)

    with pytest.raises(RuntimeError, match="has not loaded a service config yet"):
        runtime.reload_if_changed()


def test_workflow_runtime_rejects_fully_populated_plane_configs_until_supported(
    tmp_path: Path,
) -> None:
    workflow_path = write_plane_workflow(tmp_path / "WORKFLOW.md")
    runtime = WorkflowRuntime(workflow_path)

    with pytest.raises(
        UnsupportedTrackerKindError,
        match="tracker.kind must be set to the supported tracker kind 'linear'.",
    ):
        runtime.load_initial()


def test_workflow_runtime_watches_for_file_changes(tmp_path: Path) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md", prompt_template="Prompt body v1")
    runtime = WorkflowRuntime(workflow_path)
    listener_called = threading.Event()
    runtime.load_initial()
    runtime.add_reload_listener(listener_called.set)
    runtime.start_watching(interval_seconds=0.05)

    try:
        write_workflow(workflow_path, prompt_template="Prompt body v2", poll_interval_ms=1_234)

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if listener_called.wait(timeout=0.05):
                break

        assert listener_called.is_set()
        assert runtime.config.prompt_template == "Prompt body v2"
        assert runtime.config.polling.interval_ms == 1_234
    finally:
        runtime.stop_watching()


def test_workflow_runtime_removes_bound_method_listeners(tmp_path: Path) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md")
    runtime = WorkflowRuntime(workflow_path)
    runtime.load_initial()
    watcher_fired = threading.Event()

    class ListenerOwner:
        def __init__(self) -> None:
            self.calls = 0

        def on_reload(self) -> None:
            self.calls += 1

    listener_owner = ListenerOwner()
    runtime.add_reload_listener(listener_owner.on_reload)
    runtime.remove_reload_listener(listener_owner.on_reload)
    runtime.add_reload_listener(watcher_fired.set)

    runtime.start_watching(interval_seconds=0.05)
    try:
        write_workflow(workflow_path, prompt_template="Prompt body v2")
        assert watcher_fired.wait(timeout=2.0) is True
        assert listener_owner.calls == 0
    finally:
        runtime.stop_watching()
