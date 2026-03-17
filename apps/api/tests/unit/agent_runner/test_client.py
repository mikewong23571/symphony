from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest
from lib.common.types import ServiceInfo
from runtime.agent_runner import (
    AppServerProtocolError,
    AppServerResponseTimeoutError,
    AppServerSession,
    read_protocol_message,
    start_app_server_session,
    start_next_turn,
)

from .helpers import (
    FAKE_APP_SERVER_PATH,
    FakeSdkClient,
    FakeSdkProtocolError,
    install_fake_sdk_bindings,
    start_fake_app_server_session,
)


def test_start_app_server_session_completes_handshake_and_returns_ids(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> AppServerSession:
        session = await run_handshake(tmp_path, log_path=log_path, mode="success")
        try:
            assert session.thread_id == "thr_123"
            assert session.turn_id == "turn_1"
            assert session.session_id == "thr_123-turn_1"
            return session
        finally:
            await session.aclose()

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [message["method"] for message in logged_messages] == [
        "initialize",
        "thread/start",
        "turn/start",
    ]
    assert logged_messages[1]["params"]["cwd"] == str(tmp_path.resolve())
    assert logged_messages[2]["params"]["threadId"] == "thr_123"
    assert logged_messages[2]["params"]["title"] == "SYM-123: Handshake"
    assert logged_messages[2]["params"]["sandboxPolicy"] == {"type": "workspaceWrite"}


def test_start_app_server_session_ignores_interleaved_notifications(tmp_path: Path) -> None:
    async def run_test() -> None:
        session = await run_handshake(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="interleaved",
        )
        try:
            assert session.session_id == "thr_123-turn_1"
        finally:
            await session.aclose()

    asyncio.run(run_test())


def test_start_app_server_session_advertises_dynamic_tools(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> None:
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=log_path,
            mode="success",
            dynamic_tools=[
                {
                    "name": "linear_graphql",
                    "description": "Execute Linear GraphQL.",
                    "inputSchema": {"type": "object"},
                }
            ],
        )
        try:
            assert session.session_id == "thr_123-turn_1"
        finally:
            await session.aclose()

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[1]["params"]["dynamicTools"] == [
        {
            "name": "linear_graphql",
            "description": "Execute Linear GraphQL.",
            "inputSchema": {"type": "object"},
        }
    ]


def test_start_app_server_session_uses_sdk_handshake_and_returns_ids(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_client = FakeSdkClient(
        responses=[
            {"thread": {"id": "thr_sdk"}},
            {"turn": {"id": "turn_sdk"}},
        ]
    )
    install_fake_sdk_bindings(monkeypatch, fake_client)

    async def run_test() -> None:
        session = await start_app_server_session(
            command="codex app-server",
            workspace_path=tmp_path,
            prompt_text="Summarize this repo.",
            title="SYM-123: SDK Handshake",
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            approval_policy="never",
            thread_sandbox="workspace-write",
            turn_sandbox_policy={"type": "workspace-write"},
            read_timeout_ms=1_500,
            capabilities={"roots": True},
            dynamic_tools=[
                {
                    "name": "linear_graphql",
                    "description": "Execute Linear GraphQL.",
                    "inputSchema": {"type": "object"},
                }
            ],
            model="gpt-5.1-codex",
        )
        try:
            assert session.thread_id == "thr_sdk"
            assert session.turn_id == "turn_sdk"
            assert session.session_id == "thr_sdk-turn_sdk"
            assert session.process.pid == 4321
        finally:
            await session.aclose()

    asyncio.run(run_test())

    assert fake_client.started is True
    assert fake_client.closed is True
    assert fake_client.connect_kwargs == {
        "command": ["bash", "-lc", "codex app-server"],
        "cwd": str(tmp_path.resolve()),
        "connect_timeout": 1.5,
        "request_timeout": 1.5,
        "inactivity_timeout": None,
    }
    assert fake_client.initialize_calls == [
        (
            {
                "clientInfo": {"name": "symphony", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True, "roots": True},
            },
            1.5,
        )
    ]
    assert fake_client.request_calls == [
        (
            "thread/start",
            {
                "cwd": str(tmp_path.resolve()),
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
                "model": "gpt-5.1-codex",
                "dynamicTools": [
                    {
                        "name": "linear_graphql",
                        "description": "Execute Linear GraphQL.",
                        "inputSchema": {"type": "object"},
                    }
                ],
            },
            1.5,
        ),
        (
            "turn/start",
            {
                "threadId": "thr_sdk",
                "input": [{"type": "text", "text": "Summarize this repo."}],
                "cwd": str(tmp_path.resolve()),
                "title": "SYM-123: SDK Handshake",
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "workspaceWrite"},
            },
            1.5,
        ),
    ]


def test_start_app_server_session_maps_sdk_protocol_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_client = FakeSdkClient(
        responses=[FakeSdkProtocolError("thread/start failed: bad request")]
    )
    install_fake_sdk_bindings(monkeypatch, fake_client)

    with pytest.raises(AppServerProtocolError, match="thread/start failed: bad request"):
        asyncio.run(
            start_app_server_session(
                command="codex app-server",
                workspace_path=tmp_path,
                prompt_text="Summarize this repo.",
                title="SYM-123: SDK Handshake",
                service_info=ServiceInfo(name="symphony", version="0.1.0"),
                approval_policy="never",
                thread_sandbox="workspace-write",
                turn_sandbox_policy={"type": "workspace-write"},
                read_timeout_ms=1_000,
            )
        )

    assert fake_client.closed is True


def test_start_app_server_session_supports_notification_reads_and_continuation_turns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    turn_counter = 0

    def request_handler(method: str, params: dict[str, object], timeout: float | None) -> object:
        nonlocal turn_counter
        assert timeout == 1.0
        if method == "thread/start":
            return {"thread": {"id": "thr_sdk"}}
        if method == "turn/start":
            turn_counter += 1
            if turn_counter == 1:
                return {"turn": {"id": "turn_1"}}
            fake_client._notifications.put_nowait(
                {"id": "approval_2", "method": "approval/request", "params": {"kind": "command"}}
            )
            return {"turn": {"id": "turn_2"}}
        raise AssertionError(f"Unexpected method: {method}")

    fake_client = FakeSdkClient(request_handler=request_handler)
    install_fake_sdk_bindings(monkeypatch, fake_client)

    async def run_test() -> None:
        session = await start_app_server_session(
            command="codex app-server",
            workspace_path=tmp_path,
            prompt_text="Summarize this repo.",
            title="SYM-123: SDK Handshake",
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            approval_policy="never",
            thread_sandbox="workspace-write",
            turn_sandbox_policy={"type": "workspace-write"},
            read_timeout_ms=1_000,
        )
        try:
            fake_client._notifications.put_nowait(
                {"method": "item/started", "params": {"item": {"id": "itm_1"}}}
            )
            message = await read_protocol_message(session)
            assert message["method"] == "item/started"

            turn_id = await start_next_turn(
                session,
                prompt_text="Continue the work.",
                title="SYM-123: Turn 2",
                approval_policy="never",
                sandbox_policy={"type": "workspace-write"},
                cwd=tmp_path,
                read_timeout_ms=1_000,
            )
            assert turn_id == "turn_2"
            assert session.session_id == "thr_sdk-turn_2"

            approval_request = await read_protocol_message(session)
            assert approval_request["id"] == "approval_2"
        finally:
            await session.aclose()

    asyncio.run(run_test())

    assert fake_client.started is True
    assert fake_client.closed is True
    assert fake_client.request_calls == [
        (
            "thread/start",
            {
                "cwd": str(tmp_path.resolve()),
                "approvalPolicy": "never",
                "sandbox": "workspace-write",
            },
            1.0,
        ),
        (
            "turn/start",
            {
                "threadId": "thr_sdk",
                "input": [{"type": "text", "text": "Summarize this repo."}],
                "cwd": str(tmp_path.resolve()),
                "title": "SYM-123: SDK Handshake",
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "workspaceWrite"},
            },
            1.0,
        ),
        (
            "turn/start",
            {
                "threadId": "thr_sdk",
                "input": [{"type": "text", "text": "Continue the work."}],
                "cwd": str(tmp_path.resolve()),
                "title": "SYM-123: Turn 2",
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "workspaceWrite"},
            },
            1.0,
        ),
    ]


