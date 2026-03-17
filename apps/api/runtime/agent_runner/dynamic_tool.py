from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from lib.tracker.linear_client import (
    LinearAPIRequestError,
    LinearAPIStatusError,
    LinearTrackerClient,
)
from lib.workflow.config import LinearTrackerConfig, PlaneTrackerConfig, ServiceConfig

LINEAR_GRAPHQL_TOOL_NAME = "linear_graphql"
LINEAR_GRAPHQL_TOOL_DESCRIPTION = (
    "Execute a raw GraphQL query or mutation against Linear using Symphony's configured auth."
)
LINEAR_GRAPHQL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["query"],
    "properties": {
        "query": {
            "type": "string",
            "description": "GraphQL query or mutation document to execute against Linear.",
        },
        "variables": {
            "type": ["object", "null"],
            "description": "Optional GraphQL variables object.",
            "additionalProperties": True,
        },
    },
}


class DynamicToolExecutor(Protocol):
    def __call__(self, tool: str | None, arguments: object) -> Mapping[str, Any] | object: ...


class RawLinearGraphqlClient(Protocol):
    def execute_raw_graphql(
        self,
        *,
        query: str,
        variables: Mapping[str, object],
    ) -> Mapping[str, Any] | object: ...


@dataclass(slots=True, frozen=True)
class DynamicToolRuntime:
    tool_specs: tuple[dict[str, Any], ...]
    executor: DynamicToolExecutor | None


def build_dynamic_tool_runtime(config: ServiceConfig) -> DynamicToolRuntime:
    if isinstance(config.tracker, PlaneTrackerConfig):
        return DynamicToolRuntime(tool_specs=(), executor=None)

    return DynamicToolRuntime(
        tool_specs=(linear_graphql_tool_spec(),),
        executor=lambda tool, arguments: execute_dynamic_tool(
            tool,
            arguments,
            tracker_config=config.tracker,
        ),
    )


def linear_graphql_tool_spec() -> dict[str, Any]:
    return {
        "name": LINEAR_GRAPHQL_TOOL_NAME,
        "description": LINEAR_GRAPHQL_TOOL_DESCRIPTION,
        "inputSchema": dict(LINEAR_GRAPHQL_INPUT_SCHEMA),
    }


def _build_linear_graphql_client(tracker_config: LinearTrackerConfig) -> RawLinearGraphqlClient:
    return LinearTrackerClient(tracker_config)


def execute_dynamic_tool(
    tool: str | None,
    arguments: object,
    *,
    tracker_config: LinearTrackerConfig,
    linear_client_factory: Callable[
        [LinearTrackerConfig],
        RawLinearGraphqlClient,
    ] = _build_linear_graphql_client,
) -> dict[str, Any]:
    if tool != LINEAR_GRAPHQL_TOOL_NAME:
        return _failure_response(
            {
                "error": {
                    "message": f"Unsupported dynamic tool: {tool!r}.",
                    "supportedTools": [LINEAR_GRAPHQL_TOOL_NAME],
                }
            }
        )

    normalized_arguments = _normalize_linear_graphql_arguments(arguments)
    if isinstance(normalized_arguments, dict) and "error" in normalized_arguments:
        return _failure_response(normalized_arguments)

    query = normalized_arguments["query"]
    variables = normalized_arguments["variables"]

    if not tracker_config.api_key:
        return _failure_response(
            {
                "error": {
                    "message": (
                        "Symphony is missing Linear auth. Set `tracker.api_key` in "
                        "`WORKFLOW.md` or export `LINEAR_API_KEY`."
                    )
                }
            }
        )

    client = linear_client_factory(tracker_config)
    try:
        payload = client.execute_raw_graphql(query=query, variables=variables)
    except LinearAPIStatusError as exc:
        error_payload: dict[str, Any] = {
            "error": {
                "message": exc.message,
            }
        }
        status = _extract_http_status(exc.message)
        if status is not None:
            error_payload["error"]["status"] = status
        return _failure_response(error_payload)
    except LinearAPIRequestError as exc:
        return _failure_response(
            {
                "error": {
                    "message": "Linear GraphQL request failed before receiving a response.",
                    "reason": _exception_reason(exc),
                }
            }
        )
    except Exception as exc:  # noqa: BLE001
        return _failure_response(
            {
                "error": {
                    "message": "Linear GraphQL tool execution failed.",
                    "reason": _exception_reason(exc),
                }
            }
        )

    return _graphql_response(payload)


def _normalize_linear_graphql_arguments(arguments: object) -> dict[str, Any]:
    if isinstance(arguments, str):
        query = arguments.strip()
        if not query:
            return {"error": {"message": "`linear_graphql` requires a non-empty `query` string."}}
        return {"query": query, "variables": {}}

    if not isinstance(arguments, Mapping):
        return {
            "error": {
                "message": (
                    "`linear_graphql` expects either a GraphQL query string or an object "
                    "with `query` and optional `variables`."
                )
            }
        }

    query_value = arguments.get("query")
    if not isinstance(query_value, str) or not query_value.strip():
        return {"error": {"message": "`linear_graphql` requires a non-empty `query` string."}}

    variables_value = arguments.get("variables", {})
    if variables_value is None:
        variables_value = {}
    if not isinstance(variables_value, Mapping):
        return {
            "error": {"message": "`linear_graphql.variables` must be a JSON object when provided."}
        }

    return {
        "query": query_value.strip(),
        "variables": dict(variables_value),
    }


def _graphql_response(payload: object) -> dict[str, Any]:
    success = True
    if isinstance(payload, Mapping):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            success = False

    return _dynamic_tool_response(success=success, output=_encode_payload(payload))


def _failure_response(payload: object) -> dict[str, Any]:
    return _dynamic_tool_response(success=False, output=_encode_payload(payload))


def _dynamic_tool_response(*, success: bool, output: str) -> dict[str, Any]:
    return {
        "success": success,
        "output": output,
        "contentItems": [
            {
                "type": "inputText",
                "text": output,
            }
        ],
    }


def _encode_payload(payload: object) -> str:
    if isinstance(payload, Mapping | list):
        return json.dumps(payload, indent=2)
    return repr(payload)


def _extract_http_status(message: str) -> int | None:
    match = re.search(r"\bHTTP (\d{3})\b", message)
    if match is None:
        return None
    return int(match.group(1))


def _exception_reason(exc: Exception) -> str:
    if exc.__cause__ is not None:
        return repr(exc.__cause__)
    return str(exc)
