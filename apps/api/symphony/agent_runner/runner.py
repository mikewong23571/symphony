from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .client import (
    AppServerProtocolError,
    AppServerResponseTimeoutError,
    AppServerSession,
    read_protocol_message,
    send_protocol_message,
)
from .dynamic_tool import DynamicToolExecutor
from .events import AgentRuntimeEvent, TurnResult, extract_usage_snapshot, utcnow

logger = logging.getLogger(__name__)

DEFAULT_UNSUPPORTED_TOOL_ERROR = "unsupported_tool_call"
DEFAULT_USER_INPUT_ERROR = "turn_input_required"
DEFAULT_APPROVAL_REQUIRED_ERROR = "approval_required"
DEFAULT_TURN_TIMEOUT_ERROR = "turn_timeout"
DEFAULT_STALL_TIMEOUT_ERROR = "stalled"
DEFAULT_PROTOCOL_ERROR = "response_error"


async def stream_turn(
    session: AppServerSession,
    *,
    approval_policy: str,
    turn_timeout_ms: int,
    stall_timeout_ms: int,
    tool_executor: DynamicToolExecutor | None = None,
    on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None = None,
) -> TurnResult:
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    last_activity_at = started_at

    while True:
        timeout_seconds = _compute_next_timeout(
            loop_time=loop.time(),
            started_at=started_at,
            last_activity_at=last_activity_at,
            turn_timeout_ms=turn_timeout_ms,
            stall_timeout_ms=stall_timeout_ms,
        )

        try:
            message = await read_protocol_message(session, timeout_seconds=timeout_seconds)
        except TimeoutError:
            now = loop.time()
            turn_deadline_exceeded = _turn_deadline_exceeded(
                now=now,
                started_at=started_at,
                turn_timeout_ms=turn_timeout_ms,
            )
            if turn_deadline_exceeded:
                return TurnResult(
                    outcome="timed_out",
                    error_code=DEFAULT_TURN_TIMEOUT_ERROR,
                    message="App-server turn timed out before reaching a terminal event.",
                    usage=None,
                )

            return TurnResult(
                outcome="stalled",
                error_code=DEFAULT_STALL_TIMEOUT_ERROR,
                message="App-server turn stalled before reaching a terminal event.",
                usage=None,
            )
        except (AppServerProtocolError, AppServerResponseTimeoutError) as exc:
            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name="malformed",
                payload={"message": exc.message},
                usage=None,
            )
            return TurnResult(
                outcome="failed",
                error_code=DEFAULT_PROTOCOL_ERROR,
                message=str(exc),
                usage=None,
            )

        last_activity_at = loop.time()
        raw_message_event_name = message.get("method")
        message_event_name = (
            raw_message_event_name if isinstance(raw_message_event_name, str) else None
        )
        usage = extract_usage_snapshot(message, event_name=message_event_name)
        if usage is not None:
            logger.debug(
                "codex_usage_extracted method=%s is_absolute=%s input=%d output=%d total=%d",
                message_event_name or "unknown",
                usage.is_absolute_total,
                usage.input_tokens,
                usage.output_tokens,
                usage.total_tokens,
            )
        else:
            logger.debug("codex_message_no_usage method=%s", message_event_name or "unknown")

        if _is_turn_completed(message):
            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name="turn_completed",
                payload=_build_payload(message),
                usage=usage,
            )
            return TurnResult(
                outcome="completed",
                error_code=None,
                message=None,
                usage=usage,
            )

        if _is_turn_failed(message):
            error_message = _extract_error_message(message) or "App-server reported turn failure."
            error_code = _extract_error_code(message) or "turn_failed"
            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name="turn_failed",
                payload=_build_payload(message),
                usage=usage,
            )
            return TurnResult(
                outcome="failed",
                error_code=error_code,
                message=error_message,
                usage=usage,
            )

        if _is_turn_cancelled(message):
            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name="turn_cancelled",
                payload=_build_payload(message),
                usage=usage,
            )
            return TurnResult(
                outcome="cancelled",
                error_code="turn_cancelled",
                message="App-server cancelled the turn.",
                usage=usage,
            )

        if _is_user_input_request(message):
            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name="turn_input_required",
                payload=_build_payload(message),
                usage=usage,
            )
            return TurnResult(
                outcome="failed",
                error_code=DEFAULT_USER_INPUT_ERROR,
                message="App-server requested user input during the turn.",
                usage=usage,
            )

        if _is_approval_request(message):
            if _should_auto_approve_requests(approval_policy):
                await _auto_approve_request(session, message)
                await _emit_runtime_event(
                    session,
                    on_event=on_event,
                    event_name="approval_auto_approved",
                    payload=_build_payload(message),
                    usage=usage,
                )
                continue

            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name="turn_ended_with_error",
                payload=_build_payload(message),
                usage=usage,
            )
            return TurnResult(
                outcome="failed",
                error_code=DEFAULT_APPROVAL_REQUIRED_ERROR,
                message=(
                    "App-server requested approval, but the configured approval policy does "
                    "not allow automatic approval."
                ),
                usage=usage,
            )

        if _is_tool_call_request(message):
            event_name = await _handle_tool_call_request(
                session,
                message,
                tool_executor=tool_executor,
            )
            await _emit_runtime_event(
                session,
                on_event=on_event,
                event_name=event_name,
                payload=_build_payload(message),
                usage=usage,
            )
            continue

        event_name = "notification" if "method" in message else "other_message"
        await _emit_runtime_event(
            session,
            on_event=on_event,
            event_name=event_name,
            payload=_build_payload(message),
            usage=usage,
        )