@pytest.mark.parametrize("mode", ["missing_thread_id", "missing_turn_id"])
def test_start_app_server_session_rejects_missing_nested_ids(
    tmp_path: Path,
    mode: str,
) -> None:
    with pytest.raises(AppServerProtocolError, match="missing result"):
        asyncio.run(run_handshake(tmp_path, log_path=tmp_path / "messages.jsonl", mode=mode))


def test_start_app_server_session_surfaces_response_error_details(tmp_path: Path) -> None:
    with pytest.raises(
        AppServerProtocolError,
        match=r"turn/start failed: sandbox policy rejected",
    ):
        asyncio.run(
            run_handshake(
                tmp_path,
                log_path=tmp_path / "messages.jsonl",
                mode="turn_start_error",
            )
        )


def test_start_app_server_session_times_out_waiting_for_response(tmp_path: Path) -> None:
    with pytest.raises(AppServerResponseTimeoutError, match="app-server handshake response"):
        asyncio.run(
            run_handshake(
                tmp_path,
                log_path=tmp_path / "messages.jsonl",
                mode="timeout_initialize",
                read_timeout_ms=50,
            )
        )


def test_start_app_server_session_keeps_stderr_separate_from_stdout_protocol(
    tmp_path: Path,
) -> None:
    async def run_test() -> None:
        session = await run_handshake(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="stderr",
        )
        await session.aclose()
        assert session.session_id == "thr_123-turn_1"
        assert session.stderr_lines == ["stderr noise"]

    asyncio.run(run_test())


