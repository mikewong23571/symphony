from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .loader import WorkflowDefinition

DEFAULT_LINEAR_ENDPOINT = "https://api.linear.app/graphql"
DEFAULT_ACTIVE_STATES = ("Todo", "In Progress")
DEFAULT_TERMINAL_STATES = ("Closed", "Cancelled", "Canceled", "Duplicate", "Done")
DEFAULT_POLL_INTERVAL_MS = 30_000
DEFAULT_WORKSPACE_ROOT = Path(tempfile.gettempdir()) / "symphony_workspaces"
DEFAULT_HOOK_TIMEOUT_MS = 60_000
DEFAULT_MAX_CONCURRENT_AGENTS = 10
DEFAULT_MAX_TURNS = 20
DEFAULT_MAX_RETRY_BACKOFF_MS = 300_000
DEFAULT_CODEX_COMMAND = "codex app-server"
DEFAULT_TURN_TIMEOUT_MS = 3_600_000
DEFAULT_READ_TIMEOUT_MS = 5_000
DEFAULT_STALL_TIMEOUT_MS = 300_000
DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 120


class WorkflowConfigError(Exception):
    code = "workflow_config_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class UnsupportedTrackerKindError(WorkflowConfigError):
    code = "unsupported_tracker_kind"


class MissingTrackerAPIKeyError(WorkflowConfigError):
    code = "missing_tracker_api_key"


class MissingTrackerAPIBaseURLError(WorkflowConfigError):
    code = "missing_tracker_api_base_url"


class MissingTrackerWorkspaceSlugError(WorkflowConfigError):
    code = "missing_tracker_workspace_slug"


class MissingTrackerProjectIDError(WorkflowConfigError):
    code = "missing_tracker_project_id"


class MissingTrackerProjectSlugError(WorkflowConfigError):
    code = "missing_tracker_project_slug"


class MissingCodexCommandError(WorkflowConfigError):
    code = "missing_codex_command"


class InvalidServerPortError(WorkflowConfigError):
    code = "invalid_server_port"


@dataclass(slots=True, frozen=True)
class LinearTrackerConfig:
    kind: str | None
    endpoint: str
    api_key: str | None
    project_slug: str | None
    active_states: tuple[str, ...]
    terminal_states: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class PlaneTrackerConfig:
    kind: str
    api_base_url: str | None
    api_key: str | None
    workspace_slug: str | None
    project_id: str | None
    active_states: tuple[str, ...]
    terminal_states: tuple[str, ...]


TrackerConfig = LinearTrackerConfig | PlaneTrackerConfig


@dataclass(slots=True, frozen=True)
class PollingConfig:
    interval_ms: int


@dataclass(slots=True, frozen=True)
class WorkspaceConfig:
    root: Path


@dataclass(slots=True, frozen=True)
class ObservabilityConfig:
    snapshot_path: Path | None
    refresh_request_path: Path | None
    recovery_path: Path | None
    snapshot_max_age_seconds: int


@dataclass(slots=True, frozen=True)
class ServerConfig:
    port: int | None


@dataclass(slots=True, frozen=True)
class HooksConfig:
    after_create: str | None
    before_run: str | None
    after_run: str | None
    before_remove: str | None
    timeout_ms: int


@dataclass(slots=True, frozen=True)
class AgentConfig:
    max_concurrent_agents: int
    max_turns: int
    max_retry_backoff_ms: int
    max_concurrent_agents_by_state: dict[str, int]


@dataclass(slots=True, frozen=True)
class CodexConfig:
    command: str
    approval_policy: str | None
    thread_sandbox: str | None
    turn_sandbox_policy: Mapping[str, Any] | None
    turn_timeout_ms: int
    read_timeout_ms: int
    stall_timeout_ms: int


@dataclass(slots=True, frozen=True)
class ServiceConfig:
    prompt_template: str
    tracker: TrackerConfig
    polling: PollingConfig
    workspace: WorkspaceConfig
    observability: ObservabilityConfig
    server: ServerConfig
    hooks: HooksConfig
    agent: AgentConfig
    codex: CodexConfig


