from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from lib.common.types import ServiceInfo
from runtime.agent_runner import (
    AgentRuntimeEvent,
    AppServerSession,
    start_next_turn,
    stream_turn,
)

from .helpers import (
    FakeSdkClient,
    collect_events,
    install_fake_sdk_bindings,
    start_fake_app_server_session,
)


def test_stream_turn_completes_and_emits_runtime_events(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="stream_success",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert result.usage is not None
        assert result.usage.total_tokens == 15
        assert [event.event for event in events] == ["notification", "turn_completed"]

    asyncio.run(run_test())


def test_stream_turn_handles_huge_single_line_notifications(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="huge_stream_success",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert [event.event for event in events] == ["notification", "turn_completed"]

    asyncio.run(run_test())


def test_stream_turn_maps_failed_terminal_events(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="turn_failed",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "failed"
        assert result.error_code == "turn_failed"
        assert [event.event for event in events] == ["turn_failed"]

    asyncio.run(run_test())


def test_stream_turn_maps_cancelled_terminal_events(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="turn_cancelled",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "cancelled"
        assert result.error_code == "turn_cancelled"
        assert [event.event for event in events] == ["turn_cancelled"]

    asyncio.run(run_test())


def test_stream_turn_handles_malformed_protocol_lines(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="malformed_stream",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "failed"
        assert result.error_code == "response_error"
        assert [event.event for event in events] == ["malformed"]

    asyncio.run(run_test())


def test_stream_turn_handles_stdout_close_before_terminal_message(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="eof_after_turn_start",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "failed"
        assert result.error_code == "response_error"
        assert [event.event for event in events] == ["malformed"]

    asyncio.run(run_test())


def test_stream_turn_auto_approves_requests(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=log_path,
            mode="approval_request",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert [event.event for event in events] == [
            "approval_auto_approved",
            "turn_completed",
        ]

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[-1] == {"id": "approval_1", "result": {"approved": True}}


def test_stream_turn_rejects_unsupported_tool_calls(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=log_path,
            mode="tool_call_unsupported",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert [event.event for event in events] == [
            "unsupported_tool_call",
            "turn_completed",
        ]

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[-1]["id"] == "tool_1"
    assert logged_messages[-1]["result"]["success"] is False
    assert logged_messages[-1]["result"]["error"] == "unsupported_tool_call"


def test_stream_turn_executes_supported_tool_calls(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=log_path,
            mode="tool_call_supported",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                tool_executor=lambda tool, arguments: {
                    "success": True,
                    "output": json.dumps(
                        {
                            "tool": tool,
                            "arguments": arguments,
                        }
                    ),
                },
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert [event.event for event in events] == [
            "tool_call_completed",
            "turn_completed",
        ]

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[-1]["id"] == "tool_1"
    assert logged_messages[-1]["result"]["success"] is True
    assert logged_messages[-1]["result"]["contentItems"] == [
        {
            "type": "inputText",
            "text": logged_messages[-1]["result"]["output"],
        }
    ]


def test_stream_turn_handles_messages_buffered_during_continuation_turn_start(
    tmp_path: Path,
) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=log_path,
            mode="multi_turn_interleaved_approval",
        )
        try:
            first_result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
            assert first_result.outcome == "completed"

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

            second_result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
            assert second_result.outcome == "completed"
        finally:
            await session.aclose()

        assert [event.event for event in events] == [
            "turn_completed",
            "approval_auto_approved",
            "turn_completed",
        ]

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[-1] == {"id": "approval_2", "result": {"approved": True}}


def test_stream_turn_fails_fast_on_user_input_required(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="user_input_required",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "failed"
        assert result.error_code == "turn_input_required"
        assert [event.event for event in events] == ["turn_input_required"]

    asyncio.run(run_test())


def test_stream_turn_detects_stalls(tmp_path: Path) -> None:
    async def run_test() -> None:
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="silent_stream",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=50,
            )
        finally:
            await session.aclose()

        assert result.outcome == "stalled"
        assert result.error_code == "stalled"

    asyncio.run(run_test())


def test_stream_turn_enforces_turn_timeout_even_with_activity(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="noisy_stream",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=75,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "timed_out"
        assert result.error_code == "turn_timeout"
        assert events

    asyncio.run(run_test())


def test_stream_turn_fails_when_approval_requires_operator(tmp_path: Path) -> None:
    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await start_fake_app_server_session(
            tmp_path,
            log_path=tmp_path / "messages.jsonl",
            mode="approval_request",
            approval_policy="on-request",
        )
        try:
            result = await stream_turn(
                session,
                approval_policy="on-request",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "failed"
        assert result.error_code == "approval_required"
        assert [event.event for event in events] == ["turn_ended_with_error"]

    asyncio.run(run_test())


def test_stream_turn_auto_approves_sdk_requests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_client = FakeSdkClient(
        request_handler=lambda method, params, timeout: (
            {"thread": {"id": "thr_sdk"}}
            if method == "thread/start"
            else {"turn": {"id": "turn_1"}}
        )
    )
    install_fake_sdk_bindings(monkeypatch, fake_client)

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await _start_sdk_session(tmp_path)
        try:
            fake_client._notifications.put_nowait(
                {"id": "approval_1", "method": "approval/request", "params": {"kind": "command"}}
            )
            fake_client._notifications.put_nowait(
                {
                    "method": "turn/completed",
                    "params": {
                        "turn": {"id": "turn_1"},
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                }
            )
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert [event.event for event in events] == [
            "approval_auto_approved",
            "turn_completed",
        ]

    asyncio.run(run_test())

    assert fake_client.sent_messages == [{"id": "approval_1", "result": {"approved": True}}]


def test_stream_turn_executes_sdk_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake_client = FakeSdkClient(
        request_handler=lambda method, params, timeout: (
            {"thread": {"id": "thr_sdk"}}
            if method == "thread/start"
            else {"turn": {"id": "turn_1"}}
        )
    )
    install_fake_sdk_bindings(monkeypatch, fake_client)

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        session = await _start_sdk_session(tmp_path)
        try:
            fake_client._notifications.put_nowait(
                {
                    "id": "tool_1",
                    "method": "item/tool/call",
                    "params": {
                        "name": "linear_graphql",
                        "arguments": {"query": "query Viewer { viewer { id } }"},
                    },
                }
            )
            fake_client._notifications.put_nowait(
                {
                    "method": "turn/completed",
                    "params": {
                        "turn": {"id": "turn_1"},
                        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
                    },
                }
            )
            result = await stream_turn(
                session,
                approval_policy="never",
                turn_timeout_ms=1_000,
                stall_timeout_ms=1_000,
                tool_executor=lambda tool, arguments: {
                    "success": True,
                    "output": json.dumps({"tool": tool, "arguments": arguments}),
                },
                on_event=lambda event: collect_events(events, event),
            )
        finally:
            await session.aclose()

        assert result.outcome == "completed"
        assert [event.event for event in events] == [
            "tool_call_completed",
            "turn_completed",
        ]

    asyncio.run(run_test())

    first_result = fake_client.sent_messages[0]["result"]
    assert isinstance(first_result, dict)
    content_items = first_result["contentItems"]
    assert isinstance(content_items, list)
    assert fake_client.sent_messages[0]["id"] == "tool_1"
    assert first_result["success"] is True
    assert content_items == [
        {
            "type": "inputText",
            "text": first_result["output"],
        }
    ]


async def _start_sdk_session(tmp_path: Path) -> AppServerSession:
    from runtime.agent_runner import start_app_server_session

    return await start_app_server_session(
        command="codex app-server",
        workspace_path=tmp_path,
        prompt_text="Summarize this repo.",
        title="SYM-123: Handshake",
        service_info=ServiceInfo(name="symphony", version="0.1.0"),
        approval_policy="never",
        thread_sandbox="workspace-write",
        turn_sandbox_policy={"type": "workspace-write"},
        read_timeout_ms=1_000,
        capabilities={},
        model="gpt-5.1-codex",
    )
