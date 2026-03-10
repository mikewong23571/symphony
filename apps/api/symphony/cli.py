from __future__ import annotations

import os
import sys


def run_orchestrator_main() -> None:
    if "DJANGO_SETTINGS_MODULE" not in os.environ:
        sys.stderr.write(
            "Error: DJANGO_SETTINGS_MODULE is not set.\n"
            "Example: export DJANGO_SETTINGS_MODULE=config.settings.local\n"
        )
        sys.exit(1)

    from django.core.management import execute_from_command_line

    execute_from_command_line(
        ["symphony-orchestrator", "run_orchestrator", *sys.argv[1:]],
    )
