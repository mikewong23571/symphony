from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from symphony.workspace.hooks import run_hook


class FakeProcess:
    def __init__(self) -> None:
        self.returncode = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        return (b"", b"")

    async def wait(self) -> int:
        return 0

    def terminate(self) -> None:
        return None

    def kill(self) -> None:
        return None


def test_run_hook_uses_bash_lc(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_create_subprocess_exec(*args: object, **kwargs: object) -> FakeProcess:
        captured["args"] = args
        captured["kwargs"] = kwargs
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    async def run_test() -> None:
        result = await run_hook(
            name="before_run",
            script="echo hi",
            cwd=tmp_path,
            timeout_ms=1_000,
        )
        assert result.name == "before_run"

    asyncio.run(run_test())

    assert captured["args"][:2] == ("bash", "-lc")
