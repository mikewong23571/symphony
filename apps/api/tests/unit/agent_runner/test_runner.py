from __future__ import annotations

import asyncio
import json
from pathlib import Path

from symphony.agent_runner import AgentRuntimeEvent, start_next_turn, stream_turn

from .helpers import collect_events, start_fake_app_server_session


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
