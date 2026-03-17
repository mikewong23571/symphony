from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from runtime.observability.snapshots import isoformat_utc, parse_snapshot_timestamp


class RecoveryStateError(RuntimeError):
    code = "recovery_state_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass(slots=True, frozen=True)
class PersistedSessionMetadata:
    session_id: str | None
    thread_id: str | None
    turn_id: str | None
    turn_count: int
    last_event: str | None
    last_event_at: datetime | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    codex_app_server_pid: int | None

    def to_snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "thread_id": self.thread_id,
            "turn_id": self.turn_id,
            "turn_count": self.turn_count,
            "last_event": self.last_event,
            "last_event_at": isoformat_utc(self.last_event_at),
            "tokens": {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
            },
            "codex_app_server_pid": self.codex_app_server_pid,
        }


@dataclass(slots=True, frozen=True)
class RecoveryRetryState:
    issue_id: str
    issue_identifier: str
    attempt: int
    due_at: datetime
    workspace_path: Path
    error: str | None
    prior_session: PersistedSessionMetadata | None = None

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "issue_id": self.issue_id,
            "issue_identifier": self.issue_identifier,
            "attempt": self.attempt,
            "due_at": isoformat_utc(self.due_at),
            "workspace_path": str(self.workspace_path),
            "error": self.error,
        }
        if self.prior_session is not None:
            payload["prior_session"] = self.prior_session.to_snapshot()
        return payload


@dataclass(slots=True, frozen=True)
class RecoveryRunningState:
    issue_id: str
    issue_identifier: str
    attempt: int | None
    workspace_path: Path
    started_at: datetime
    session: PersistedSessionMetadata

    def to_payload(self) -> dict[str, Any]:
        return {
            "issue_id": self.issue_id,
            "issue_identifier": self.issue_identifier,
            "attempt": self.attempt,
            "workspace_path": str(self.workspace_path),
            "started_at": isoformat_utc(self.started_at),
            "session": self.session.to_snapshot(),
        }


@dataclass(slots=True, frozen=True)
class RecoveryState:
    running: tuple[RecoveryRunningState, ...]
    retrying: tuple[RecoveryRetryState, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "running": [entry.to_payload() for entry in self.running],
            "retrying": [entry.to_payload() for entry in self.retrying],
        }


def load_recovery_state(path: Path) -> RecoveryState | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RecoveryStateError(f"Recovery state could not be read from {path}: {exc}.") from exc

    if not isinstance(payload, dict):
        raise RecoveryStateError(f"Recovery state at {path} must be a JSON object.")

    running_rows = payload.get("running")
    retry_rows = payload.get("retrying")
    if not isinstance(running_rows, list) or not isinstance(retry_rows, list):
        raise RecoveryStateError(
            f"Recovery state at {path} must contain 'running' and 'retrying' lists."
        )

    return RecoveryState(
        running=tuple(_parse_running_state(path, row) for row in running_rows),
        retrying=tuple(_parse_retry_state(path, row) for row in retry_rows),
    )


def publish_recovery_state(path: Path, state: RecoveryState) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _replace_recovery_file(path=path, payload=json.dumps(state.to_payload(), sort_keys=True))
    except (OSError, TypeError, ValueError) as exc:
        raise RecoveryStateError(f"Recovery state could not be written to {path}: {exc}.") from exc
    return path


def _parse_running_state(path: Path, row: object) -> RecoveryRunningState:
    if not isinstance(row, dict):
        raise RecoveryStateError(f"Recovery state at {path} contains an invalid running row.")

    session_payload = row.get("session")
    if not isinstance(session_payload, dict):
        raise RecoveryStateError(f"Recovery state at {path} is missing running session metadata.")

    return RecoveryRunningState(
        issue_id=_require_string(path, row.get("issue_id"), "running.issue_id"),
        issue_identifier=_require_string(
            path,
            row.get("issue_identifier"),
            "running.issue_identifier",
        ),
        attempt=_optional_int(path, row.get("attempt"), "running.attempt"),
        workspace_path=_require_path(path, row.get("workspace_path"), "running.workspace_path"),
        started_at=_require_datetime(path, row.get("started_at"), "running.started_at"),
        session=_parse_session_state(path, session_payload, "running.session"),
    )


