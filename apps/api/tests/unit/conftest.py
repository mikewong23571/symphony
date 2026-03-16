from __future__ import annotations

from pathlib import Path

import pytest

ISOLATED_RUNTIME_ENV_VARS = (
    "SYMPHONY_WORKFLOW_PATH",
    "SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH",
    "SYMPHONY_RUNTIME_RECOVERY_PATH",
    "SYMPHONY_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS",
)


@pytest.fixture(autouse=True)
def isolate_runtime_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Unit tests should not inherit workflow/runtime state from another checkout.
    for env_var in ISOLATED_RUNTIME_ENV_VARS:
        monkeypatch.delenv(env_var, raising=False)
    monkeypatch.setenv(
        "SYMPHONY_RUNTIME_SNAPSHOT_PATH",
        str(tmp_path / "runtime-snapshot.json"),
    )
