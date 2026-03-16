from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from symphony.agent_runner.client import (
    AppServerDiagnosticContext,
    AppServerProtocolError,
    AppServerResponseTimeoutError,
    AppServerSession,
    AppServerStartupError,
    _drain_stderr,
    _extract_required_id,
    _normalize_sandbox_policy,
)
from symphony.common.types import ServiceInfo

HANDSHAKE_REQUEST_COUNT = 3
FIRST_RUNTIME_REQUEST_ID = HANDSHAKE_REQUEST_COUNT + 1
APP_SERVER_STREAM_READ_LIMIT_BYTES = 1_048_576


async def start_legacy_app_server_session(
    *,
    command: str,
    workspace_path: Path,
    prompt_text: str,
    title: str,
    service_info: ServiceInfo,
    approval_policy: str,
    thread_sandbox: str,
    turn_sandbox_policy: Mapping[str, Any],
    read_timeout_ms: int,
    capabilities: Mapping[str, Any] | None = None,
    dynamic_tools: Sequence[Mapping[str, Any]] | None = None,
    model: str | None = None,
    stderr_callback: (
        Callable[[str, AppServerDiagnosticContext], Awaitable[None] | None] | None
    ) = None,
) -> AppServerSession:
    workspace_cwd = workspace_path.resolve()

    try:
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            command,
            cwd=str(workspace_cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=APP_SERVER_STREAM_READ_LIMIT_BYTES,
        )
    except OSError as exc:
        raise AppServerStartupError("Could not start the Codex app-server subprocess.") from exc

    stderr_lines: list[str] = []
    pending_messages: deque[Mapping[str, Any]] = deque()
    next_request_id = FIRST_RUNTIME_REQUEST_ID
    diagnostic_context = AppServerDiagnosticContext(
        session_id=None,
        thread_id=None,
        turn_id=None,
        codex_app_server_pid=process.pid,
    )
    stderr_task = asyncio.create_task(
        _drain_stderr(
            process,
            stderr_lines,
            stderr_callback=stderr_callback,
            diagnostic_context=diagnostic_context,
        )
    )

    try:
        await _send_message(
            process,
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "clientInfo": {
                        "name": service_info.name,
                        "version": service_info.version,
                    },
                    "capabilities": dict(capabilities or {}),
                },
            },
        )
        await _wait_for_response(
            process,
            expected_id=1,
            read_timeout_ms=read_timeout_ms,
            pending_messages=pending_messages,
        )

        await _send_message(process, {"method": "initialized", "params": {}})

        thread_start_params: dict[str, Any] = {
            "cwd": str(workspace_cwd),
            "approvalPolicy": approval_policy,
            "sandbox": thread_sandbox,
        }
        if model is not None:
            thread_start_params["model"] = model
        if dynamic_tools:
            thread_start_params["dynamicTools"] = [dict(tool_spec) for tool_spec in dynamic_tools]

        await _send_message(
            process,
            {
                "id": 2,
                "method": "thread/start",
                "params": thread_start_params,
            },
        )
        thread_result = await _wait_for_response(
            process,
            expected_id=2,
            read_timeout_ms=read_timeout_ms,
            pending_messages=pending_messages,
        )
        thread_id = _extract_required_id(thread_result, outer_key="thread")
        diagnostic_context.thread_id = thread_id

        await _send_message(
            process,
            {
                "id": 3,
                "method": "turn/start",
                "params": {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": prompt_text}],
                    "cwd": str(workspace_cwd),
                    "title": title,
                    "approvalPolicy": approval_policy,
                    "sandboxPolicy": _normalize_sandbox_policy(turn_sandbox_policy),
                },
            },
        )
        turn_result = await _wait_for_response(
            process,
            expected_id=3,
            read_timeout_ms=read_timeout_ms,
            pending_messages=pending_messages,
        )
        turn_id = _extract_required_id(turn_result, outer_key="turn")
        diagnostic_context.turn_id = turn_id
        diagnostic_context.session_id = f"{thread_id}-{turn_id}"
    except Exception:
        await _terminate_process(process)
        await stderr_task
        raise

    async def close_session() -> None:
        await _terminate_process(process)
        await stderr_task

    async def read_message(timeout_seconds: float | None) -> Mapping[str, Any]:
        if pending_messages:
            return pending_messages.popleft()

        if process.stdout is None:
            raise AppServerStartupError("App-server stdout is not available.")

        if timeout_seconds is None:
            line = await _read_jsonl_line(process.stdout)
        else:
            line = await asyncio.wait_for(_read_jsonl_line(process.stdout), timeout=timeout_seconds)

        if not line:
            raise AppServerProtocolError("App-server closed stdout before the turn completed.")

        return _decode_message(line)

    async def send_message(message: Mapping[str, object]) -> None:
        await _send_message(process, message)

    async def start_turn(
        next_prompt_text: str,
        next_title: str,
        next_approval_policy: str,
        next_sandbox_policy: Mapping[str, Any],
        next_cwd: Path,
        next_read_timeout_ms: int,
    ) -> str:
        nonlocal next_request_id
        request_id = next_request_id
        next_request_id += 1

        await _send_message(
            process,
            {
                "id": request_id,
                "method": "turn/start",
                "params": {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": next_prompt_text}],
                    "cwd": str(next_cwd.resolve()),
                    "title": next_title,
                    "approvalPolicy": next_approval_policy,
                    "sandboxPolicy": _normalize_sandbox_policy(next_sandbox_policy),
                },
            },
        )
        turn_result = await _wait_for_response(
            process,
            expected_id=request_id,
            read_timeout_ms=next_read_timeout_ms,
            pending_messages=pending_messages,
        )
        return _extract_required_id(turn_result, outer_key="turn")

    return AppServerSession(
        process=process,
        thread_id=thread_id,
        turn_id=turn_id,
        session_id=f"{thread_id}-{turn_id}",
        stderr_lines=stderr_lines,
        _stderr_task=stderr_task,
        _diagnostic_context=diagnostic_context,
        _close_callback=close_session,
        _read_message_callback=read_message,
        _send_message_callback=send_message,
        _start_turn_callback=start_turn,
    )