def _parse_retry_state(path: Path, row: object) -> RecoveryRetryState:
    if not isinstance(row, dict):
        raise RecoveryStateError(f"Recovery state at {path} contains an invalid retry row.")

    prior_session_payload = row.get("prior_session")
    prior_session = None
    if prior_session_payload is not None:
        if not isinstance(prior_session_payload, dict):
            raise RecoveryStateError(
                f"Recovery state at {path} contains an invalid retry prior session row."
            )
        prior_session = _parse_session_state(path, prior_session_payload, "retrying.prior_session")

    return RecoveryRetryState(
        issue_id=_require_string(path, row.get("issue_id"), "retrying.issue_id"),
        issue_identifier=_require_string(
            path,
            row.get("issue_identifier"),
            "retrying.issue_identifier",
        ),
        attempt=_require_int(path, row.get("attempt"), "retrying.attempt"),
        due_at=_require_datetime(path, row.get("due_at"), "retrying.due_at"),
        workspace_path=_require_path(path, row.get("workspace_path"), "retrying.workspace_path"),
        error=_optional_string(path, row.get("error"), "retrying.error"),
        prior_session=prior_session,
    )


def _parse_session_state(
    path: Path,
    payload: dict[str, Any],
    label: str,
) -> PersistedSessionMetadata:
    tokens = payload.get("tokens")
    if not isinstance(tokens, dict):
        raise RecoveryStateError(f"Recovery state at {path} is missing {label}.tokens.")

    return PersistedSessionMetadata(
        session_id=_optional_string(path, payload.get("session_id"), f"{label}.session_id"),
        thread_id=_optional_string(path, payload.get("thread_id"), f"{label}.thread_id"),
        turn_id=_optional_string(path, payload.get("turn_id"), f"{label}.turn_id"),
        turn_count=_require_int(path, payload.get("turn_count"), f"{label}.turn_count"),
        last_event=_optional_string(path, payload.get("last_event"), f"{label}.last_event"),
        last_event_at=_optional_datetime(
            path,
            payload.get("last_event_at"),
            f"{label}.last_event_at",
        ),
        input_tokens=_require_int(
            path,
            tokens.get("input_tokens"),
            f"{label}.tokens.input_tokens",
        ),
        output_tokens=_require_int(
            path,
            tokens.get("output_tokens"),
            f"{label}.tokens.output_tokens",
        ),
        total_tokens=_require_int(
            path,
            tokens.get("total_tokens"),
            f"{label}.tokens.total_tokens",
        ),
        codex_app_server_pid=_optional_int(
            path,
            payload.get("codex_app_server_pid"),
            f"{label}.codex_app_server_pid",
        ),
    )


def _optional_string(path: Path, value: object, label: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RecoveryStateError(f"Recovery state at {path} contains an invalid {label}.")
    normalized = value.strip()
    return normalized or None


def _require_string(path: Path, value: object, label: str) -> str:
    normalized = _optional_string(path, value, label)
    if normalized is None:
        raise RecoveryStateError(f"Recovery state at {path} is missing {label}.")
    return normalized


def _require_path(path: Path, value: object, label: str) -> Path:
    raw_value = _require_string(path, value, label)
    return Path(raw_value)


def _require_int(path: Path, value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecoveryStateError(f"Recovery state at {path} contains an invalid {label}.")
    return value


def _optional_int(path: Path, value: object, label: str) -> int | None:
    if value is None:
        return None
    return _require_int(path, value, label)


def _require_datetime(path: Path, value: object, label: str) -> datetime:
    parsed = parse_snapshot_timestamp(value)
    if parsed is None:
        raise RecoveryStateError(f"Recovery state at {path} contains an invalid {label}.")
    return parsed


def _optional_datetime(path: Path, value: object, label: str) -> datetime | None:
    if value is None:
        return None
    return _require_datetime(path, value, label)


def _replace_recovery_file(*, path: Path, payload: str) -> None:
    temp_path: Path | None = None
    try:
        temp_file_descriptor, temp_file_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temp_path = Path(temp_file_name)
        with os.fdopen(temp_file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        temp_path.replace(path)
    except OSError:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


RecoverySessionState = PersistedSessionMetadata
