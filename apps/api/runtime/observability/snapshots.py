from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast


def isoformat_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def refresh_runtime_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    generated_at = datetime.now(UTC)
    revision = snapshot.get("revision")
    if not isinstance(revision, int) or revision < 0:
        snapshot["revision"] = 0
    base_generated_at = parse_snapshot_timestamp(snapshot.get("generated_at"))
    codex_totals = snapshot.get("codex_totals")
    running_rows = snapshot.get("running")

    if (
        isinstance(codex_totals, dict)
        and base_generated_at is not None
        and isinstance(running_rows, list)
    ):
        base_seconds = cast(float | int | None, codex_totals.get("seconds_running"))
        if isinstance(base_seconds, int | float):
            active_runtime_at_base = 0.0
            active_runtime_now = 0.0
            for row in running_rows:
                if not isinstance(row, dict):
                    continue
                started_at = parse_snapshot_timestamp(row.get("started_at"))
                if started_at is None:
                    continue
                active_runtime_at_base += max(
                    (base_generated_at - started_at).total_seconds(),
                    0.0,
                )
                active_runtime_now += max((generated_at - started_at).total_seconds(), 0.0)

            ended_runtime = max(float(base_seconds) - active_runtime_at_base, 0.0)
            codex_totals["seconds_running"] = round(ended_runtime + active_runtime_now, 3)

    snapshot["generated_at"] = isoformat_utc(generated_at)
    return snapshot


def parse_snapshot_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
