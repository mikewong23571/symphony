from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True, frozen=True)
class UsageSnapshot:
    input_tokens: int
    output_tokens: int
    total_tokens: int


@dataclass(slots=True, frozen=True)
class AgentRuntimeEvent:
    event: str
    timestamp: datetime
    session_id: str
    thread_id: str
    turn_id: str
    codex_app_server_pid: int | None
    usage: UsageSnapshot | None
    payload: Mapping[str, Any]


@dataclass(slots=True, frozen=True)
class TurnResult:
    outcome: str
    error_code: str | None
    message: str | None
    usage: UsageSnapshot | None


def utcnow() -> datetime:
    return datetime.now(UTC)


def extract_usage_snapshot(message: Mapping[str, Any]) -> UsageSnapshot | None:
    payload_candidates: list[Any] = [message]

    for key in ("params", "result"):
        nested = message.get(key)
        if isinstance(nested, Mapping):
            payload_candidates.append(nested)
            usage_candidate = nested.get("usage")
            if isinstance(usage_candidate, Mapping):
                payload_candidates.append(usage_candidate)

    for candidate in payload_candidates:
        usage = _coerce_usage_snapshot(candidate)
        if usage is not None:
            return usage

    return None


def _coerce_usage_snapshot(value: Any) -> UsageSnapshot | None:
    if not isinstance(value, Mapping):
        return None

    direct = _build_usage_snapshot(value)
    if direct is not None:
        return direct

    for key in ("usage", "tokenUsage"):
        nested = value.get(key)
        if isinstance(nested, Mapping):
            nested_usage = _build_usage_snapshot(nested)
            if nested_usage is not None:
                return nested_usage

    return None


def _build_usage_snapshot(value: Mapping[str, Any]) -> UsageSnapshot | None:
    input_tokens = _coerce_int(
        _get_first_present(
            value,
            "input_tokens",
            "inputTokens",
            "prompt_tokens",
            "promptTokens",
        )
    )
    output_tokens = _coerce_int(
        _get_first_present(
            value,
            "output_tokens",
            "outputTokens",
            "completion_tokens",
            "completionTokens",
        )
    )
    total_tokens = _coerce_int(_get_first_present(value, "total_tokens", "totalTokens"))

    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None

    resolved_input = input_tokens or 0
    resolved_output = output_tokens or 0
    resolved_total = total_tokens
    if resolved_total is None:
        resolved_total = resolved_input + resolved_output

    return UsageSnapshot(
        input_tokens=resolved_input,
        output_tokens=resolved_output,
        total_tokens=resolved_total,
    )


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return None
        try:
            return int(normalized)
        except ValueError:
            return None
    return None


def _get_first_present(value: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None
