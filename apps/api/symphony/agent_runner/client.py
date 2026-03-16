from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from symphony.common.types import ServiceInfo

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
    stderr_lines: list[str] = field(default_factory=list)
    _stderr_task: asyncio.Task[None] | None = field(default=None, repr=False)
    _diagnostic_context: AppServerDiagnosticContext | None = field(default=None, repr=False)
    _close_callback: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)
    _read_message_callback: Callable[[float | None], Awaitable[Mapping[str, Any]]] | None = field(
        default=None, repr=False
    )
    _send_message_callback: Callable[[Mapping[str, object]], Awaitable[None]] | None = field(
        default=None, repr=False
    )
    _start_turn_callback: (
        Callable[[str, str, str, Mapping[str, Any], Path, int], Awaitable[str]] | None
    ) = field(default=None, repr=False)

    async def aclose(self) -> None:
        if self._close_callback is not None:
            await self._close_callback()
            return

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
    dynamic_tools: Sequence[Mapping[str, Any]] | None = None,
    model: str | None = None,
    stderr_callback: (
        Callable[[str, AppServerDiagnosticContext], Awaitable[None] | None] | None
    ) = None,
) -> AppServerSession:
    return await start_sdk_app_server_session(
        command=command,
        workspace_path=workspace_path,
        prompt_text=prompt_text,
        title=title,
        service_info=service_info,
        approval_policy=approval_policy,
        thread_sandbox=thread_sandbox,
        turn_sandbox_policy=turn_sandbox_policy,
        read_timeout_ms=read_timeout_ms,
        capabilities=capabilities,
        dynamic_tools=dynamic_tools,
        model=model,
        stderr_callback=stderr_callback,
    )


@dataclass(frozen=True, slots=True)
class _SdkBindings:
    client_class: Any
    protocol_error_class: type[Exception]
    timeout_error_class: type[Exception]
    transport_error_class: type[Exception]


def _load_sdk_bindings() -> _SdkBindings:
    try:
        from codex_app_server_sdk.client import CodexClient
        from codex_app_server_sdk.errors import (
            CodexProtocolError,
            CodexTimeoutError,
            CodexTransportError,
        )
    except ImportError as exc:  # pragma: no cover - exercised via real dependency resolution
        raise AppServerStartupError("The codex-app-server-sdk package is not installed.") from exc

    return _SdkBindings(
        client_class=CodexClient,
        protocol_error_class=CodexProtocolError,
        timeout_error_class=CodexTimeoutError,
        transport_error_class=CodexTransportError,
    )


async def start_sdk_app_server_session(
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
    bindings = _load_sdk_bindings()
    workspace_cwd = workspace_path.resolve()
    timeout_seconds = _milliseconds_to_seconds(read_timeout_ms)
    client = bindings.client_class.connect_stdio(
        command=["bash", "-lc", command],
        cwd=str(workspace_cwd),
        connect_timeout=timeout_seconds,
        request_timeout=timeout_seconds,
        inactivity_timeout=None,
    )
    stderr_lines: list[str] = []
    stderr_task: asyncio.Task[None] | None = None
    diagnostic_context: AppServerDiagnosticContext | None = None

    try:
        await client.start()
        process = _extract_sdk_process(client)
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
        await client.initialize(
            {
                "clientInfo": {
                    "name": service_info.name,
                    "version": service_info.version,
                },
                "capabilities": dict(capabilities or {}),
            },
            timeout=timeout_seconds,
        )

        thread_start_params: dict[str, Any] = {
            "cwd": str(workspace_cwd),
            "approvalPolicy": approval_policy,
            "sandbox": thread_sandbox,
        }
        if model is not None:
            thread_start_params["model"] = model
        if dynamic_tools:
            thread_start_params["dynamicTools"] = [dict(tool_spec) for tool_spec in dynamic_tools]

        thread_result = await client.request(
            "thread/start",
            thread_start_params,
            timeout=timeout_seconds,
        )
        if not isinstance(thread_result, Mapping):
            raise AppServerProtocolError("App-server response id 2 is missing a result object.")
        thread_id = _extract_required_id(thread_result, outer_key="thread")
        diagnostic_context.thread_id = thread_id

        turn_result = await client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt_text}],
                "cwd": str(workspace_cwd),
                "title": title,
                "approvalPolicy": approval_policy,
                "sandboxPolicy": _normalize_sandbox_policy(turn_sandbox_policy),
            },
            timeout=timeout_seconds,
        )
        if not isinstance(turn_result, Mapping):
            raise AppServerProtocolError("App-server response id 3 is missing a result object.")
        turn_id = _extract_required_id(turn_result, outer_key="turn")
        diagnostic_context.turn_id = turn_id
        diagnostic_context.session_id = f"{thread_id}-{turn_id}"
    except bindings.timeout_error_class as exc:
        with suppress(Exception):
            await client.close()
        if stderr_task is not None:
            await stderr_task
        raise AppServerResponseTimeoutError(
            "Timed out waiting for app-server handshake response."
        ) from exc
    except bindings.protocol_error_class as exc:
        with suppress(Exception):
            await client.close()
        if stderr_task is not None:
            await stderr_task
        raise AppServerProtocolError(str(exc)) from exc
    except bindings.transport_error_class as exc:
        with suppress(Exception):
            await client.close()
        if stderr_task is not None:
            await stderr_task
        raise AppServerStartupError("Could not start the Codex app-server subprocess.") from exc
    except Exception:
        with suppress(Exception):
            await client.close()
        if stderr_task is not None:
            await stderr_task
        raise

    return AppServerSession(
        process=process,
        thread_id=thread_id,
        turn_id=turn_id,
        session_id=f"{thread_id}-{turn_id}",
        stderr_lines=stderr_lines,
        _stderr_task=stderr_task,
        _diagnostic_context=diagnostic_context,
        _close_callback=lambda: _close_sdk_session(client, stderr_task),
        _read_message_callback=lambda timeout_seconds: _read_sdk_notification(
            client,
            timeout_seconds=timeout_seconds,
        ),
        _send_message_callback=lambda message: _send_sdk_message(client, message),
        _start_turn_callback=lambda next_prompt_text,
        next_title,
        next_approval_policy,
        next_sandbox_policy,
        next_cwd,
        next_read_timeout_ms: _start_sdk_next_turn(
            client,
            thread_id=thread_id,
            prompt_text=next_prompt_text,
            title=next_title,
            approval_policy=next_approval_policy,
            sandbox_policy=next_sandbox_policy,
            cwd=next_cwd,
            read_timeout_ms=next_read_timeout_ms,
            bindings=bindings,
        ),
    )


