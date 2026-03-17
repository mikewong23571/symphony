from __future__ import annotations

import pytest
from lib.tracker import (
    LinearTrackerClient,
    PlaneTrackerClient,
    TrackerRequestFailedError,
    build_tracker_mutation_backend,
    build_tracker_read_client,
)
from lib.workflow import MissingTrackerWorkspaceSlugError
from lib.workflow.config import ServiceConfig, build_service_config
from lib.workflow.loader import WorkflowDefinition


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


def make_plane_service_config() -> ServiceConfig:
    return build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "plane",
                    "api_base_url": "https://plane.example",
                    "api_key": "plane-token",
                    "workspace_slug": "workspace",
                    "project_id": "project-123",
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


def test_build_tracker_read_client_returns_plane_adapter() -> None:
    client = build_tracker_read_client(make_plane_service_config())

    assert isinstance(client, PlaneTrackerClient)
    assert client.project_ref == "project-123"


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


def test_build_tracker_mutation_backend_returns_plane_adapter() -> None:
    backend = build_tracker_mutation_backend(make_plane_service_config())

    assert isinstance(backend, PlaneTrackerClient)
    assert backend.project_ref == "project-123"


def test_build_tracker_mutation_backend_normalizes_plane_request_errors() -> None:
    backend = build_tracker_mutation_backend(make_plane_service_config())

    assert isinstance(backend, PlaneTrackerClient)
    backend.transport = lambda **_: (_ for _ in ()).throw(OSError("boom"))

    with pytest.raises(TrackerRequestFailedError, match="Plane API request failed."):
        backend.create_comment("issue-123", "Ready for review")
