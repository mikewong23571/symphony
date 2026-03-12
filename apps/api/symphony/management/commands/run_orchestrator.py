import asyncio
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from symphony.api.server import DEFAULT_HTTP_BIND_HOST, start_runtime_http_server
from symphony.observability.logging import log_event
from symphony.observability.runtime import configure_runtime_observability
from symphony.orchestrator import Orchestrator
from symphony.workflow import (
    WorkflowConfigError,
    WorkflowError,
    WorkflowRuntime,
)

if TYPE_CHECKING:
    from symphony.api.server import RuntimeHTTPServer

__all__ = ["Command", "Orchestrator"]

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Run the Symphony orchestrator loop."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "workflow_path",
            nargs="?",
            help="Optional path to the workflow file. Defaults to ./WORKFLOW.md.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run startup cleanup and a single orchestrator tick, then exit.",
        )
        parser.add_argument(
            "--port",
            type=int,
            help="Optional HTTP port for the observability/control extension.",
        )
        parser.add_argument(
            "--host",
            help="Optional HTTP bind host for the observability/control extension.",
        )

    def handle(self, *args: object, **options: Any) -> str | None:
        workflow_path = options.get("workflow_path")
        if workflow_path is not None and not isinstance(workflow_path, str):
            log_event(
                logger,
                logging.WARNING,
                "startup_validation_failed",
                fields={
                    "error_code": "workflow_error",
                    "message": "workflow path must be a string.",
                },
            )
            raise CommandError("Startup failed (workflow_error): workflow path must be a string.")
        run_once = bool(options.get("once"))
        cli_port = options.get("port")
        cli_host = options.get("host")
        if cli_port is not None and not isinstance(cli_port, int):
            log_event(
                logger,
                logging.WARNING,
                "startup_validation_failed",
                fields={
                    "error_code": "workflow_config_error",
                    "message": "port must be an integer.",
                },
            )
            raise CommandError("Startup failed (workflow_config_error): port must be an integer.")
        if cli_port is not None and cli_port < 0:
            log_event(
                logger,
                logging.WARNING,
                "startup_validation_failed",
                fields={
                    "error_code": "workflow_config_error",
                    "message": "port must be an integer greater than or equal to 0.",
                },
            )
            raise CommandError(
                "Startup failed (workflow_config_error): "
                "port must be an integer greater than or equal to 0."
            )
        bind_host = self._resolve_http_host(cli_host)

        workflow_runtime = WorkflowRuntime(workflow_path, cwd=Path.cwd(), env=os.environ)
        try:
            config = workflow_runtime.load_initial()
        except (WorkflowError, WorkflowConfigError) as exc:
            log_event(
                logger,
                logging.WARNING,
                "workflow_load_failed",
                fields={
                    "workflow_path": workflow_runtime.path,
                    "error_code": exc.code,
                    "message": exc.message,
                },
            )
            raise CommandError(f"Startup failed ({exc.code}): {exc.message}") from exc

        self.stdout.write(f"Loaded workflow definition from {workflow_runtime.path}")
        configure_runtime_observability(
            snapshot_path=config.observability.snapshot_path,
            refresh_request_path=config.observability.refresh_request_path,
            recovery_path=config.observability.recovery_path,
            snapshot_max_age_seconds=config.observability.snapshot_max_age_seconds,
        )
        http_port = cli_port if cli_port is not None else config.server.port
        http_server = self._start_http_server(host=bind_host, port=http_port)

        async def run() -> None:
            orchestrator: Orchestrator | None = None
            try:
                orchestrator = Orchestrator(config=config, workflow_runtime=workflow_runtime)
                if run_once:
                    await orchestrator.run_once()
                    await orchestrator.wait_for_running_workers()
                else:
                    await orchestrator.run_forever()
            finally:
                if orchestrator is not None:
                    await orchestrator.aclose()

        try:
            try:
                asyncio.run(run())
            finally:
                if http_server is not None:
                    http_server.close()
        except WorkflowConfigError as exc:
            log_event(
                logger,
                logging.WARNING,
                "startup_validation_failed",
                fields={
                    "error_code": exc.code,
                    "message": exc.message,
                },
            )
            raise CommandError(f"Startup failed ({exc.code}): {exc.message}") from exc
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Orchestrator stopped by signal."))

        if run_once:
            self.stdout.write("Orchestrator tick completed.")
        else:
            self.stdout.write("Orchestrator stopped.")
        return None

    def _resolve_http_host(self, cli_host: str | None) -> str:
        if cli_host is None:
            return DEFAULT_HTTP_BIND_HOST
        host = cli_host.strip()
        if not host:
            log_event(
                logger,
                logging.WARNING,
                "startup_validation_failed",
                fields={
                    "error_code": "workflow_config_error",
                    "message": "host must not be empty.",
                },
            )
            raise CommandError("Startup failed (workflow_config_error): host must not be empty.")
        return host

    def _start_http_server(self, *, host: str, port: int | None) -> "RuntimeHTTPServer | None":
        if port is None:
            return None
        try:
            http_server = start_runtime_http_server(host=host, port=port)
        except OSError as exc:
            log_event(
                logger,
                logging.WARNING,
                "http_server_bind_failed",
                fields={
                    "host": host,
                    "port": port,
                    "error_code": exc.__class__.__name__,
                    "message": str(exc) or "could not bind HTTP server",
                },
            )
            raise CommandError(
                f"Startup failed (http_server_error): could not bind HTTP server to {host}:{port}."
            ) from exc
        self.stdout.write(f"Runtime dashboard listening on {http_server.url}")
        return http_server