async def send_protocol_message(
    session: AppServerSession,
    message: Mapping[str, object],
) -> None:
    if session._send_message_callback is None:
        raise AppServerProtocolError("App-server session does not support protocol replies.")
    await session._send_message_callback(message)


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
    if session._start_turn_callback is None:
        raise AppServerProtocolError("App-server session does not support continuation turns.")
    turn_id = await session._start_turn_callback(
        prompt_text,
        title,
        approval_policy,
        sandbox_policy,
        cwd,
        read_timeout_ms,
    )
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
    if session._read_message_callback is None:
        raise AppServerProtocolError("App-server session does not support streamed notifications.")
    message = await session._read_message_callback(timeout_seconds)
    if message.get("method") == "__transport_error__":
        raise AppServerProtocolError(_extract_transport_error_message(message))
    return message


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


def _milliseconds_to_seconds(read_timeout_ms: int) -> float:
    return max(read_timeout_ms / 1000, 0.001)


def _extract_sdk_process(client: Any) -> Any:
    transport = getattr(client, "_transport", None)
    process = getattr(transport, "_proc", None)
    if process is None or not hasattr(process, "pid") or not hasattr(process, "returncode"):
        raise AppServerStartupError("SDK-backed app-server transport did not expose a subprocess.")
    return process


async def _close_sdk_session(client: Any, stderr_task: asyncio.Task[None] | None) -> None:
    await client.close()
    if stderr_task is not None:
        await stderr_task


async def _read_sdk_notification(
    client: Any,
    *,
    timeout_seconds: float | None,
) -> Mapping[str, Any]:
    notifications = getattr(client, "_notifications", None)
    if not isinstance(notifications, asyncio.Queue):
        raise AppServerProtocolError("SDK-backed app-server client did not expose notifications.")

    if timeout_seconds is None:
        message = await notifications.get()
    else:
        message = await asyncio.wait_for(notifications.get(), timeout=timeout_seconds)

    if not isinstance(message, Mapping):
        raise AppServerProtocolError("App-server emitted a non-object notification.")
    return message


async def _send_sdk_message(client: Any, message: Mapping[str, object]) -> None:
    transport = getattr(client, "_transport", None)
    send = getattr(transport, "send", None)
    send_lock = getattr(client, "_send_lock", None)
    if not callable(send):
        raise AppServerProtocolError("SDK-backed app-server transport did not expose send().")

    payload = dict(message)
    if isinstance(send_lock, asyncio.Lock):
        async with send_lock:
            await send(payload)
        return

    await send(payload)


async def _start_sdk_next_turn(
    client: Any,
    *,
    thread_id: str,
    prompt_text: str,
    title: str,
    approval_policy: str,
    sandbox_policy: Mapping[str, Any],
    cwd: Path,
    read_timeout_ms: int,
    bindings: _SdkBindings,
) -> str:
    timeout_seconds = _milliseconds_to_seconds(read_timeout_ms)
    try:
        turn_result = await client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt_text}],
                "cwd": str(cwd.resolve()),
                "title": title,
                "approvalPolicy": approval_policy,
                "sandboxPolicy": _normalize_sandbox_policy(sandbox_policy),
            },
            timeout=timeout_seconds,
        )
    except bindings.timeout_error_class as exc:
        raise AppServerResponseTimeoutError(
            "Timed out waiting for app-server handshake response."
        ) from exc
    except bindings.protocol_error_class as exc:
        raise AppServerProtocolError(str(exc)) from exc
    except bindings.transport_error_class as exc:
        raise AppServerProtocolError(
            "App-server transport failed while starting the next turn."
        ) from exc

    if not isinstance(turn_result, Mapping):
        raise AppServerProtocolError("App-server response id 3 is missing a result object.")
    return _extract_required_id(turn_result, outer_key="turn")


def _extract_transport_error_message(message: Mapping[str, Any]) -> str:
    params = message.get("params")
    if isinstance(params, Mapping):
        value = params.get("message")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "App-server transport failed while receiving notifications."


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
