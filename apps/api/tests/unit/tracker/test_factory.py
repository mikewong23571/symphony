from __future__ import annotations

import pytest
from symphony.tracker import (
    LinearTrackerClient,
    TrackerRequestFailedError,
    build_tracker_mutation_backend,
    build_tracker_read_client,
)
from symphony.workflow import MissingTrackerWorkspaceSlugError, UnsupportedTrackerKindError
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
    assert backend.project_ref == "symphony"


def test_build_tracker_mutation_backend_normalizes_linear_request_errors() -> None:
    backend = build_tracker_mutation_backend(make_service_config())

    assert isinstance(backend, LinearTrackerClient)
    backend.transport = lambda **_: (_ for _ in ()).throw(OSError("boom"))

    with pytest.raises(TrackerRequestFailedError, match="Linear API request failed."):
        backend.create_comment("issue-123", "Ready for review")


def test_build_tracker_read_client_rejects_valid_plane_config_with_typed_error() -> None:
    config = build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "plane",
                    "api_base_url": "https://plane.example",
                    "api_key": "plane-token",
                    "workspace_slug": "workspace",
                    "project_id": "project-123",
                }
            },
            prompt_template="Prompt body",
        ),
        env={},
    )

    try:
        build_tracker_read_client(config)
    except UnsupportedTrackerKindError as exc:
        assert exc.message == "tracker.kind must be set to the supported tracker kind 'linear'."
    else:
        raise AssertionError("Expected build_tracker_read_client() to raise a typed config error.")


def test_build_tracker_mutation_backend_surfaces_plane_field_errors() -> None:
    config = build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "plane",
                    "api_base_url": "https://plane.example",
                    "api_key": "plane-token",
                    "project_id": "project-123",
                }
            },
            prompt_template="Prompt body",
        ),
        env={},
    )

    try:
        build_tracker_mutation_backend(config)
    except MissingTrackerWorkspaceSlugError as exc:
        assert exc.message == "tracker.workspace_slug is required when tracker.kind is 'plane'."
    else:
        raise AssertionError(
            "Expected build_tracker_mutation_backend() to raise a typed Plane field error."
        )
