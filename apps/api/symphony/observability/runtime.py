from __future__ import annotations

import fcntl
import json
import os
import re
import tempfile
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol, cast

from .snapshots import parse_snapshot_timestamp, refresh_runtime_snapshot

RUNTIME_SNAPSHOT_PATH_ENV_VAR = "SYMPHONY_RUNTIME_SNAPSHOT_PATH"
RUNTIME_SNAPSHOT_MAX_AGE_SECONDS_ENV_VAR = "SYMPHONY_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS"
DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS = 120
DEFAULT_RUNTIME_SNAPSHOT_FILENAME = "symphony-runtime-snapshot.json"
_RUNTIME_SNAPSHOT_SCOPE_MARKERS = ("pyproject.toml", ".git", "WORKFLOW.md")


class RuntimeSnapshotProvider(Protocol):
    def get_runtime_snapshot(self) -> dict[str, Any]: ...


class RuntimeSnapshotUnavailableError(RuntimeError):
    pass


_provider_lock = threading.Lock()
_provider: RuntimeSnapshotProvider | None = None


def register_runtime_snapshot_provider(provider: RuntimeSnapshotProvider) -> None:
    global _provider
    with _provider_lock:
        _provider = provider


def clear_runtime_snapshot_provider(provider: RuntimeSnapshotProvider | None = None) -> None:
    global _provider
    with _provider_lock:
        if provider is None or _provider is provider:
            _provider = None


def get_runtime_snapshot_path() -> Path:
    configured_path = os.environ.get(RUNTIME_SNAPSHOT_PATH_ENV_VAR, "").strip()
    if configured_path:
        return Path(configured_path).expanduser()
    return _get_default_runtime_snapshot_path()


def get_runtime_snapshot_refresh_interval_seconds(*, poll_interval_ms: int) -> float:
    max_age_seconds = _get_runtime_snapshot_max_age_seconds()
    poll_interval_seconds = max(poll_interval_ms / 1000, 0.5)
    return min(poll_interval_seconds, max_age_seconds / 2)


def publish_runtime_snapshot(
    snapshot: Mapping[str, Any],
    *,
    owner_token: str | None = None,
) -> Path:
    path = get_runtime_snapshot_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _serialize_runtime_snapshot(snapshot)
        with _runtime_snapshot_file_lock(path):
            _replace_runtime_snapshot_file(path=path, payload=payload)
            if owner_token is not None:
                _replace_runtime_snapshot_owner_token(path=path, owner_token=owner_token)
    except (OSError, TypeError, ValueError) as exc:
        raise RuntimeSnapshotUnavailableError(
            f"Runtime snapshot could not be written to {path}: {exc}."
        ) from exc

    return path


def clear_runtime_snapshot_file(*, owner_token: str | None = None) -> bool:
    path = get_runtime_snapshot_path()
    owner_path = _get_runtime_snapshot_owner_path(path)
    if not path.exists() and not owner_path.exists() and not path.parent.exists():
        return False

    try:
        with _runtime_snapshot_file_lock(path):
            if owner_token is not None and _read_runtime_snapshot_owner_token(path) != owner_token:
                return False
            path.unlink(missing_ok=True)
            owner_path.unlink(missing_ok=True)
    except OSError as exc:
        raise RuntimeSnapshotUnavailableError(
            f"Runtime snapshot could not be cleared: {exc}."
        ) from exc

    return True


def load_runtime_snapshot() -> dict[str, Any]:
    path = get_runtime_snapshot_path()
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeSnapshotUnavailableError(
            f"Runtime snapshot is unavailable at {path}."
        ) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeSnapshotUnavailableError(
            f"Runtime snapshot could not be read from {path}: {exc}."
        ) from exc

    if not isinstance(payload, dict):
        raise RuntimeSnapshotUnavailableError(f"Runtime snapshot at {path} must be a JSON object.")

    _ensure_snapshot_is_fresh(cast(dict[str, Any], payload), path)
    return refresh_runtime_snapshot(cast(dict[str, Any], payload))


def get_runtime_snapshot() -> dict[str, Any]:
    with _provider_lock:
        provider = _provider

    if provider is not None:
        return provider.get_runtime_snapshot()

    return load_runtime_snapshot()


def _ensure_snapshot_is_fresh(snapshot: dict[str, Any], path: Path) -> None:
    expires_at = parse_snapshot_timestamp(snapshot.get("expires_at"))
    if expires_at is not None and datetime.now(UTC) > expires_at:
        raise RuntimeSnapshotUnavailableError(
            f"Runtime snapshot at {path} is stale (expired at {snapshot['expires_at']})."
        )

    generated_at = parse_snapshot_timestamp(snapshot.get("generated_at"))
    if generated_at is None:
        return

    max_age_seconds = _get_runtime_snapshot_max_age_seconds()
    max_age = timedelta(seconds=max_age_seconds)
    if datetime.now(UTC) - generated_at > max_age:
        raise RuntimeSnapshotUnavailableError(
            f"Runtime snapshot at {path} is stale (older than {max_age_seconds} seconds)."
        )


def _get_runtime_snapshot_max_age_seconds() -> int:
    configured = os.environ.get(RUNTIME_SNAPSHOT_MAX_AGE_SECONDS_ENV_VAR, "").strip()
    if not configured:
        return DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS

    try:
        value = int(configured)
    except ValueError:
        return DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS

    return max(value, 1)


def _get_default_runtime_snapshot_path() -> Path:
    scope_root = _resolve_runtime_snapshot_scope_root()
    scope_name = _sanitize_snapshot_scope_name(scope_root.name)
    scope_hash = sha256(str(scope_root).encode("utf-8")).hexdigest()[:12]
    base_name = Path(DEFAULT_RUNTIME_SNAPSHOT_FILENAME)
    scoped_name = f"{base_name.stem}-{scope_name}-{scope_hash}{base_name.suffix}"
    return Path(tempfile.gettempdir()) / scoped_name


def _resolve_runtime_snapshot_scope_root() -> Path:
    module_path = Path(__file__).resolve()
    for candidate in module_path.parents:
        if any((candidate / marker).exists() for marker in _RUNTIME_SNAPSHOT_SCOPE_MARKERS):
            return candidate
    return module_path.parent


def _sanitize_snapshot_scope_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return normalized or "symphony"


def _serialize_runtime_snapshot(snapshot: Mapping[str, Any]) -> str:
    return json.dumps(snapshot, sort_keys=True)


def _replace_runtime_snapshot_file(*, path: Path, payload: str) -> None:
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


def _replace_runtime_snapshot_owner_token(*, path: Path, owner_token: str) -> None:
    owner_path = _get_runtime_snapshot_owner_path(path)
    temp_path: Path | None = None
    try:
        temp_file_descriptor, temp_file_name = tempfile.mkstemp(
            prefix=f".{owner_path.name}.",
            suffix=".tmp",
            dir=path.parent,
            text=True,
        )
        temp_path = Path(temp_file_name)
        with os.fdopen(temp_file_descriptor, "w", encoding="utf-8") as handle:
            handle.write(owner_token)
        temp_path.replace(owner_path)
    except OSError:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _read_runtime_snapshot_owner_token(path: Path) -> str | None:
    owner_path = _get_runtime_snapshot_owner_path(path)
    try:
        return owner_path.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def _get_runtime_snapshot_owner_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.owner")


def _get_runtime_snapshot_lock_path(path: Path) -> Path:
    return path.with_name(f".{path.name}.lock")


@contextmanager
def _runtime_snapshot_file_lock(path: Path) -> Iterator[None]:
    lock_path = _get_runtime_snapshot_lock_path(path)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
