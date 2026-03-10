from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pytest
from symphony.workflow import (
    DEFAULT_ACTIVE_STATES,
    DEFAULT_CODEX_COMMAND,
    DEFAULT_HOOK_TIMEOUT_MS,
    DEFAULT_MAX_TURNS,
    DEFAULT_TERMINAL_STATES,
    DEFAULT_WORKSPACE_ROOT,
    InvalidServerPortError,
    MissingCodexCommandError,
    MissingTrackerAPIKeyError,
    MissingTrackerProjectSlugError,
    ServiceConfig,
    UnsupportedTrackerKindError,
    WorkflowDefinition,
    build_service_config,
    validate_dispatch_config,
)


def build_definition(config: dict[str, Any]) -> WorkflowDefinition:
    return WorkflowDefinition(config=config, prompt_template="Prompt body")


def test_build_service_config_applies_defaults() -> None:
    config = build_service_config(build_definition({}))

    assert config.prompt_template == "Prompt body"
    assert config.tracker.kind is None
    assert config.tracker.active_states == DEFAULT_ACTIVE_STATES
    assert config.tracker.terminal_states == DEFAULT_TERMINAL_STATES
    assert config.workspace.root == DEFAULT_WORKSPACE_ROOT
    assert config.observability.snapshot_path is None
    assert config.observability.refresh_request_path is None
    assert config.observability.recovery_path is None
    assert config.observability.snapshot_max_age_seconds == 120
    assert config.server.port is None
    assert config.hooks.timeout_ms == DEFAULT_HOOK_TIMEOUT_MS
    assert config.agent.max_turns == DEFAULT_MAX_TURNS
    assert config.codex.command == DEFAULT_CODEX_COMMAND


def test_build_service_config_resolves_tracker_api_key_from_explicit_env_token() -> None:
    config = build_service_config(
        build_definition(
            {
                "tracker": {
                    "kind": "linear",
                    "api_key": "$CUSTOM_LINEAR_KEY",
                    "project_slug": "symphony",
                }
            }
        ),
        env={"CUSTOM_LINEAR_KEY": "token-from-env"},
    )

    assert config.tracker.api_key == "token-from-env"


def test_build_service_config_uses_canonical_linear_env_fallback() -> None:
    config = build_service_config(
        build_definition({"tracker": {"kind": "linear", "project_slug": "symphony"}}),
        env={"LINEAR_API_KEY": "canonical-token"},
    )

    assert config.tracker.api_key == "canonical-token"


def test_build_service_config_treats_empty_explicit_env_api_key_as_missing() -> None:
    config = build_service_config(
        build_definition(
            {
                "tracker": {
                    "kind": "linear",
                    "api_key": "$CUSTOM_LINEAR_KEY",
                    "project_slug": "symphony",
                }
            }
        ),
        env={
            "CUSTOM_LINEAR_KEY": "",
            "LINEAR_API_KEY": "canonical-token",
        },
    )

    assert config.tracker.api_key is None


def test_build_service_config_expands_workspace_root_from_env_and_home() -> None:
    config = build_service_config(
        build_definition({"workspace": {"root": "$WORKSPACE_ROOT"}}),
        env={"WORKSPACE_ROOT": "~/symphony/workspaces"},
    )

    assert config.workspace.root == Path.home() / "symphony" / "workspaces"


def test_build_service_config_parses_observability_paths_and_max_age() -> None:
    config = build_service_config(
        build_definition(
            {
                "observability": {
                    "snapshot_path": "~/runtime/snapshot.json",
                    "refresh_request_path": "$REFRESH_REQUEST_PATH",
                    "recovery_path": "var/recovery.json",
                    "snapshot_max_age_seconds": "45",
                }
            }
        ),
        env={"REFRESH_REQUEST_PATH": "~/runtime/refresh.json"},
    )

    assert config.observability.snapshot_path == Path.home() / "runtime" / "snapshot.json"
    assert config.observability.refresh_request_path == Path.home() / "runtime" / "refresh.json"
    assert config.observability.recovery_path == Path("var/recovery.json")
    assert config.observability.snapshot_max_age_seconds == 45


def test_build_service_config_parses_states_and_agent_limits() -> None:
    config = build_service_config(
        build_definition(
            {
                "tracker": {
                    "active_states": "Todo, In Progress, Blocked",
                    "terminal_states": ["Done", "Cancelled"],
                },
                "hooks": {"timeout_ms": 0},
                "agent": {
                    "max_turns": "25",
                    "max_concurrent_agents_by_state": {
                        " Todo ": "2",
                        "In Progress": 0,
                        "Review": "bad",
                        "Blocked": 3,
                    },
                },
            }
        )
    )

    assert config.tracker.active_states == ("Todo", "In Progress", "Blocked")
    assert config.tracker.terminal_states == ("Done", "Cancelled")
    assert config.hooks.timeout_ms == DEFAULT_HOOK_TIMEOUT_MS
    assert config.agent.max_turns == 25
    assert config.agent.max_concurrent_agents_by_state == {"todo": 2, "blocked": 3}


def test_build_service_config_parses_optional_server_port() -> None:
    config = build_service_config(build_definition({"server": {"port": "0"}}))

    assert config.server.port == 0


@pytest.mark.parametrize("raw_port", [-1, "abc", True])
def test_build_service_config_rejects_invalid_server_port(raw_port: object) -> None:
    with pytest.raises(InvalidServerPortError, match="server.port must be an integer"):
        build_service_config(build_definition({"server": {"port": raw_port}}))


@pytest.mark.parametrize(
    ("config", "error_type"),
    [
        ({}, UnsupportedTrackerKindError),
        ({"tracker": {"kind": "github"}}, UnsupportedTrackerKindError),
        (
            {"tracker": {"kind": "linear", "project_slug": "symphony"}},
            MissingTrackerAPIKeyError,
        ),
        (
            {
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                }
            },
            MissingTrackerProjectSlugError,
        ),
        (
            {
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                },
                "codex": {"command": "   "},
            },
            MissingCodexCommandError,
        ),
    ],
)
def test_validate_dispatch_config_surfaces_required_startup_errors(
    config: dict[str, Any],
    error_type: type[Exception],
) -> None:
    service_config = build_service_config(build_definition(config))

    with pytest.raises(error_type):
        validate_dispatch_config(service_config)


def test_default_workspace_root_uses_system_tempdir() -> None:
    config = build_service_config(build_definition({}))

    assert config.workspace.root == Path(tempfile.gettempdir()) / "symphony_workspaces"


def test_validate_dispatch_config_accepts_minimal_valid_linear_config() -> None:
    service_config = build_service_config(
        build_definition(
            {
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                }
            }
        )
    )

    validate_dispatch_config(service_config)

    assert isinstance(service_config, ServiceConfig)