def build_service_config(
    definition: WorkflowDefinition,
    *,
    env: Mapping[str, str] | None = None,
) -> ServiceConfig:
    environment = env if env is not None else os.environ

    tracker_section = _get_section(definition.config, "tracker")
    polling_section = _get_section(definition.config, "polling")
    workspace_section = _get_section(definition.config, "workspace")
    observability_section = _get_section(definition.config, "observability")
    server_section = _get_section(definition.config, "server")
    hooks_section = _get_section(definition.config, "hooks")
    agent_section = _get_section(definition.config, "agent")
    codex_section = _get_section(definition.config, "codex")

    return ServiceConfig(
        prompt_template=definition.prompt_template,
        tracker=_build_tracker_config(tracker_section, env=environment),
        polling=PollingConfig(
            interval_ms=_coerce_int(
                polling_section.get("interval_ms"),
                default=DEFAULT_POLL_INTERVAL_MS,
            ),
        ),
        workspace=WorkspaceConfig(
            root=_coerce_workspace_root(
                workspace_section.get("root"),
                env=environment,
            ),
        ),
        observability=ObservabilityConfig(
            snapshot_path=_coerce_optional_path(
                observability_section.get("snapshot_path"),
                env=environment,
            ),
            refresh_request_path=_coerce_optional_path(
                observability_section.get("refresh_request_path"),
                env=environment,
            ),
            recovery_path=_coerce_optional_path(
                observability_section.get("recovery_path"),
                env=environment,
            ),
            snapshot_max_age_seconds=_coerce_positive_int(
                observability_section.get("snapshot_max_age_seconds"),
                default=DEFAULT_SNAPSHOT_MAX_AGE_SECONDS,
            ),
        ),
        server=ServerConfig(port=_coerce_server_port(server_section.get("port"))),
        hooks=HooksConfig(
            after_create=_clean_string(hooks_section.get("after_create")),
            before_run=_clean_string(hooks_section.get("before_run")),
            after_run=_clean_string(hooks_section.get("after_run")),
            before_remove=_clean_string(hooks_section.get("before_remove")),
            timeout_ms=_coerce_positive_int(
                hooks_section.get("timeout_ms"),
                default=DEFAULT_HOOK_TIMEOUT_MS,
            ),
        ),
        agent=AgentConfig(
            max_concurrent_agents=_coerce_int(
                agent_section.get("max_concurrent_agents"),
                default=DEFAULT_MAX_CONCURRENT_AGENTS,
            ),
            max_turns=_coerce_int(
                agent_section.get("max_turns"),
                default=DEFAULT_MAX_TURNS,
            ),
            max_retry_backoff_ms=_coerce_int(
                agent_section.get("max_retry_backoff_ms"),
                default=DEFAULT_MAX_RETRY_BACKOFF_MS,
            ),
            max_concurrent_agents_by_state=_coerce_state_limits(
                agent_section.get("max_concurrent_agents_by_state"),
            ),
        ),
        codex=CodexConfig(
            command=_resolve_codex_command(codex_section),
            approval_policy=_clean_string(codex_section.get("approval_policy")),
            thread_sandbox=_clean_string(codex_section.get("thread_sandbox")),
            turn_sandbox_policy=_coerce_turn_sandbox_policy(
                codex_section.get("turn_sandbox_policy")
            ),
            turn_timeout_ms=_coerce_int(
                codex_section.get("turn_timeout_ms"),
                default=DEFAULT_TURN_TIMEOUT_MS,
            ),
            read_timeout_ms=_coerce_int(
                codex_section.get("read_timeout_ms"),
                default=DEFAULT_READ_TIMEOUT_MS,
            ),
            stall_timeout_ms=_coerce_int(
                codex_section.get("stall_timeout_ms"),
                default=DEFAULT_STALL_TIMEOUT_MS,
            ),
        ),
    )


