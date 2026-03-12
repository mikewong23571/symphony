from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import TypedDict

import pytest
from symphony.workflow import (
    MissingTrackerAPIBaseURLError,
    MissingTrackerAPIKeyError,
    MissingTrackerProjectIDError,
    MissingTrackerWorkspaceSlugError,
    PlaneTrackerConfig,
    WorkflowRuntime,
)


class PlaneWorkflowOverrides(TypedDict, total=False):
    api_base_url: str | None
    api_key: str | None
    workspace_slug: str | None
    project_id: str | None


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


def write_plane_workflow(
    path: Path,
    *,
    prompt_template: str = "Prompt body",
    api_base_url: str | None = "https://plane.example",
    api_key: str | None = "plane-token",
    workspace_slug: str | None = "workspace",
    project_id: str | None = "project-123",
) -> Path:
    lines = ["---", "tracker:", "  kind: plane"]
    if api_base_url is not None:
        lines.append(f"  api_base_url: {api_base_url}")
    if api_key is not None:
        lines.append(f"  api_key: {api_key}")
    if workspace_slug is not None:
        lines.append(f"  workspace_slug: {workspace_slug}")
    if project_id is not None:
        lines.append(f"  project_id: {project_id}")
    lines.extend(["---", prompt_template, ""])
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_plane_workflow_with_overrides(
    path: Path,
    *,
    prompt_template: str = "Prompt body",
    overrides: PlaneWorkflowOverrides,
) -> Path:
    return write_plane_workflow(
        path,
        prompt_template=prompt_template,
        api_base_url=overrides.get("api_base_url", "https://plane.example"),
        api_key=overrides.get("api_key", "plane-token"),
        workspace_slug=overrides.get("workspace_slug", "workspace"),
        project_id=overrides.get("project_id", "project-123"),
    )


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


def test_workflow_runtime_loads_fully_populated_plane_config(tmp_path: Path) -> None:
    workflow_path = write_plane_workflow(tmp_path / "WORKFLOW.md")
    runtime = WorkflowRuntime(workflow_path)

    config = runtime.load_initial()

    assert isinstance(config.tracker, PlaneTrackerConfig)
    assert config.tracker.workspace_slug == "workspace"


@pytest.mark.parametrize(
    ("overrides", "error_type", "message"),
    [
        (
            {"api_base_url": None},
            MissingTrackerAPIBaseURLError,
            "tracker.api_base_url is required when tracker.kind is 'plane'.",
        ),
        (
            {"api_key": None},
            MissingTrackerAPIKeyError,
            "tracker.api_key is required when tracker.kind is 'plane'.",
        ),
        (
            {"workspace_slug": None},
            MissingTrackerWorkspaceSlugError,
            "tracker.workspace_slug is required when tracker.kind is 'plane'.",
        ),
        (
            {"project_id": None},
            MissingTrackerProjectIDError,
            "tracker.project_id is required when tracker.kind is 'plane'.",
        ),
    ],
)
def test_workflow_runtime_surfaces_plane_validation_errors_on_initial_load(
    tmp_path: Path,
    overrides: PlaneWorkflowOverrides,
    error_type: type[Exception],
    message: str,
) -> None:
    workflow_path = write_plane_workflow_with_overrides(
        tmp_path / "WORKFLOW.md",
        overrides=overrides,
    )
    runtime = WorkflowRuntime(workflow_path)

    with pytest.raises(
        error_type,
        match=re.escape(message),
    ):
        runtime.load_initial()


@pytest.mark.parametrize(
    ("overrides", "error_code"),
    [
        ({"api_base_url": None}, "missing_tracker_api_base_url"),
        ({"api_key": None}, "missing_tracker_api_key"),
        ({"workspace_slug": None}, "missing_tracker_workspace_slug"),
        ({"project_id": None}, "missing_tracker_project_id"),
    ],
)
def test_workflow_runtime_preserves_last_good_config_when_plane_reload_is_invalid(
    tmp_path: Path,
    overrides: PlaneWorkflowOverrides,
    error_code: str,
) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md", prompt_template="Prompt body v1")
    runtime = WorkflowRuntime(workflow_path)
    runtime.load_initial()

    write_plane_workflow_with_overrides(
        workflow_path,
        prompt_template="Prompt body invalid",
        overrides=overrides,
    )

    changed = runtime.reload_if_changed()

    assert changed is False
    assert runtime.config.prompt_template == "Prompt body v1"
    assert runtime.last_error is not None
    assert runtime.last_error.code == error_code


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