async def _emit_runtime_event(
    session: AppServerSession,
    *,
    on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None,
    event_name: str,
    payload: Mapping[str, Any],
    usage: Any,
) -> None:
    if on_event is None:
        return

    await on_event(
        AgentRuntimeEvent(
            event=event_name,
            timestamp=utcnow(),
            session_id=session.session_id,
            thread_id=session.thread_id,
            turn_id=session.turn_id,
            codex_app_server_pid=session.process.pid,
            usage=usage,
            payload=payload,
        )
    )


def _compute_next_timeout(
    *,
    loop_time: float,
    started_at: float,
    last_activity_at: float,
    turn_timeout_ms: int,
    stall_timeout_ms: int,
) -> float | None:
    deadlines: list[float] = []

    if turn_timeout_ms > 0:
        deadlines.append(started_at + (turn_timeout_ms / 1000))

    if stall_timeout_ms > 0:
        deadlines.append(last_activity_at + (stall_timeout_ms / 1000))

    if not deadlines:
        return None

    nearest_deadline = min(deadlines)
    return max(nearest_deadline - loop_time, 0.0)


def _turn_deadline_exceeded(*, now: float, started_at: float, turn_timeout_ms: int) -> bool:
    if turn_timeout_ms <= 0:
        return False
    return now >= started_at + (turn_timeout_ms / 1000)


def _is_turn_completed(message: Mapping[str, Any]) -> bool:
    return message.get("method") == "turn/completed"


def _is_turn_failed(message: Mapping[str, Any]) -> bool:
    return message.get("method") == "turn/failed"


def _is_turn_cancelled(message: Mapping[str, Any]) -> bool:
    return message.get("method") == "turn/cancelled"


def _is_user_input_request(message: Mapping[str, Any]) -> bool:
    if message.get("method") == "item/tool/requestUserInput":
        return True

    params = message.get("params")
    if not isinstance(params, Mapping):
        return False

    return bool(params.get("inputRequired"))


def _is_approval_request(message: Mapping[str, Any]) -> bool:
    method = message.get("method")
    return isinstance(method, str) and method == "approval/request" and "id" in message


def _is_tool_call_request(message: Mapping[str, Any]) -> bool:
    method = message.get("method")
    return isinstance(method, str) and method == "item/tool/call" and "id" in message


async def _auto_approve_request(session: AppServerSession, message: Mapping[str, Any]) -> None:
    request_id = message.get("id")
    if request_id is None:
        return
    await send_protocol_message(session, {"id": request_id, "result": {"approved": True}})


