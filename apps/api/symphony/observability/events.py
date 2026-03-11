from __future__ import annotations

import copy
import threading
import time
from collections import deque
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .snapshots import isoformat_utc

DEFAULT_RUNTIME_INVALIDATION_HISTORY_LIMIT = 128

_invalidation_condition = threading.Condition()
_invalidation_events: deque[dict[str, Any]] = deque(
    maxlen=DEFAULT_RUNTIME_INVALIDATION_HISTORY_LIMIT
)
_next_invalidation_sequence = 0


def publish_runtime_invalidation(
    event_type: str,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    event_payload = dict(payload or {})
    event_payload.pop("sequence", None)
    event_payload.pop("event", None)
    event_payload.pop("emitted_at", None)

    global _next_invalidation_sequence
    with _invalidation_condition:
        _next_invalidation_sequence += 1
        event = {
            "sequence": _next_invalidation_sequence,
            "event": event_type,
            "emitted_at": isoformat_utc(datetime.now(UTC)),
            **event_payload,
        }
        _invalidation_events.append(event)
        _invalidation_condition.notify_all()

    return copy.deepcopy(event)


def wait_for_runtime_invalidation(
    *,
    after_sequence: int | None,
    timeout_seconds: float,
) -> dict[str, Any] | None:
    deadline = time.monotonic() + max(timeout_seconds, 0.0)
    with _invalidation_condition:
        event = _find_runtime_invalidation_locked(after_sequence)
        if event is not None:
            return copy.deepcopy(event)

        while True:
            remaining_seconds = deadline - time.monotonic()
            if remaining_seconds <= 0:
                return None

            _invalidation_condition.wait(timeout=remaining_seconds)
            event = _find_runtime_invalidation_locked(after_sequence)
            if event is not None:
                return copy.deepcopy(event)


def clear_runtime_invalidations() -> None:
    global _next_invalidation_sequence
    with _invalidation_condition:
        _invalidation_events.clear()
        _next_invalidation_sequence = 0


def _find_runtime_invalidation_locked(
    after_sequence: int | None,
) -> dict[str, Any] | None:
    if not _invalidation_events:
        return None

    if after_sequence is None:
        return _invalidation_events[-1]

    for event in _invalidation_events:
        if int(event["sequence"]) > after_sequence:
            return event

    return None
