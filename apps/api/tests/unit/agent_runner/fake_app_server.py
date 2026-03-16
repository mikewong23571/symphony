from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, cast

mode = os.environ["FAKE_SERVER_MODE"]
log_path = Path(os.environ["FAKE_SERVER_LOG"])


def log_message(message: dict[str, object]) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(message) + "\n")


def send(message: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def read_message() -> dict[str, object]:
    line = sys.stdin.readline()
    if not line:
        raise SystemExit(0)
    message = cast(dict[str, object], json.loads(line))
    log_message(message)
    return message


def send_turn_completed(turn_id: str, index: int = 1) -> None:
    send(
        {
            "method": "turn/completed",
            "params": {
                "turn": {"id": turn_id},
                "usage": {
                    "input_tokens": 10 * index,
                    "output_tokens": 5 * index,
                    "total_tokens": 15 * index,
                },
            },
        }
    )


def perform_handshake() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
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

    if mode == "thread_started_notice":
        send({"method": "thread/started", "params": {"thread": {"id": "thr_notice"}}})

    send({"id": thread_start["id"], "result": {"thread": {"id": "thr_123"}}})

    turn_start = read_message()
    if mode == "missing_turn_id":
        send({"id": turn_start["id"], "result": {"turn": {}}})
        raise SystemExit(0)
    if mode == "turn_start_error":
        send(
            {
                "id": turn_start["id"],
                "error": {
                    "code": -32600,
                    "message": "sandbox policy rejected",
                },
            }
        )
        raise SystemExit(0)

    if mode == "interleaved":
        send({"method": "item/started", "params": {"item": {"id": "itm_1"}}})

    send({"id": turn_start["id"], "result": {"turn": {"id": "turn_1"}}})
    return initialize, initialized, thread_start, turn_start


def read_followup_turn(expected_turn_number: int) -> dict[str, Any]:
    turn_start = read_message()
    if mode == "multi_turn_interleaved_approval":
        send({"id": "approval_2", "method": "approval/request", "params": {"kind": "command"}})
    send(
        {
            "id": turn_start["id"],
            "result": {"turn": {"id": f"turn_{expected_turn_number}"}},
        }
    )
    if mode == "multi_turn_interleaved_approval":
        approval_response = read_message()
        if approval_response.get("id") != "approval_2":
            raise SystemExit(2)
    return turn_start


_ = perform_handshake()

if mode in {"success", "interleaved", "stderr", "thread_started_notice"}:
    raise SystemExit(0)

if mode == "stream_success":
    send({"method": "item/started", "params": {"item": {"id": "itm_1"}}})
    send_turn_completed("turn_1")
    raise SystemExit(0)

if mode == "huge_stream_success":
    send({"method": "item/started", "params": {"blob": "x" * 1_200_000}})
    send_turn_completed("turn_1")
    raise SystemExit(0)

if mode == "turn_failed":
    send(
        {
            "method": "turn/failed",
            "params": {
                "error": {"code": "turn_failed", "message": "The turn failed."},
                "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            },
        }
    )
    raise SystemExit(0)

if mode == "turn_cancelled":
    send(
        {
            "method": "turn/cancelled",
            "params": {
                "message": "The turn was cancelled.",
                "usage": {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5},
            },
        }
    )
    raise SystemExit(0)

if mode == "malformed_stream":
    sys.stdout.write("{not-json}\n")
    sys.stdout.flush()
    raise SystemExit(0)

if mode == "eof_after_turn_start":
    raise SystemExit(0)

if mode == "approval_request":
    send({"id": "approval_1", "method": "approval/request", "params": {"kind": "command"}})
    approval_response = read_message()
    if approval_response.get("id") != "approval_1":
        raise SystemExit(2)
    send_turn_completed("turn_1")
    raise SystemExit(0)

if mode == "tool_call_unsupported":
    send(
        {
            "id": "tool_1",
            "method": "item/tool/call",
            "params": {"toolCall": {"toolName": "unknown_tool", "arguments": {}}},
        }
    )
    tool_response = read_message()
    if tool_response.get("id") != "tool_1":
        raise SystemExit(2)
    send_turn_completed("turn_1")
    raise SystemExit(0)

if mode == "tool_call_supported":
    send(
        {
            "id": "tool_1",
            "method": "item/tool/call",
            "params": {
                "name": "linear_graphql",
                "arguments": {"query": "query Viewer { viewer { id } }"},
            },
        }
    )
    tool_response = read_message()
    if tool_response.get("id") != "tool_1":
        raise SystemExit(2)
    result = tool_response.get("result")
    if not isinstance(result, dict) or result.get("success") is not True:
        raise SystemExit(2)
    send_turn_completed("turn_1")
    raise SystemExit(0)

if mode == "user_input_required":
    send(
        {
            "id": "input_1",
            "method": "item/tool/requestUserInput",
            "params": {"prompt": "Need operator input"},
        }
    )
    time.sleep(0.2)
    raise SystemExit(0)

if mode == "silent_stream":
    time.sleep(0.2)
    raise SystemExit(0)

if mode == "noisy_stream":
    for index in range(20):
        send({"method": "item/updated", "params": {"index": index}})
        time.sleep(0.02)
    raise SystemExit(0)

if mode in {"multi_turn", "multi_turn_interleaved_approval"}:
    total_turns = int(os.environ.get("FAKE_SERVER_TURNS", "2"))
    send_turn_completed("turn_1", index=1)
    for turn_number in range(2, total_turns + 1):
        read_followup_turn(turn_number)
        send_turn_completed(f"turn_{turn_number}", index=turn_number)
    raise SystemExit(0)

raise SystemExit(1)
