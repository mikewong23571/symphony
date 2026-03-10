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
    is_absolute_total: bool = True


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
    method = _coerce_method_name(message.get("method"))
    if method in {
        "turn/completed",
        "turn/failed",
        "turn/cancelled",
        "thread/tokenUsage/updated",
    }:
        absolute_usage = _extract_nested_usage(message, ("params", "result"))
        if absolute_usage is not None:
            return _build_usage_snapshot(absolute_usage, is_absolute_total=True)
        # Fall through when a known absolute-total event omits parseable `usage`/`tokenUsage`.
        # This lets explicit wrappers like `last_token_usage` still be classified as delta-only
        # instead of being dropped as an untyped unknown payload.

    total_usage_wrapper = _extract_named_usage_payload(
        message,
        ("total_token_usage", "totalTokenUsage"),
    )
    if total_usage_wrapper is not None:
        return _build_usage_snapshot(total_usage_wrapper, is_absolute_total=True)

    last_usage_wrapper = _extract_named_usage_payload(
        message,
        ("last_token_usage", "lastTokenUsage"),
    )
    if last_usage_wrapper is not None:
        return _build_usage_snapshot(last_usage_wrapper, is_absolute_total=False)

    return None


def _build_usage_snapshot(
    value: Mapping[str, Any],
    *,
    is_absolute_total: bool,
) -> UsageSnapshot | None:
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
        is_absolute_total=is_absolute_total,
    )


def _extract_nested_usage(
    message: Mapping[str, Any],
    container_keys: tuple[str, ...],
) -> Mapping[str, Any] | None:
    payload_candidates: list[Mapping[str, Any]] = [message]

    for key in container_keys:
        nested = message.get(key)
        if isinstance(nested, Mapping):
            payload_candidates.append(nested)

    for candidate in payload_candidates:
        direct = _extract_usage_mapping(candidate)
        if direct is not None:
            return direct

    return None


def _extract_named_usage_payload(
    message: Mapping[str, Any],
    keys: tuple[str, ...],
) -> Mapping[str, Any] | None:
    payload_candidates: list[Mapping[str, Any]] = [message]

    for container_key in ("params", "result"):
        nested = message.get(container_key)
        if isinstance(nested, Mapping):
            payload_candidates.append(nested)

    for candidate in payload_candidates:
        for key in keys:
            nested = candidate.get(key)
            if isinstance(nested, Mapping):
                return nested

    return None


def _extract_usage_mapping(candidate: Mapping[str, Any]) -> Mapping[str, Any] | None:
    if _contains_usage_keys(candidate):
        return candidate

    for key in ("usage", "tokenUsage"):
        nested = candidate.get(key)
        if isinstance(nested, Mapping) and _contains_usage_keys(nested):
            return nested

    return None


def _contains_usage_keys(value: Mapping[str, Any]) -> bool:
    return any(
        key in value
        for key in (
            "input_tokens",
            "inputTokens",
            "prompt_tokens",
            "promptTokens",
            "output_tokens",
            "outputTokens",
            "completion_tokens",
            "completionTokens",
            "total_tokens",
            "totalTokens",
        )
    )


def _coerce_method_name(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized:
        return None
    return normalized


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
