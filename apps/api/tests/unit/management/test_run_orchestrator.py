from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from symphony.management.commands.run_orchestrator import Orchestrator as CommandOrchestrator

MINIMAL_VALID_WORKFLOW = """---
tracker:
  kind: linear
  api_key: linear-token
  project_slug: symphony
---
# Prompt body
"""


def fake_async_method(calls: list[str], name: str) -> object:
    async def _method(self: object) -> None:
        calls.append(name)

    return _method


def write_workflow(path: Path, *, contents: str = MINIMAL_VALID_WORKFLOW) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def test_run_orchestrator_uses_default_workflow_in_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md")
    stdout = StringIO()
    calls: list[str] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        CommandOrchestrator,
        "run_once",
        fake_async_method(calls, "run_once"),
    )
    monkeypatch.setattr(
        CommandOrchestrator,
        "wait_for_running_workers",
        fake_async_method(calls, "wait_for_running_workers"),
    )
    monkeypatch.setattr(
        CommandOrchestrator,
        "aclose",
        fake_async_method(calls, "aclose"),
    )

    call_command("run_orchestrator", "--once", stdout=stdout)

    output = stdout.getvalue()
    assert f"Loaded workflow definition from {workflow_path}" in output
    assert "Orchestrator tick completed." in output
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_uses_explicit_workflow_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md")
    explicit_path = write_workflow(
        tmp_path / "custom-workflow.md",
        contents=MINIMAL_VALID_WORKFLOW.replace("symphony", "explicit-project"),
    )
    stdout = StringIO()
    calls: list[str] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        CommandOrchestrator,
        "run_once",
        fake_async_method(calls, "run_once"),
    )
    monkeypatch.setattr(
        CommandOrchestrator,
        "wait_for_running_workers",
        fake_async_method(calls, "wait_for_running_workers"),
    )
    monkeypatch.setattr(
        CommandOrchestrator,
        "aclose",
        fake_async_method(calls, "aclose"),
    )

    call_command("run_orchestrator", str(explicit_path), "--once", stdout=stdout)

    assert f"Loaded workflow definition from {explicit_path}" in stdout.getvalue()
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_runs_forever_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md")
    stdout = StringIO()
    calls: list[str] = []

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        CommandOrchestrator,
        "run_forever",
        fake_async_method(calls, "run_forever"),
    )
    monkeypatch.setattr(
        CommandOrchestrator,
        "aclose",
        fake_async_method(calls, "aclose"),
    )

    call_command("run_orchestrator", stdout=stdout)

    assert "Orchestrator stopped." in stdout.getvalue()
    assert calls == ["run_forever", "aclose"]


def test_run_orchestrator_fails_when_default_workflow_is_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match=r"Startup failed \(missing_workflow_file\):"):
        call_command("run_orchestrator")


def test_run_orchestrator_fails_when_explicit_workflow_is_missing(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing-workflow.md"

    with pytest.raises(CommandError, match=r"Startup failed \(missing_workflow_file\):"):
        call_command("run_orchestrator", str(missing_path))


def test_run_orchestrator_surfaces_workflow_parse_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(
        tmp_path / "WORKFLOW.md",
        contents="---\ntracker: [unterminated\n---\n# Prompt body\n",
    )

    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match=r"Startup failed \(workflow_parse_error\):"):
        call_command("run_orchestrator")


def test_run_orchestrator_surfaces_config_validation_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(
        tmp_path / "WORKFLOW.md",
        contents="""---
tracker:
  kind: github
---
# Prompt body
""",
    )

    monkeypatch.chdir(tmp_path)

    with pytest.raises(CommandError, match=r"Startup failed \(unsupported_tracker_kind\):"):
        call_command("run_orchestrator")