async def _reject_unsupported_tool_call(
    session: AppServerSession,
    message: Mapping[str, Any],
) -> None:
    request_id = message.get("id")
    if request_id is None:
        return
    await send_protocol_message(
        session,
        {
            "id": request_id,
            "result": {
                "success": False,
                "error": DEFAULT_UNSUPPORTED_TOOL_ERROR,
            },
        },
    )


async def _handle_tool_call_request(
    session: AppServerSession,
    message: Mapping[str, Any],
    *,
    tool_executor: DynamicToolExecutor | None,
) -> str:
    request_id = message.get("id")
    if request_id is None:
        return "unsupported_tool_call"

    tool_name, arguments = _extract_tool_call(message)
    if tool_executor is None:
        await _reject_unsupported_tool_call(session, message)
        return "unsupported_tool_call"

    try:
        result = _normalize_dynamic_tool_result(tool_executor(tool_name, arguments))
    except Exception as exc:  # noqa: BLE001
        result = _normalize_dynamic_tool_result(
            {
                "success": False,
                "output": _dynamic_tool_output(
                    {
                        "error": {
                            "message": "Dynamic tool execution failed.",
                            "reason": repr(exc),
                        }
                    }
                ),
            }
        )

    await send_protocol_message(session, {"id": request_id, "result": result})

    if result.get("success") is True:
        return "tool_call_completed"
    if not tool_name:
        return "unsupported_tool_call"
    return "tool_call_failed"


def _extract_tool_call(message: Mapping[str, Any]) -> tuple[str | None, object]:
    params = message.get("params")
    if not isinstance(params, Mapping):
        return (None, {})

    tool_call = params.get("toolCall")
    if isinstance(tool_call, Mapping):
        tool_name = tool_call.get("toolName")
        if isinstance(tool_name, str) and tool_name.strip():
            arguments = tool_call.get("arguments")
            return (tool_name.strip(), arguments if arguments is not None else {})

    for key in ("tool", "name", "toolName"):
        tool_name = params.get(key)
        if isinstance(tool_name, str) and tool_name.strip():
            arguments = params.get("arguments")
            return (tool_name.strip(), arguments if arguments is not None else {})

    return (None, params.get("arguments", {}))


def _normalize_dynamic_tool_result(result: object) -> dict[str, Any]:
    if isinstance(result, Mapping):
        success = result.get("success")
        if isinstance(success, bool):
            normalized_result = dict(result)
            output = normalized_result.get("output")
            if not isinstance(output, str):
                output = _dynamic_tool_output(result)
            content_items = normalized_result.get("contentItems")
            if not isinstance(content_items, list):
                content_items = _dynamic_tool_content_items(output)
            normalized_result["output"] = output
            normalized_result["contentItems"] = content_items
            return normalized_result

    output = _dynamic_tool_output(result)
    return {
        "success": True,
        "output": output,
        "contentItems": _dynamic_tool_content_items(output),
    }


def _dynamic_tool_output(result: object) -> str:
    if isinstance(result, str):
        return result
    return _json_dumps(result)


def _dynamic_tool_content_items(output: str) -> list[dict[str, str]]:
    return [{"type": "inputText", "text": output}]


def _json_dumps(value: object) -> str:
    try:
        return json.dumps(value, indent=2)
    except TypeError:
        return repr(value)


def _extract_error_message(message: Mapping[str, Any]) -> str | None:
    params = message.get("params")
    if isinstance(params, Mapping):
        error = params.get("error")
        if isinstance(error, Mapping):
            value = error.get("message")
            if isinstance(value, str) and value.strip():
                return value.strip()
        value = params.get("message")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_error_code(message: Mapping[str, Any]) -> str | None:
    params = message.get("params")
    if not isinstance(params, Mapping):
        return None
    error = params.get("error")
    if isinstance(error, Mapping):
        value = error.get("code")
        if isinstance(value, str) and value.strip():
            return value.strip()
    value = params.get("code")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _build_payload(message: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}

    method = message.get("method")
    if isinstance(method, str):
        payload["method"] = method

    params = message.get("params")
    if isinstance(params, Mapping):
        payload["params"] = dict(params)

    if "id" in message:
        payload["id"] = message["id"]

    return payload


def _should_auto_approve_requests(approval_policy: str) -> bool:
    return approval_policy.strip().lower() == "never"
