from __future__ import annotations

import asyncio
import json
import sys
import textwrap
from pathlib import Path

import pytest
from symphony.agent_runner import (
    AppServerProtocolError,
    AppServerResponseTimeoutError,
    AppServerSession,
    start_app_server_session,
)
from symphony.common.types import ServiceInfo

FAKE_SERVER_SOURCE = """
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

mode = os.environ["FAKE_SERVER_MODE"]
log_path = Path(os.environ["FAKE_SERVER_LOG"])


def log_message(message: dict[str, object]) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message) + "\\n")


def send(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\\n")
    sys.stdout.flush()


def read_message() -> dict[str, object]:
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    message = json.loads(line)
    log_message(message)
    return message


initialize = read_message()
if mode == "timeout_initialize":
    time.sleep(0.2)
    raise SystemExit(0)

send({"id": initialize["id"], "result": {"serverInfo": {"name": "fake"}}})

initialized = read_message()
if mode == "stderr":
    print("stderr noise", file=sys.stderr, flush=True)

thread_start = read_message()
if mode == "missing_thread_id":
    send({"id": thread_start["id"], "result": {"thread": {}}})
    raise SystemExit(0)

send({"method": "thread/started", "params": {"thread": {"id": "thr_notice"}}})
send({"id": thread_start["id"], "result": {"thread": {"id": "thr_123"}}})

turn_start = read_message()
if mode == "missing_turn_id":
    send({"id": turn_start["id"], "result": {"turn": {}}})
    raise SystemExit(0)

if mode == "interleaved":
    send({"method": "item/started", "params": {"item": {"id": "itm_1"}}})

send({"id": turn_start["id"], "result": {"turn": {"id": "turn_456"}}})
"""


def test_start_app_server_session_completes_handshake_and_returns_ids(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"

    async def run_test() -> AppServerSession:
        session = await run_handshake(tmp_path, log_path=log_path, mode="success")
        try:
            assert session.thread_id == "thr_123"
            assert session.turn_id == "turn_456"
            assert session.session_id == "thr_123-turn_456"
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
            assert session.session_id == "thr_123-turn_456"
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
            assert session.session_id == "thr_123-turn_456"
            assert session.stderr_lines == ["stderr noise"]
        finally:
            await session.aclose()

    asyncio.run(run_test())


async def run_handshake(
    tmp_path: Path,
    *,
    log_path: Path,
    mode: str,
    read_timeout_ms: int = 1_000,
) -> AppServerSession:
    server_script = tmp_path / "fake_app_server.py"
    server_script.write_text(textwrap.dedent(FAKE_SERVER_SOURCE), encoding="utf-8")
    log_path.write_text("", encoding="utf-8")

    command = f"FAKE_SERVER_MODE={mode} FAKE_SERVER_LOG={log_path} {sys.executable} {server_script}"

    return await start_app_server_session(
        command=command,
        workspace_path=tmp_path,
        prompt_text="Summarize this repo.",
        title="SYM-123: Handshake",
        service_info=ServiceInfo(name="symphony", version="0.1.0"),
        approval_policy="never",
        thread_sandbox="workspace-write",
        turn_sandbox_policy={"type": "workspace-write"},
        read_timeout_ms=read_timeout_ms,
        capabilities={},
        model="gpt-5.1-codex",
    )
