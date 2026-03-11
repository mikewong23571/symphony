from __future__ import annotations

from symphony.tracker import (
    LinearTrackerClient,
    build_tracker_mutation_backend,
    build_tracker_read_client,
)
from symphony.workflow.config import ServiceConfig, build_service_config
from symphony.workflow.loader import WorkflowDefinition


def make_service_config() -> ServiceConfig:
    return build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                },
                "codex": {"command": "codex app-server"},
            },
            prompt_template="Prompt body",
        ),
        env={},
    )


def test_build_tracker_read_client_returns_linear_adapter() -> None:
    client = build_tracker_read_client(make_service_config())

    assert isinstance(client, LinearTrackerClient)


def test_build_tracker_mutation_backend_returns_linear_adapter() -> None:
    backend = build_tracker_mutation_backend(make_service_config())

    assert isinstance(backend, LinearTrackerClient)
