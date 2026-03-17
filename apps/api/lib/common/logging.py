from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

MAX_LOG_VALUE_LENGTH = 240
_SAFE_TOKEN_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._/:@+"
)


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    *,
    fields: Mapping[str, object | None],
) -> None:
    parts = [f"event={_format_token(event)}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    message = " ".join(parts)
    try:
        logger.log(level, message)
    except Exception as exc:
        _emit_fallback_warning(logger=logger, message=message, exc=exc)


def _format_value(value: object) -> str:
    normalized = _normalize_value(value)
    if isinstance(normalized, str):
        text = _truncate_text(normalized)
        if _is_safe_token(text):
            return text
        return json.dumps(text)
    if isinstance(normalized, int | float | bool):
        return json.dumps(normalized)
    return _format_json_value(normalized)


def _normalize_value(value: object) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes | bytearray | memoryview):
        return bytes(value).decode("utf-8", errors="replace")
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _normalize_value(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize_value(item) for item in value]
    if isinstance(value, set | frozenset):
        return [_normalize_value(item) for item in sorted(value, key=repr)]
    return str(value)


def _format_json_value(value: Any) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return json.dumps(_truncate_text(text))


def _format_token(value: str) -> str:
    text = _truncate_text(value)
    if _is_safe_token(text):
        return text
    return json.dumps(text)


def _truncate_text(value: str) -> str:
    if len(value) <= MAX_LOG_VALUE_LENGTH:
        return value
    return f"{value[: MAX_LOG_VALUE_LENGTH - 14]}...[truncated]"


def _is_safe_token(value: str) -> bool:
    # Empty values should stay quoted so `key=""` remains distinguishable from a missing field.
    return bool(value) and all(character in _SAFE_TOKEN_CHARS for character in value)


def _emit_fallback_warning(
    *,
    logger: logging.Logger,
    message: str,
    exc: Exception,
) -> None:
    fallback_message = " ".join(
        [
            "event=log_sink_failed",
            f"logger_name={_format_value(logger.name)}",
            f"error_code={_format_value(exc.__class__.__name__)}",
            f"message={_format_value(str(exc) or exc.__class__.__name__)}",
            f"original_message={_format_value(message)}",
        ]
    )
    if _emit_with_last_resort(fallback_message):
        return
    try:
        sys.stderr.write(fallback_message + "\n")
        sys.stderr.flush()
    except Exception:
        return


def _emit_with_last_resort(message: str) -> bool:
    handler = logging.lastResort
    if handler is None:
        return False
    try:
        record = logging.LogRecord(
            name="lib.common.logging",
            level=logging.ERROR,
            pathname=__file__,
            lineno=0,
            msg=message,
            args=(),
            exc_info=None,
        )
        handler.handle(record)
    except Exception:
        return False
    return True