def require_linear_tracker_config(tracker: TrackerConfig) -> LinearTrackerConfig:
    _validate_tracker_config(tracker)
    if isinstance(tracker, PlaneTrackerConfig):
        raise UnsupportedTrackerKindError(
            "tracker.kind must be set to the supported tracker kind 'linear'."
        )

    return tracker


def require_plane_tracker_config(tracker: TrackerConfig) -> PlaneTrackerConfig:
    _validate_tracker_config(tracker)
    if not isinstance(tracker, PlaneTrackerConfig):
        raise UnsupportedTrackerKindError(
            "tracker.kind must be set to the supported tracker kind 'plane'."
        )

    return tracker


def validate_dispatch_config(config: ServiceConfig) -> None:
    _validate_tracker_config(config.tracker)

    if not config.codex.command.strip():
        raise MissingCodexCommandError("codex.command must be a non-empty shell command.")


def _validate_tracker_config(tracker: TrackerConfig) -> None:
    if isinstance(tracker, PlaneTrackerConfig):
        if not tracker.api_base_url:
            raise MissingTrackerAPIBaseURLError(
                "tracker.api_base_url is required when tracker.kind is 'plane'."
            )

        if not tracker.api_key:
            raise MissingTrackerAPIKeyError(
                "tracker.api_key is required when tracker.kind is 'plane'."
            )

        if not tracker.workspace_slug:
            raise MissingTrackerWorkspaceSlugError(
                "tracker.workspace_slug is required when tracker.kind is 'plane'."
            )

        if not tracker.project_id:
            raise MissingTrackerProjectIDError(
                "tracker.project_id is required when tracker.kind is 'plane'."
            )
        return

    if tracker.kind != "linear":
        raise UnsupportedTrackerKindError(
            "tracker.kind must be set to the supported tracker kind 'linear'."
        )

    if not tracker.api_key:
        raise MissingTrackerAPIKeyError(
            "tracker.api_key must be configured or resolve from LINEAR_API_KEY."
        )

    if not tracker.project_slug:
        raise MissingTrackerProjectSlugError(
            "tracker.project_slug is required when tracker.kind is 'linear'."
        )


def _get_section(config: dict[str, Any], key: str) -> Mapping[str, Any]:
    value = config.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _build_tracker_config(
    tracker_section: Mapping[str, Any],
    *,
    env: Mapping[str, str],
) -> TrackerConfig:
    tracker_kind = _clean_string(tracker_section.get("kind"))
    tracker_kind = tracker_kind.lower() if tracker_kind is not None else None
    tracker_api_key = _resolve_tracker_api_key(tracker_section, tracker_kind, env)
    active_states = _coerce_states(
        tracker_section.get("active_states"),
        DEFAULT_ACTIVE_STATES,
    )
    terminal_states = _coerce_states(
        tracker_section.get("terminal_states"),
        DEFAULT_TERMINAL_STATES,
    )

    if tracker_kind == "plane":
        return PlaneTrackerConfig(
            kind=tracker_kind,
            api_base_url=_resolve_optional_env_string(
                tracker_section.get("api_base_url"),
                env=env,
            ),
            api_key=tracker_api_key,
            workspace_slug=_resolve_optional_env_string(
                tracker_section.get("workspace_slug"),
                env=env,
            ),
            project_id=_coerce_tracker_project_id(
                tracker_section.get("project_id"),
                env=env,
            ),
            active_states=active_states,
            terminal_states=terminal_states,
        )

    return LinearTrackerConfig(
        kind=tracker_kind,
        endpoint=_clean_string(tracker_section.get("endpoint")) or DEFAULT_LINEAR_ENDPOINT,
        api_key=tracker_api_key,
        project_slug=_clean_string(tracker_section.get("project_slug")),
        active_states=active_states,
        terminal_states=terminal_states,
    )


def _clean_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _coerce_tracker_project_id(value: Any, *, env: Mapping[str, str]) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    return _resolve_optional_env_string(value, env=env)


