from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from symphony.common.types import ServiceInfo


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
class AppServerSession:
    process: asyncio.subprocess.Process
    thread_id: str
    turn_id: str
    session_id: str
    stderr_lines: list[str] = field(default_factory=list)
    _stderr_task: asyncio.Task[None] | None = field(default=None, repr=False)

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
) -> AppServerSession:
    workspace_cwd = workspace_path.resolve()
    if not workspace_cwd.is_absolute():
        raise AppServerStartupError("App-server workspace path must be absolute.")

    try:
        process = await asyncio.create_subprocess_exec(
            "bash",
            "-lc",
            command,
            cwd=str(workspace_cwd),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise AppServerStartupError("Could not start the Codex app-server subprocess.") from exc

    stderr_lines: list[str] = []
    stderr_task = asyncio.create_task(_drain_stderr(process, stderr_lines))

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
        await _wait_for_response(process, expected_id=1, read_timeout_ms=read_timeout_ms)

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
        )
        thread_id = _extract_required_id(thread_result, outer_key="thread")

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
                    "sandboxPolicy": dict(turn_sandbox_policy),
                },
            },
        )
        turn_result = await _wait_for_response(
            process,
            expected_id=3,
            read_timeout_ms=read_timeout_ms,
        )
        turn_id = _extract_required_id(turn_result, outer_key="turn")
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
        stderr_lines=stderr_lines,
        _stderr_task=stderr_task,
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
            line = await asyncio.wait_for(process.stdout.readline(), timeout=remaining)
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
            continue

        error = message.get("error")
        if error is not None:
            raise AppServerProtocolError(
                f"App-server returned an error for request id {expected_id}."
            )

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


def _extract_required_id(result: Mapping[str, Any], *, outer_key: str) -> str:
    nested = result.get(outer_key)
    if not isinstance(nested, Mapping):
        raise AppServerProtocolError(f"App-server response is missing result.{outer_key}.id.")

    identifier = nested.get("id")
    if not isinstance(identifier, str) or not identifier.strip():
        raise AppServerProtocolError(f"App-server response is missing result.{outer_key}.id.")

    return identifier


async def _drain_stderr(
    process: asyncio.subprocess.Process,
    stderr_lines: list[str],
) -> None:
    if process.stderr is None:
        return

    while True:
        line = await process.stderr.readline()
        if not line:
            return
        stderr_lines.append(line.decode("utf-8", errors="replace").rstrip("\n"))
