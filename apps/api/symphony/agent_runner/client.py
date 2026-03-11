from __future__ import annotations

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from symphony.common.types import ServiceInfo

HANDSHAKE_REQUEST_COUNT = 3
FIRST_RUNTIME_REQUEST_ID = HANDSHAKE_REQUEST_COUNT + 1
APP_SERVER_STREAM_READ_LIMIT_BYTES = 1_048_576
_LEGACY_SANDBOX_POLICY_TYPES = {
    "danger-full-access": "dangerFullAccess",
    "external-sandbox": "externalSandbox",
    "read-only": "readOnly",
    "workspace-write": "workspaceWrite",
}


class AppServerError(Exception):
    code = "app_server_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class AppServerStartupError(AppServerError):
    code = "app_server_startup_error"


class AppServerProtocolError(AppServerError):
    code = "app_server_protocol_error"


class AppServerResponseTimeoutError(AppServerError):
    code = "app_server_response_timeout"


@dataclass(slots=True)
class AppServerDiagnosticContext:
    session_id: str | None
    thread_id: str | None
    turn_id: str | None
    codex_app_server_pid: int | None


@dataclass(slots=True)
class AppServerSession:
    process: asyncio.subprocess.Process
    thread_id: str
    turn_id: str
    session_id: str
    # Requests 1-3 are reserved for initialize/thread-start/turn-start during the handshake.
    next_request_id: int = FIRST_RUNTIME_REQUEST_ID
    stderr_lines: list[str] = field(default_factory=list)
    _stderr_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _pending_messages: deque[Mapping[str, Any]] = field(default_factory=deque, repr=False)
    _diagnostic_context: AppServerDiagnosticContext | None = field(default=None, repr=False)

    async def aclose(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=1.0)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

        if self._stderr_task is not None:
            await self._stderr_task


async def start_app_server_session(
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
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except TimeoutError:
                process.kill()
                await process.wait()

        await stderr_task
        raise

    return AppServerSession(
        process=process,
        thread_id=thread_id,
        turn_id=turn_id,
        session_id=f"{thread_id}-{turn_id}",
        next_request_id=FIRST_RUNTIME_REQUEST_ID,
        stderr_lines=stderr_lines,
        _stderr_task=stderr_task,
        _pending_messages=pending_messages,
        _diagnostic_context=diagnostic_context,
    )


async def send_protocol_message(
    session: AppServerSession,
    message: Mapping[str, object],
) -> None:
    await _send_message(session.process, message)


async def start_next_turn(
    session: AppServerSession,
    *,
    prompt_text: str,
    title: str,
    approval_policy: str,
    sandbox_policy: Mapping[str, Any],
    cwd: Path,
    read_timeout_ms: int,
) -> str:
    request_id = session.next_request_id
    session.next_request_id += 1

    await _send_message(
        session.process,
        {
            "id": request_id,
            "method": "turn/start",
            "params": {
                "threadId": session.thread_id,
                "input": [{"type": "text", "text": prompt_text}],
                "cwd": str(cwd.resolve()),
                "title": title,
                "approvalPolicy": approval_policy,
                "sandboxPolicy": _normalize_sandbox_policy(sandbox_policy),
            },
        },
    )
    turn_result = await _wait_for_response(
        session.process,
        expected_id=request_id,
        read_timeout_ms=read_timeout_ms,
        pending_messages=session._pending_messages,
    )
    turn_id = _extract_required_id(turn_result, outer_key="turn")
    session.turn_id = turn_id
    session.session_id = f"{session.thread_id}-{turn_id}"
    if session._diagnostic_context is not None:
        session._diagnostic_context.turn_id = turn_id
        session._diagnostic_context.session_id = session.session_id
    return turn_id


async def read_protocol_message(
    session: AppServerSession,
    *,
    timeout_seconds: float | None = None,
) -> Mapping[str, Any]:
    if session._pending_messages:
        return session._pending_messages.popleft()

    if session.process.stdout is None:
        raise AppServerStartupError("App-server stdout is not available.")

    if timeout_seconds is None:
        line = await _read_jsonl_line(session.process.stdout)
    else:
        # The streaming runner interprets raw TimeoutError as a turn/stall deadline, unlike the
        # handshake path, which wraps request/response timeouts in AppServerResponseTimeoutError.
        line = await asyncio.wait_for(
            _read_jsonl_line(session.process.stdout),
            timeout=timeout_seconds,
        )

    if not line:
        raise AppServerProtocolError("App-server closed stdout before the turn completed.")

    return _decode_message(line)


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
    pending_messages: deque[Mapping[str, Any]] | None = None,
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
            line = await asyncio.wait_for(
                _read_jsonl_line(process.stdout),
                timeout=remaining,
            )
        except TimeoutError as exc:
            raise AppServerResponseTimeoutError(
                f"Timed out waiting for app-server response id {expected_id}."
            ) from exc

        if not line:
            raise AppServerProtocolError(
                "App-server closed stdout before completing the handshake."
            )

        message = _decode_message(line)
        message_id = message.get("id")
        if message_id != expected_id:
            if pending_messages is not None:
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


def _extract_required_id(result: Mapping[str, Any], *, outer_key: str) -> str:
    nested = result.get(outer_key)
    if not isinstance(nested, Mapping):
        raise AppServerProtocolError(f"App-server response is missing result.{outer_key}.id.")

    identifier = nested.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise AppServerProtocolError(f"App-server response is missing result.{outer_key}.id.")

    return identifier


def _normalize_sandbox_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(policy)
    sandbox_type = normalized.get("type")
    if isinstance(sandbox_type, str):
        stripped = sandbox_type.strip()
        normalized["type"] = _LEGACY_SANDBOX_POLICY_TYPES.get(stripped, stripped)
    return normalized


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


async def _drain_stderr(
    process: asyncio.subprocess.Process,
    stderr_lines: list[str],
    *,
    stderr_callback: (
        Callable[[str, AppServerDiagnosticContext], Awaitable[None] | None] | None
    ) = None,
    diagnostic_context: AppServerDiagnosticContext,
) -> None:
    if process.stderr is None:
        return

    while True:
        line = await process.stderr.readline()
        if not line:
            return
        decoded_line = line.decode("utf-8", errors="replace").rstrip("\n")
        stderr_lines.append(decoded_line)
        if stderr_callback is None:
            continue

        callback_result = stderr_callback(decoded_line, diagnostic_context)
        if callback_result is not None:
            await callback_result
