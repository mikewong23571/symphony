from __future__ import annotations

import pytest
from _pytest.monkeypatch import MonkeyPatch
from symphony.cli import run_orchestrator_main


def test_run_orchestrator_main_dispatches_management_command(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def _execute(argv: list[str]) -> None:
        captured.append(argv)

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.local")
    monkeypatch.setattr("django.core.management.execute_from_command_line", _execute)
    monkeypatch.setattr("sys.argv", ["symphony-orchestrator", "--once", "--host", "0.0.0.0"])

    run_orchestrator_main()

    assert captured == [
        ["symphony-orchestrator", "run_orchestrator", "--once", "--host", "0.0.0.0"],
    ]


def test_run_orchestrator_main_fails_without_settings_module(
    monkeypatch: MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("DJANGO_SETTINGS_MODULE", raising=False)

    with pytest.raises(SystemExit, match="1"):
        run_orchestrator_main()

    assert "DJANGO_SETTINGS_MODULE is not set" in capsys.readouterr().err


def test_run_orchestrator_main_preserves_explicit_settings_module(
    monkeypatch: MonkeyPatch,
) -> None:
    captured: list[list[str]] = []

    def _execute(argv: list[str]) -> None:
        captured.append(argv)

    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings.prod")
    monkeypatch.setattr("django.core.management.execute_from_command_line", _execute)
    monkeypatch.setattr("sys.argv", ["symphony-orchestrator"])

    run_orchestrator_main()

    assert captured == [["symphony-orchestrator", "run_orchestrator"]]
