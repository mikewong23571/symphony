from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_snapshot_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "SYMPHONY_RUNTIME_SNAPSHOT_PATH",
        str(tmp_path / "runtime-snapshot.json"),
    )