def test_start_app_server_session_forwards_stderr_lines_to_callback(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"
    log_path.write_text("", encoding="utf-8")
    command = (
        f"FAKE_SERVER_MODE=stderr FAKE_SERVER_LOG={log_path} "
        f"{sys.executable} {FAKE_APP_SERVER_PATH}"
    )

    async def run_test() -> None:
        diagnostics: list[dict[str, object | None]] = []

        session = await start_app_server_session(
            command=command,
            workspace_path=tmp_path,
            prompt_text="Summarize this repo.",
            title="SYM-123: Handshake",
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            approval_policy="never",
            thread_sandbox="workspace-write",
            turn_sandbox_policy={"type": "workspace-write"},
            read_timeout_ms=1_000,
            stderr_callback=lambda line, context: diagnostics.append(
                {
                    "line": line,
                    "session_id": context.session_id,
                    "thread_id": context.thread_id,
                    "turn_id": context.turn_id,
                    "pid": context.codex_app_server_pid,
                }
            ),
        )
        pid = session.process.pid
        await session.aclose()
        assert session.stderr_lines == ["stderr noise"]
        assert diagnostics == [
            {
                "line": "stderr noise",
                "session_id": None,
                "thread_id": None,
                "turn_id": None,
                "pid": pid,
            }
        ]

    asyncio.run(run_test())


def test_read_protocol_message_reads_stream_notifications(tmp_path: Path) -> None:
    async def run_test() -> None:
        session = await run_handshake(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="stream_success",
        )
        try:
            message = await read_protocol_message(session)
            assert message["method"] == "item/started"
        finally:
            await session.aclose()

    asyncio.run(run_test())


def test_start_next_turn_reuses_thread_and_updates_session_ids(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> None:
        session = await run_handshake(tmp_path, log_path=log_path, mode="multi_turn")
        try:
            await read_protocol_message(session)
            turn_id = await start_next_turn(
                session,
                prompt_text="Continue the work.",
                title="SYM-123: Turn 2",
                approval_policy="never",
                sandbox_policy={"type": "workspace-write"},
                cwd=tmp_path,
                read_timeout_ms=1_000,
            )
            assert turn_id == "turn_2"
            assert session.session_id == "thr_123-turn_2"
        finally:
            await session.aclose()

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[3]["method"] == "turn/start"
    assert logged_messages[3]["params"]["threadId"] == "thr_123"
    assert logged_messages[3]["params"]["input"][0]["text"] == "Continue the work."


async def run_handshake(
    tmp_path: Path,
    *,
    log_path: Path,
    mode: str,
    read_timeout_ms: int = 1_000,
) -> AppServerSession:
    if not FAKE_APP_SERVER_PATH.is_file():
        raise AssertionError("fake_app_server.py is missing.")
    return await start_fake_app_server_session(
        tmp_path,
        log_path=log_path,
        mode=mode,
        read_timeout_ms=read_timeout_ms,
    )
