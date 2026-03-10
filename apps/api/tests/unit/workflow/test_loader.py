from __future__ import annotations

from pathlib import Path

import pytest
from symphony.workflow import (
    WORKFLOW_PATH_ENV_VAR,
    MissingWorkflowFileError,
    WorkflowFrontMatterNotAMapError,
    WorkflowParseError,
    load_workflow_definition,
    parse_workflow_definition,
    resolve_workflow_path,
)


def test_resolve_workflow_path_defaults_to_workflow_md_in_cwd(tmp_path: Path) -> None:
    assert resolve_workflow_path(cwd=tmp_path) == tmp_path / "WORKFLOW.md"


def test_resolve_workflow_path_uses_env_var_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WORKFLOW_PATH_ENV_VAR, "configs/runtime-workflow.md")

    assert resolve_workflow_path(cwd=tmp_path) == tmp_path / "configs/runtime-workflow.md"


def test_resolve_workflow_path_explicit_argument_overrides_env_var(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(WORKFLOW_PATH_ENV_VAR, "configs/runtime-workflow.md")

    assert resolve_workflow_path("WORKFLOW.md", cwd=tmp_path) == tmp_path / "WORKFLOW.md"


def test_resolve_workflow_path_uses_explicit_relative_path(tmp_path: Path) -> None:
    assert resolve_workflow_path("configs/project-workflow.md", cwd=tmp_path) == (
        tmp_path / "configs/project-workflow.md"
    )


def test_resolve_workflow_path_preserves_explicit_absolute_path(tmp_path: Path) -> None:
    absolute_path = tmp_path / "nested" / "WORKFLOW.md"

    assert resolve_workflow_path(absolute_path, cwd=Path("/ignored")) == absolute_path


def test_load_workflow_definition_reads_from_disk(tmp_path: Path) -> None:
    workflow_path = tmp_path / "WORKFLOW.md"
    workflow_path.write_text("# Prompt body\n", encoding="utf-8")

    definition = load_workflow_definition(cwd=tmp_path)

    assert definition.config == {}
    assert definition.prompt_template == "# Prompt body"


def test_load_workflow_definition_uses_env_workflow_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workflow_path = tmp_path / "configs" / "runtime-workflow.md"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text("# Runtime prompt body\n", encoding="utf-8")
    monkeypatch.setenv(WORKFLOW_PATH_ENV_VAR, "configs/runtime-workflow.md")

    definition = load_workflow_definition(cwd=tmp_path)

    assert definition.config == {}
    assert definition.prompt_template == "# Runtime prompt body"


def test_load_workflow_definition_raises_typed_error_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MissingWorkflowFileError, match="Could not read workflow file"):
        load_workflow_definition(cwd=tmp_path)


def test_parse_workflow_definition_without_front_matter_uses_empty_config() -> None:
    definition = parse_workflow_definition("\n# Prompt body\n")

    assert definition.config == {}
    assert definition.prompt_template == "# Prompt body"


def test_parse_workflow_definition_splits_yaml_front_matter_and_trimmed_body() -> None:
    definition = parse_workflow_definition(
        """---
tracker:
  kind: linear
  project_slug: symphony
---

# Prompt body

Extra details.
"""
    )

    assert definition.config == {"tracker": {"kind": "linear", "project_slug": "symphony"}}
    assert definition.prompt_template == "# Prompt body\n\nExtra details."


def test_parse_workflow_definition_supports_empty_front_matter_map() -> None:
    definition = parse_workflow_definition(
        """---
---
# Prompt body
"""
    )

    assert definition.config == {}
    assert definition.prompt_template == "# Prompt body"


def test_parse_workflow_definition_raises_for_missing_closing_delimiter() -> None:
    with pytest.raises(
        WorkflowParseError,
        match="Workflow front matter is missing a closing '---' delimiter.",
    ):
        parse_workflow_definition("---\ntracker:\n  kind: linear\n")


def test_parse_workflow_definition_raises_for_invalid_yaml() -> None:
    with pytest.raises(
        WorkflowParseError,
        match="Workflow front matter could not be parsed as YAML.",
    ):
        parse_workflow_definition("---\ntracker: [unterminated\n---\n# Prompt body\n")


def test_parse_workflow_definition_raises_for_non_mapping_front_matter() -> None:
    with pytest.raises(
        WorkflowFrontMatterNotAMapError,
        match="Workflow front matter must decode to a mapping.",
    ):
        parse_workflow_definition("---\n- linear\n---\n# Prompt body\n")
