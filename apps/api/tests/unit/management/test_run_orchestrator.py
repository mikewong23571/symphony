from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

MINIMAL_VALID_WORKFLOW = """---
tracker:
  kind: linear
  api_key: linear-token
  project_slug: symphony
---
# Prompt body
"""


def write_workflow(path: Path, *, contents: str = MINIMAL_VALID_WORKFLOW) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def test_run_orchestrator_uses_default_workflow_in_cwd(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workflow_path = write_workflow(tmp_path / "WORKFLOW.md")
    stdout = StringIO()

    monkeypatch.chdir(tmp_path)

    call_command("run_orchestrator", stdout=stdout)

    output = stdout.getvalue()
    assert f"Loaded workflow definition from {workflow_path}" in output
    assert "Orchestrator skeleton created. Implementation is pending." in output


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

    monkeypatch.chdir(tmp_path)

    call_command("run_orchestrator", str(explicit_path), stdout=stdout)

    assert f"Loaded workflow definition from {explicit_path}" in stdout.getvalue()


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
