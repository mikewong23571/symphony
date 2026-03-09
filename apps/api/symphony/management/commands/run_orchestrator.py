import os
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from symphony.workflow import (
    WorkflowConfigError,
    WorkflowError,
    build_service_config,
    load_workflow_definition,
    resolve_workflow_path,
    validate_dispatch_config,
)


class Command(BaseCommand):
    help = "Run the Symphony orchestrator loop."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "workflow_path",
            nargs="?",
            help="Optional path to the workflow file. Defaults to ./WORKFLOW.md.",
        )

    def handle(self, *args: object, **options: Any) -> str | None:
        workflow_path = options.get("workflow_path")
        if workflow_path is not None and not isinstance(workflow_path, str):
            raise CommandError("Startup failed (workflow_error): workflow path must be a string.")

        resolved_path = resolve_workflow_path(workflow_path, cwd=Path.cwd())

        try:
            definition = load_workflow_definition(workflow_path, cwd=Path.cwd())
            config = build_service_config(definition, env=os.environ)
            validate_dispatch_config(config)
        except (WorkflowError, WorkflowConfigError) as exc:
            raise CommandError(f"Startup failed ({exc.code}): {exc.message}") from exc

        self.stdout.write(f"Loaded workflow definition from {resolved_path}")
        self.stdout.write(
            self.style.WARNING("Orchestrator skeleton created. Implementation is pending.")
        )
        return None
