from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_KEY_PATTERN = re.compile(r"[^A-Za-z0-9._-]")
DEGENERATE_WORKSPACE_KEYS = {"", ".", ".."}


class WorkspaceError(Exception):
    code = "workspace_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class InvalidWorkspaceIdentifierError(WorkspaceError):
    code = "invalid_workspace_identifier"


class WorkspaceRootError(WorkspaceError):
    code = "workspace_root_error"


class WorkspacePathCollisionError(WorkspaceError):
    code = "workspace_path_collision"


class UnsafeWorkspacePathError(WorkspaceError):
    code = "unsafe_workspace_path"


class WorkspaceRemoveError(WorkspaceError):
    code = "workspace_remove_error"


@dataclass(slots=True, frozen=True)
class Workspace:
    path: Path
    workspace_key: str
    created_now: bool


def sanitize_issue_identifier(issue_identifier: str) -> str:
    normalized_identifier = issue_identifier.strip()
    workspace_key = WORKSPACE_KEY_PATTERN.sub("_", normalized_identifier)

    if workspace_key in DEGENERATE_WORKSPACE_KEYS:
        raise InvalidWorkspaceIdentifierError(
            "Issue identifier must resolve to a safe workspace key."
        )

    return workspace_key


@dataclass(slots=True)
class WorkspaceManager:
    root: Path

    def __post_init__(self) -> None:
        self.root = self.root.resolve()

    def resolve_workspace_path(self, issue_identifier: str) -> Path:
        workspace_key = sanitize_issue_identifier(issue_identifier)
        workspace_path = (self.root / workspace_key).resolve(strict=False)
        _ensure_path_within_root(self.root, workspace_path)
        return workspace_path

    def ensure_workspace(self, issue_identifier: str) -> Workspace:
        workspace_key = sanitize_issue_identifier(issue_identifier)
        root = self._ensure_root_directory()
        workspace_path = (root / workspace_key).resolve(strict=False)
        _ensure_path_within_root(root, workspace_path)

        if workspace_path.exists():
            if not workspace_path.is_dir():
                raise WorkspacePathCollisionError(
                    f"Workspace path is not a directory: {workspace_path}"
                )
            return Workspace(path=workspace_path, workspace_key=workspace_key, created_now=False)

        workspace_path.mkdir()
        return Workspace(path=workspace_path, workspace_key=workspace_key, created_now=True)

    def remove_workspace(self, issue_identifier: str) -> bool:
        workspace_path = self.resolve_workspace_path(issue_identifier)
        return self.remove_workspace_path(workspace_path)

    def remove_workspace_path(self, workspace_path: Path) -> bool:
        workspace_path = workspace_path.resolve(strict=False)
        _ensure_path_within_root(self.root, workspace_path)
        if not workspace_path.exists():
            return False

        try:
            if workspace_path.is_dir():
                shutil.rmtree(workspace_path)
            else:
                workspace_path.unlink()
        except OSError as exc:
            raise WorkspaceRemoveError(
                f"Could not remove workspace path: {workspace_path}"
            ) from exc
        return True

    def _ensure_root_directory(self) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise WorkspaceRootError(
                f"Could not create workspace root directory: {self.root}"
            ) from exc

        if not self.root.is_dir():
            raise WorkspaceRootError(f"Workspace root is not a directory: {self.root}")

        return self.root


def _ensure_path_within_root(root: Path, workspace_path: Path) -> None:
    try:
        workspace_path.relative_to(root)
    except ValueError as exc:
        raise UnsafeWorkspacePathError(
            f"Workspace path must stay inside the workspace root: {workspace_path}"
        ) from exc
