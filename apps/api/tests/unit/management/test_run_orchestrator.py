from __future__ import annotations

import logging
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from symphony.management.commands.run_orchestrator import Command
from symphony.management.commands.run_orchestrator import Orchestrator as CommandOrchestrator
from symphony.observability.runtime import get_runtime_observability_config

MINIMAL_VALID_WORKFLOW = """---
tracker:
  kind: linear
  api_key: linear-token
  project_slug: symphony
---
# Prompt body
"""


WORKFLOW_WITH_HTTP_PORT = """---
tracker:
  kind: linear
  api_key: linear-token
  project_slug: symphony
server:
  port: 43123
---
# Prompt body
"""


WORKFLOW_WITH_OBSERVABILITY = """---
tracker:
  kind: linear
  api_key: linear-token
  project_slug: symphony
observability:
  snapshot_path: .runtime/snapshot.json
  refresh_request_path: .runtime/refresh.json
  recovery_path: .runtime/recovery.json
  snapshot_max_age_seconds: 45
---
# Prompt body
"""


WORKFLOW_WITH_HTTP_PORT_AND_OBSERVABILITY = """---
tracker:
  kind: linear
  api_key: linear-token
  project_slug: symphony
server:
  port: 43123
observability:
  snapshot_path: .runtime/snapshot.json
  refresh_request_path: .runtime/refresh.json
  recovery_path: .runtime/recovery.json
  snapshot_max_age_seconds: 45
---
# Prompt body
"""


class FakeHTTPServer:
    def __init__(self, *, url: str = "http://127.0.0.1:43123/") -> None:
        self.url = url
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class ExplodingHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        del record
        raise RuntimeError("sink exploded")


def fake_async_method(calls: list[str], name: str) -> object:
    async def _method(self: object) -> None:
        calls.append(name)

    return _method


def write_workflow(path: Path, *, contents: str = MINIMAL_VALID_WORKFLOW) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def install_fake_http_server(
    monkeypatch: pytest.MonkeyPatch,
    *,
    calls: list[tuple[str, int]],
    server: FakeHTTPServer,
) -> None:
    def _start_http_server(*, host: str, port: int) -> FakeHTTPServer:
        calls.append((host, port))
        return server

    monkeypatch.setattr(
        "symphony.management.commands.run_orchestrator.start_runtime_http_server",
        _start_http_server,
    )


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


