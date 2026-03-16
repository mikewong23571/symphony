from __future__ import annotations

import json
from collections.abc import Mapping

from symphony.agent_runner.dynamic_tool import (
    LINEAR_GRAPHQL_TOOL_NAME,
    build_dynamic_tool_runtime,
    execute_dynamic_tool,
    linear_graphql_tool_spec,
)
from symphony.workflow.config import LinearTrackerConfig, PlaneTrackerConfig, ServiceConfig


class FakeLinearClient:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, object]]] = []

    def execute_raw_graphql(
        self,
        *,
        query: str,
        variables: Mapping[str, object],
    ) -> object:
        self.calls.append((query, dict(variables)))
        return self.payload


def build_linear_tracker_config(*, api_key: str | None = "linear-token") -> LinearTrackerConfig:
    return LinearTrackerConfig(
        kind="linear",
        endpoint="https://api.linear.app/graphql",
        api_key=api_key,
        project_slug="symphony",
        active_states=("Todo", "In Progress"),
        terminal_states=("Done",),
    )


def test_linear_graphql_tool_spec_matches_expected_contract() -> None:
    spec = linear_graphql_tool_spec()

    assert spec["name"] == LINEAR_GRAPHQL_TOOL_NAME
    assert spec["inputSchema"]["required"] == ["query"]
    assert spec["inputSchema"]["properties"]["variables"]["type"] == ["object", "null"]


def test_build_dynamic_tool_runtime_only_advertises_linear_tools() -> None:
    config = ServiceConfig(
        prompt_template="Prompt",
        tracker=PlaneTrackerConfig(
            kind="plane",
            api_base_url="https://plane.example.com",
            api_key="plane-token",
            workspace_slug="workspace",
            project_id="123",
            active_states=("Todo",),
            terminal_states=("Done",),
        ),
        polling=None,  # type: ignore[arg-type]
        workspace=None,  # type: ignore[arg-type]
        observability=None,  # type: ignore[arg-type]
        server=None,  # type: ignore[arg-type]
        hooks=None,  # type: ignore[arg-type]
        agent=None,  # type: ignore[arg-type]
        codex=None,  # type: ignore[arg-type]
    )

    runtime = build_dynamic_tool_runtime(config)

    assert runtime.tool_specs == ()
    assert runtime.executor is None


def test_execute_dynamic_tool_returns_successful_graphql_payload() -> None:
    fake_client = FakeLinearClient({"data": {"viewer": {"id": "usr_123"}}})

    result = execute_dynamic_tool(
        LINEAR_GRAPHQL_TOOL_NAME,
        {
            "query": "query Viewer { viewer { id } }",
            "variables": {"includeTeams": False},
        },
        tracker_config=build_linear_tracker_config(),
        linear_client_factory=lambda tracker_config: fake_client,
    )

    assert result["success"] is True
    assert fake_client.calls == [
        ("query Viewer { viewer { id } }", {"includeTeams": False}),
    ]
    assert json.loads(result["output"]) == {"data": {"viewer": {"id": "usr_123"}}}


def test_execute_dynamic_tool_accepts_raw_query_string() -> None:
    fake_client = FakeLinearClient({"data": {"viewer": {"id": "usr_123"}}})

    result = execute_dynamic_tool(
        LINEAR_GRAPHQL_TOOL_NAME,
        " query Viewer { viewer { id } } ",
        tracker_config=build_linear_tracker_config(),
        linear_client_factory=lambda tracker_config: fake_client,
    )

    assert result["success"] is True
    assert fake_client.calls == [("query Viewer { viewer { id } }", {})]


def test_execute_dynamic_tool_marks_graphql_errors_as_failures_and_preserves_body() -> None:
    result = execute_dynamic_tool(
        LINEAR_GRAPHQL_TOOL_NAME,
        {"query": "query Viewer { viewer { id } }"},
        tracker_config=build_linear_tracker_config(),
        linear_client_factory=lambda tracker_config: FakeLinearClient(
            {"data": None, "errors": [{"message": "No viewer"}]}
        ),
    )

    assert result["success"] is False
    assert json.loads(result["output"]) == {
        "data": None,
        "errors": [{"message": "No viewer"}],
    }


def test_execute_dynamic_tool_validates_arguments_before_calling_linear() -> None:
    fake_client = FakeLinearClient({"data": {"viewer": {"id": "usr_123"}}})

    result = execute_dynamic_tool(
        LINEAR_GRAPHQL_TOOL_NAME,
        {"query": "   ", "variables": ["bad"]},
        tracker_config=build_linear_tracker_config(),
        linear_client_factory=lambda tracker_config: fake_client,
    )

    assert result["success"] is False
    assert fake_client.calls == []
    assert json.loads(result["output"]) == {
        "error": {"message": "`linear_graphql` requires a non-empty `query` string."}
    }


def test_execute_dynamic_tool_returns_failure_for_unsupported_tools() -> None:
    result = execute_dynamic_tool(
        "not_a_real_tool",
        {},
        tracker_config=build_linear_tracker_config(),
    )

    assert result["success"] is False
    assert json.loads(result["output"]) == {
        "error": {
            "message": "Unsupported dynamic tool: 'not_a_real_tool'.",
            "supportedTools": ["linear_graphql"],
        }
    }


def test_execute_dynamic_tool_reports_missing_auth() -> None:
    result = execute_dynamic_tool(
        LINEAR_GRAPHQL_TOOL_NAME,
        {"query": "query Viewer { viewer { id } }"},
        tracker_config=build_linear_tracker_config(api_key=None),
    )

    assert result["success"] is False
    assert json.loads(result["output"]) == {
        "error": {
            "message": (
                "Symphony is missing Linear auth. Set `tracker.api_key` in "
                "`WORKFLOW.md` or export `LINEAR_API_KEY`."
            )
        }
    }
