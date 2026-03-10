import asyncio
import os
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from symphony.orchestrator import Orchestrator
from symphony.workflow import (
    WorkflowConfigError,
    WorkflowError,
    build_service_config,
    load_workflow_definition,
    resolve_workflow_path,
    validate_dispatch_config,
)

__all__ = ["Command", "Orchestrator"]


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

    def handle(self, *args: object, **options: Any) -> str | None:
        workflow_path = options.get("workflow_path")
        if workflow_path is not None and not isinstance(workflow_path, str):
            raise CommandError("Startup failed (workflow_error): workflow path must be a string.")
        run_once = bool(options.get("once"))

        resolved_path = resolve_workflow_path(workflow_path, cwd=Path.cwd())

        try:
            definition = load_workflow_definition(workflow_path, cwd=Path.cwd())
            config = build_service_config(definition, env=os.environ)
            validate_dispatch_config(config)
        except (WorkflowError, WorkflowConfigError) as exc:
            raise CommandError(f"Startup failed ({exc.code}): {exc.message}") from exc

        self.stdout.write(f"Loaded workflow definition from {resolved_path}")

        async def run() -> None:
            orchestrator = Orchestrator(config=config)
            try:
                if run_once:
                    await orchestrator.run_once()
                    await orchestrator.wait_for_running_workers()
                else:
                    await orchestrator.run_forever()
            finally:
                await orchestrator.aclose()

        try:
            asyncio.run(run())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("Orchestrator stopped by signal."))

        if run_once:
            self.stdout.write("Orchestrator tick completed.")
        else:
            self.stdout.write("Orchestrator stopped.")
        return None