def test_run_orchestrator_starts_http_server_from_workflow_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md", contents=WORKFLOW_WITH_HTTP_PORT)
    stdout = StringIO()
    calls: list[str] = []
    server_calls: list[tuple[str, int]] = []
    fake_server = FakeHTTPServer()

    monkeypatch.chdir(tmp_path)
    install_fake_http_server(
        monkeypatch,
        calls=server_calls,
        server=fake_server,
    )
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
    assert "Runtime dashboard listening on http://127.0.0.1:43123/" in output
    assert server_calls == [("127.0.0.1", 43123)]
    assert fake_server.close_calls == 1
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_applies_observability_config_before_starting_http_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md", contents=WORKFLOW_WITH_HTTP_PORT_AND_OBSERVABILITY)
    stdout = StringIO()
    calls: list[str] = []
    observed_config: dict[str, object] = {}
    fake_server = FakeHTTPServer()

    def _start_http_server(*, host: str, port: int) -> FakeHTTPServer:
        runtime_config = get_runtime_observability_config()
        observed_config["host"] = host
        observed_config["port"] = port
        observed_config["snapshot_path"] = runtime_config.snapshot_path
        observed_config["refresh_request_path"] = runtime_config.refresh_request_path
        observed_config["recovery_path"] = runtime_config.recovery_path
        observed_config["snapshot_max_age_seconds"] = runtime_config.snapshot_max_age_seconds
        return fake_server

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "symphony.management.commands.run_orchestrator.start_runtime_http_server",
        _start_http_server,
    )
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

    assert observed_config == {
        "host": "127.0.0.1",
        "port": 43123,
        "snapshot_path": Path(".runtime/snapshot.json"),
        "refresh_request_path": Path(".runtime/refresh.json"),
        "recovery_path": Path(".runtime/recovery.json"),
        "snapshot_max_age_seconds": 45,
    }
    assert fake_server.close_calls == 1
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_cli_port_overrides_workflow_port(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md", contents=WORKFLOW_WITH_HTTP_PORT)
    stdout = StringIO()
    calls: list[str] = []
    server_calls: list[tuple[str, int]] = []
    fake_server = FakeHTTPServer(url="http://127.0.0.1:0/")

    monkeypatch.chdir(tmp_path)
    install_fake_http_server(
        monkeypatch,
        calls=server_calls,
        server=fake_server,
    )
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

    call_command("run_orchestrator", "--once", "--port", "0", stdout=stdout)

    assert server_calls == [("127.0.0.1", 0)]
    assert fake_server.close_calls == 1
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_cli_host_overrides_default_bind_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md", contents=WORKFLOW_WITH_HTTP_PORT)
    stdout = StringIO()
    calls: list[str] = []
    server_calls: list[tuple[str, int]] = []
    fake_server = FakeHTTPServer(url="http://0.0.0.0:43123/")

    monkeypatch.chdir(tmp_path)
    install_fake_http_server(
        monkeypatch,
        calls=server_calls,
        server=fake_server,
    )
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

    call_command("run_orchestrator", "--once", "--host", "0.0.0.0", stdout=stdout)

    assert "Runtime dashboard listening on http://0.0.0.0:43123/" in stdout.getvalue()
    assert server_calls == [("0.0.0.0", 43123)]
    assert fake_server.close_calls == 1
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_loads_workflow_observability_settings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md", contents=WORKFLOW_WITH_OBSERVABILITY)
    stdout = StringIO()
    calls: list[str] = []
    loaded_paths: dict[str, object] = {}

    async def capture_run_once(self: CommandOrchestrator) -> None:
        loaded_paths["snapshot_path"] = self.config.observability.snapshot_path
        loaded_paths["refresh_request_path"] = self.config.observability.refresh_request_path
        loaded_paths["recovery_path"] = self.config.observability.recovery_path
        loaded_paths["snapshot_max_age_seconds"] = (
            self.config.observability.snapshot_max_age_seconds
        )
        calls.append("run_once")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(CommandOrchestrator, "run_once", capture_run_once)
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

    assert loaded_paths == {
        "snapshot_path": Path(".runtime/snapshot.json"),
        "refresh_request_path": Path(".runtime/refresh.json"),
        "recovery_path": Path(".runtime/recovery.json"),
        "snapshot_max_age_seconds": 45,
    }
    assert calls == ["run_once", "wait_for_running_workers", "aclose"]


def test_run_orchestrator_rejects_negative_cli_port(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md")
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.WARNING, logger="symphony.management.commands.run_orchestrator")

    with pytest.raises(CommandError, match=r"port must be an integer greater than or equal to 0"):
        call_command("run_orchestrator", "--port", "-1")
    assert "event=startup_validation_failed error_code=workflow_config_error" in caplog.text


def test_run_orchestrator_rejects_non_integer_port_option(
    caplog: pytest.LogCaptureFixture,
) -> None:
    command = Command()
    caplog.set_level(logging.WARNING, logger="symphony.management.commands.run_orchestrator")

    with pytest.raises(
        CommandError,
        match=r"Startup failed \(workflow_config_error\): port must be an integer\.",
    ):
        command.handle(port="abc")

    assert "event=startup_validation_failed error_code=workflow_config_error" in caplog.text


def test_run_orchestrator_rejects_empty_cli_host(
    caplog: pytest.LogCaptureFixture,
) -> None:
    command = Command()
    caplog.set_level(logging.WARNING, logger="symphony.management.commands.run_orchestrator")

    with pytest.raises(
        CommandError,
        match=r"Startup failed \(workflow_config_error\): host must not be empty\.",
    ):
        command.handle(host="   ")

    assert "event=startup_validation_failed error_code=workflow_config_error" in caplog.text


def test_run_orchestrator_survives_logging_sink_failures(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md")
    monkeypatch.chdir(tmp_path)
    command_logger = logging.getLogger("symphony.management.commands.run_orchestrator")
    original_handlers = list(command_logger.handlers)
    original_propagate = command_logger.propagate
    original_level = command_logger.level
    command_logger.handlers = [ExplodingHandler()]
    command_logger.propagate = False
    command_logger.setLevel(logging.WARNING)

    try:
        with pytest.raises(
            CommandError,
            match=r"port must be an integer greater than or equal to 0",
        ):
            call_command("run_orchestrator", "--port", "-1")
    finally:
        command_logger.handlers = original_handlers
        command_logger.propagate = original_propagate
        command_logger.setLevel(original_level)

    assert (
        "event=log_sink_failed "
        "logger_name=symphony.management.commands.run_orchestrator "
        'error_code=RuntimeError message="sink exploded"'
    ) in capsys.readouterr().err


def test_run_orchestrator_surfaces_http_server_bind_failures(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(tmp_path / "WORKFLOW.md", contents=WORKFLOW_WITH_HTTP_PORT)
    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.WARNING, logger="symphony.management.commands.run_orchestrator")
    monkeypatch.setattr(
        "symphony.management.commands.run_orchestrator.start_runtime_http_server",
        lambda *, host, port: (_ for _ in ()).throw(OSError("address in use")),
    )

    with pytest.raises(CommandError, match=r"Startup failed \(http_server_error\):"):
        call_command("run_orchestrator", "--once")
    assert "event=http_server_bind_failed host=127.0.0.1 port=43123" in caplog.text


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
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    write_workflow(
        tmp_path / "WORKFLOW.md",
        contents="---\ntracker: [unterminated\n---\n# Prompt body\n",
    )

    monkeypatch.chdir(tmp_path)
    caplog.set_level(logging.WARNING, logger="symphony.management.commands.run_orchestrator")

    with pytest.raises(CommandError, match=r"Startup failed \(workflow_parse_error\):"):
        call_command("run_orchestrator")
    assert "event=workflow_load_failed" in caplog.text
    assert "error_code=workflow_parse_error" in caplog.text


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