async def _send_message(
    process: asyncio.subprocess.Process,
    message: Mapping[str, object],
) -> None:
    if process.stdin is None:
        raise AppServerStartupError("App-server stdin is not available.")

    payload = f"{json.dumps(dict(message))}\n".encode()
    process.stdin.write(payload)
    await process.stdin.drain()


async def _wait_for_response(
    process: asyncio.subprocess.Process,
    *,
    expected_id: int,
    read_timeout_ms: int,
    pending_messages: deque[Mapping[str, Any]],
) -> Mapping[str, Any]:
    if process.stdout is None:
        raise AppServerStartupError("App-server stdout is not available.")

    loop = asyncio.get_running_loop()
    deadline = loop.time() + (read_timeout_ms / 1000)

    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AppServerResponseTimeoutError(
                f"Timed out waiting for app-server response id {expected_id}."
            )

        try:
            line = await asyncio.wait_for(_read_jsonl_line(process.stdout), timeout=remaining)
        except TimeoutError as exc:
            raise AppServerResponseTimeoutError(
                f"Timed out waiting for app-server response id {expected_id}."
            ) from exc

        if not line:
            raise AppServerProtocolError(
                "App-server closed stdout before completing the handshake."
            )

        message = _decode_message(line)
        if message.get("id") != expected_id:
            pending_messages.append(message)
            continue

        error = message.get("error")
        if error is not None:
            raise AppServerProtocolError(_format_response_error(expected_id, error))

        result = message.get("result")
        if not isinstance(result, Mapping):
            raise AppServerProtocolError(
                f"App-server response id {expected_id} is missing a result object."
            )
        return result


def _decode_message(line: bytes) -> Mapping[str, Any]:
    try:
        message = json.loads(line)
    except json.JSONDecodeError as exc:
        raise AppServerProtocolError("App-server emitted invalid JSON on stdout.") from exc

    if not isinstance(message, Mapping):
        raise AppServerProtocolError("App-server emitted a non-object JSON message on stdout.")

    return message


async def _read_jsonl_line(reader: asyncio.StreamReader) -> bytes:
    chunks = bytearray()

    while True:
        try:
            chunk = await reader.readuntil(b"\n")
        except asyncio.IncompleteReadError as exc:
            if not exc.partial:
                return b""
            raise AppServerProtocolError(
                "App-server closed stdout in the middle of a JSONL message."
            ) from exc
        except asyncio.LimitOverrunError as exc:
            if exc.consumed <= 0:
                raise AppServerProtocolError(
                    "App-server emitted an oversized stdout message before a newline separator."
                ) from exc
            chunks.extend(await reader.readexactly(exc.consumed))
            continue

        chunks.extend(chunk)
        return bytes(chunks)


def _format_response_error(expected_id: int, error: object) -> str:
    prefix = f"App-server returned an error for request id {expected_id}"
    if not isinstance(error, Mapping):
        return prefix + "."

    code = error.get("code")
    message = error.get("message")
    details: list[str] = []
    if code is not None:
        details.append(f"code={code}")
    if isinstance(message, str) and message.strip():
        details.append(message.strip())
    if not details:
        return prefix + "."
    return prefix + ": " + "; ".join(details)


async def _terminate_process(process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=1.0)
    except TimeoutError:
        process.kill()
        await process.wait()
