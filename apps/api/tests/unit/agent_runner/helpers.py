from __future__ import annotations

import asyncio
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import symphony.agent_runner.client as client_module
from symphony.agent_runner import AgentRuntimeEvent, AppServerSession
from symphony.common.types import ServiceInfo

from .legacy_transport import start_legacy_app_server_session

FAKE_APP_SERVER_PATH = Path(__file__).with_name("fake_app_server.py")


async def collect_events(
    events: list[AgentRuntimeEvent],
    event: AgentRuntimeEvent,
) -> None:
    events.append(event)


async def start_fake_app_server_session(
    tmp_path: Path,
    *,
    log_path: Path,
    mode: str,
    read_timeout_ms: int = 1_000,
    approval_policy: str = "never",
    dynamic_tools: list[dict[str, object]] | None = None,
) -> AppServerSession:
    log_path.write_text("", encoding="utf-8")
    command = (
        f"FAKE_SERVER_MODE={mode} FAKE_SERVER_LOG={log_path} "
        f"{sys.executable} {FAKE_APP_SERVER_PATH}"
    )

    return await start_legacy_app_server_session(
        command=command,
        workspace_path=tmp_path,
        prompt_text="Summarize this repo.",
        title="SYM-123: Handshake",
        service_info=ServiceInfo(name="symphony", version="0.1.0"),
        approval_policy=approval_policy,
        thread_sandbox="workspace-write",
        turn_sandbox_policy={"type": "workspace-write"},
        read_timeout_ms=read_timeout_ms,
        capabilities={},
        dynamic_tools=dynamic_tools,
        model="gpt-5.1-codex",
    )


class FakeSdkProtocolError(Exception):
    pass


class FakeSdkTimeoutError(Exception):
    pass


class FakeSdkTransportError(Exception):
    pass


class FakeSdkClientFactory:
    def __init__(self, client: FakeSdkClient) -> None:
        self._client = client

    def connect_stdio(self, **kwargs: object) -> FakeSdkClient:
        self._client.connect_kwargs = dict(kwargs)
        return self._client


class FakeSdkClient:
    def __init__(
        self,
        *,
        responses: list[object] | None = None,
        request_handler: (Callable[[str, dict[str, object], float | None], object] | None) = None,
        pid: int = 4321,
    ) -> None:
        self.responses = list(responses or [])
        self.request_handler = request_handler
        self.started = False
        self.closed = False
        self.initialize_calls: list[tuple[dict[str, object], float | None]] = []
        self.request_calls: list[tuple[str, dict[str, object], float | None]] = []
        self.connect_kwargs: dict[str, object] | None = None
        self.sent_messages: list[dict[str, object]] = []
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._transport = FakeSdkTransport(pid=pid, sent_messages=self.sent_messages)

    async def start(self) -> FakeSdkClient:
        self.started = True
        return self

    async def initialize(
        self,
        params: dict[str, object],
        *,
        timeout: float | None = None,
    ) -> object:
        self.initialize_calls.append((params, timeout))
        return {"serverInfo": {"name": "fake"}}

    async def request(
        self,
        method: str,
        params: dict[str, object],
        *,
        timeout: float | None = None,
    ) -> object:
        self.request_calls.append((method, params, timeout))
        if self.request_handler is not None:
            response = self.request_handler(method, params, timeout)
        else:
            response = self.responses.pop(0)

        if isinstance(response, FakeSdkProtocolError | FakeSdkTimeoutError | FakeSdkTransportError):
            raise response
        return response

    async def close(self) -> None:
        self.closed = True
        self._transport._proc.returncode = 0


class FakeSdkTransport:
    def __init__(self, *, pid: int, sent_messages: list[dict[str, object]]) -> None:
        self._proc = FakeSdkProcess(pid=pid)
        self._sent_messages = sent_messages

    async def send(self, message: dict[str, object]) -> None:
        self._sent_messages.append(message)


class FakeSdkProcess:
    def __init__(self, *, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.stdin = None
        self.stdout = None
        self.stderr = None


def install_fake_sdk_bindings(
    monkeypatch: Any,
    client: FakeSdkClient,
) -> None:
    monkeypatch.setattr(
        client_module,
        "_load_sdk_bindings",
        lambda: client_module._SdkBindings(
            client_class=FakeSdkClientFactory(client),
            protocol_error_class=FakeSdkProtocolError,
            timeout_error_class=FakeSdkTimeoutError,
            transport_error_class=FakeSdkTransportError,
        ),
    )
