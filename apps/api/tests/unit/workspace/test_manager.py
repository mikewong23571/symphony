from __future__ import annotations

from pathlib import Path

import pytest
from symphony.workspace import (
    InvalidWorkspaceIdentifierError,
    UnsafeWorkspacePathError,
    WorkspaceManager,
    WorkspacePathCollisionError,
    sanitize_issue_identifier,
)


def test_sanitize_issue_identifier_replaces_disallowed_characters() -> None:
    assert sanitize_issue_identifier("SYM 123/feature#alpha") == "SYM_123_feature_alpha"


def test_ensure_workspace_creates_new_directory(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")

    workspace = manager.ensure_workspace("SYM-101")

    assert workspace.workspace_key == "SYM-101"
    assert workspace.created_now is True
    assert workspace.path == (tmp_path / "workspaces" / "SYM-101").resolve()
    assert workspace.path.is_dir()


def test_ensure_workspace_reuses_existing_directory(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    original = manager.ensure_workspace("SYM-101")

    reused = manager.ensure_workspace("SYM-101")

    assert original.path == reused.path
    assert reused.created_now is False


def test_ensure_workspace_rejects_existing_file_at_workspace_path(tmp_path: Path) -> None:
    root = tmp_path / "workspaces"
    root.mkdir()
    (root / "SYM-101").write_text("not a directory", encoding="utf-8")
    manager = WorkspaceManager(root)

    with pytest.raises(WorkspacePathCollisionError, match="not a directory"):
        manager.ensure_workspace("SYM-101")


@pytest.mark.parametrize("issue_identifier", ["", "   ", ".", ".."])
def test_resolve_workspace_path_rejects_degenerate_identifiers(issue_identifier: str) -> None:
    manager = WorkspaceManager(Path("/tmp/symphony-workspaces"))

    with pytest.raises(InvalidWorkspaceIdentifierError):
        manager.resolve_workspace_path(issue_identifier)


def test_ensure_workspace_rejects_symlink_targets_outside_root(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "workspaces")
    root = manager.root
    outside_directory = tmp_path / "outside"

    root.mkdir()
    outside_directory.mkdir()
    (root / "SYM-101").symlink_to(outside_directory, target_is_directory=True)

    with pytest.raises(UnsafeWorkspacePathError, match="must stay inside"):
        manager.ensure_workspace("SYM-101")


def test_relative_workspace_root_is_normalized_to_absolute_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = WorkspaceManager(Path("relative-workspaces"))

    workspace = manager.ensure_workspace("SYM-202")

    assert workspace.path == (tmp_path / "relative-workspaces" / "SYM-202").resolve()
