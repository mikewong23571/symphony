from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

WORKFLOW_PATH_ENV_VAR = "SYMPHONY_WORKFLOW_PATH"


class WorkflowError(Exception):
    code = "workflow_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class MissingWorkflowFileError(WorkflowError):
    code = "missing_workflow_file"


class WorkflowParseError(WorkflowError):
    code = "workflow_parse_error"


class WorkflowFrontMatterNotAMapError(WorkflowError):
    code = "workflow_front_matter_not_a_map"


@dataclass(slots=True, frozen=True)
class WorkflowDefinition:
    config: dict[str, Any]
    prompt_template: str


def resolve_workflow_path(
    workflow_path: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path:
    base_dir = cwd or Path.cwd()
    if workflow_path is None:
        configured_path = os.environ.get(WORKFLOW_PATH_ENV_VAR, "").strip()
        candidate = Path(configured_path) if configured_path else Path("WORKFLOW.md")
    else:
        candidate = Path(workflow_path)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate


def load_workflow_definition(
    workflow_path: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> WorkflowDefinition:
    path = resolve_workflow_path(workflow_path, cwd=cwd)
    try:
        contents = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise MissingWorkflowFileError(f"Could not read workflow file: {path}") from exc
    return parse_workflow_definition(contents)


def parse_workflow_definition(contents: str) -> WorkflowDefinition:
    if not contents.startswith("---"):
        return WorkflowDefinition(config={}, prompt_template=contents.strip())

    lines = contents.splitlines()
    if not lines or lines[0] != "---":
        return WorkflowDefinition(config={}, prompt_template=contents.strip())

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line == "---"),
        None,
    )
    if closing_index is None:
        raise WorkflowParseError("Workflow front matter is missing a closing '---' delimiter.")

    front_matter = "\n".join(lines[1:closing_index])
    body = "\n".join(lines[closing_index + 1 :]).strip()

    try:
        parsed = yaml.safe_load(front_matter)
    except yaml.YAMLError as exc:
        raise WorkflowParseError("Workflow front matter could not be parsed as YAML.") from exc

    if parsed is None:
        config: dict[str, Any] = {}
    elif isinstance(parsed, dict):
        config = parsed
    else:
        raise WorkflowFrontMatterNotAMapError("Workflow front matter must decode to a mapping.")

    return WorkflowDefinition(config=config, prompt_template=body)
