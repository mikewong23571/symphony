from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from symphony.agent_runner import (
    AppServerProtocolError,
    AppServerResponseTimeoutError,
    AppServerSession,
    read_protocol_message,
    start_next_turn,
)

from .helpers import FAKE_APP_SERVER_PATH, start_fake_app_server_session


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
        "initialized",
        "thread/start",
        "turn/start",
    ]
    assert logged_messages[2]["params"]["cwd"] == str(tmp_path.resolve())
    assert logged_messages[3]["params"]["threadId"] == "thr_123"
    assert logged_messages[3]["params"]["title"] == "SYM-123: Handshake"


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


@pytest.mark.parametrize("mode", ["missing_thread_id", "missing_turn_id"])
def test_start_app_server_session_rejects_missing_nested_ids(
    tmp_path: Path,
    mode: str,
) -> None:
    with pytest.raises(AppServerProtocolError, match="missing result"):
        asyncio.run(run_handshake(tmp_path, log_path=tmp_path / "messages.jsonl", mode=mode))


def test_start_app_server_session_times_out_waiting_for_response(tmp_path: Path) -> None:
    with pytest.raises(AppServerResponseTimeoutError, match="response id 1"):
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
        try:
            assert session.session_id == "thr_123-turn_1"
            assert session.stderr_lines == ["stderr noise"]
        finally:
            await session.aclose()

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
    assert logged_messages[4]["method"] == "turn/start"
    assert logged_messages[4]["params"]["threadId"] == "thr_123"
    assert logged_messages[4]["params"]["input"][0]["text"] == "Continue the work."


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