def _coerce_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return int(normalized)
        except ValueError:
            return default
    return default


def _coerce_positive_int(value: Any, *, default: int) -> int:
    coerced = _coerce_int(value, default=default)
    if coerced <= 0:
        return default
    return coerced


def _coerce_server_port(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise InvalidServerPortError("server.port must be an integer greater than or equal to 0.")
    if isinstance(value, int):
        if value >= 0:
            return value
        raise InvalidServerPortError("server.port must be an integer greater than or equal to 0.")
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            parsed = int(normalized)
        except ValueError as exc:
            raise InvalidServerPortError(
                "server.port must be an integer greater than or equal to 0."
            ) from exc
        if parsed >= 0:
            return parsed
        raise InvalidServerPortError("server.port must be an integer greater than or equal to 0.")
    raise InvalidServerPortError("server.port must be an integer greater than or equal to 0.")


def _coerce_states(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [item.strip() for item in value if isinstance(item, str)]
    else:
        return default

    normalized = tuple(item for item in items if item)
    return normalized or default


def _coerce_workspace_root(value: Any, *, env: Mapping[str, str]) -> Path:
    if not isinstance(value, str):
        return DEFAULT_WORKSPACE_ROOT

    raw_value = value.strip()
    if not raw_value:
        return DEFAULT_WORKSPACE_ROOT

    if raw_value.startswith("$") and len(raw_value) > 1:
        raw_value = env.get(raw_value[1:], "").strip()
        if not raw_value:
            return DEFAULT_WORKSPACE_ROOT

    return Path(os.path.expanduser(raw_value))


def _resolve_optional_env_string(value: Any, *, env: Mapping[str, str]) -> str | None:
    if not isinstance(value, str):
        return None

    normalized = value.strip()
    if not normalized:
        return None

    if normalized.startswith("$") and len(normalized) > 1:
        return env.get(normalized[1:], "").strip() or None

    return normalized


def _resolve_tracker_api_key(
    tracker_section: Mapping[str, Any],
    tracker_kind: str | None,
    env: Mapping[str, str],
) -> str | None:
    raw_value = tracker_section.get("api_key")
    has_explicit_api_key = False

    if isinstance(raw_value, str):
        has_explicit_api_key = True
        resolved_value = _resolve_optional_env_string(raw_value, env=env)
    else:
        resolved_value = None

    if resolved_value is None and tracker_kind == "linear" and not has_explicit_api_key:
        resolved_value = env.get("LINEAR_API_KEY", "").strip() or None

    return resolved_value


def _coerce_optional_path(value: Any, *, env: Mapping[str, str]) -> Path | None:
    if not isinstance(value, str):
        return None

    raw_value = value.strip()
    if not raw_value:
        return None

    if raw_value.startswith("$") and len(raw_value) > 1:
        raw_value = env.get(raw_value[1:], "").strip()
        if not raw_value:
            return None

    return Path(os.path.expanduser(raw_value))


def _resolve_codex_command(codex_section: Mapping[str, Any]) -> str:
    if "command" not in codex_section:
        return DEFAULT_CODEX_COMMAND

    raw_value = codex_section.get("command")
    if not isinstance(raw_value, str):
        return ""

    return raw_value.strip()


def _coerce_turn_sandbox_policy(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        return {"type": normalized}

    if isinstance(value, Mapping):
        normalized_policy: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                continue
            normalized_key = key.strip()
            if not normalized_key:
                continue
            normalized_policy[normalized_key] = item
        return normalized_policy or None

    return None


def _coerce_state_limits(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}

    normalized_limits: dict[str, int] = {}
    for state_name, raw_limit in value.items():
        if not isinstance(state_name, str):
            continue

        normalized_state = state_name.strip().lower()
        if not normalized_state:
            continue

        limit = _coerce_positive_int(raw_limit, default=0)
        if limit <= 0:
            continue

        normalized_limits[normalized_state] = limit

    return normalized_limits
