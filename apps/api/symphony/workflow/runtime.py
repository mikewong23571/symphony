from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from .config import (
    ServiceConfig,
    WorkflowConfigError,
    build_service_config,
    validate_dispatch_config,
)
from .loader import (
    MissingWorkflowFileError,
    WorkflowDefinition,
    WorkflowError,
    parse_workflow_definition,
    resolve_workflow_path,
)

DEFAULT_WORKFLOW_WATCH_INTERVAL_SECONDS = 0.5
logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class WorkflowReloadError:
    code: str
    message: str
    observed_at: datetime


@dataclass(slots=True, frozen=True)
class WorkflowRuntimeStatus:
    path: Path
    loaded_at: datetime | None
    last_checked_at: datetime | None
    last_error: WorkflowReloadError | None


type WorkflowReloadListener = Callable[[], None]


class WorkflowRuntime:
    def __init__(
        self,
        workflow_path: str | Path | None = None,
        *,
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.path = resolve_workflow_path(workflow_path, cwd=cwd)
        self._env = env if env is not None else os.environ
        self._lock = threading.RLock()
        self._reload_lock = threading.Lock()
        self._definition: WorkflowDefinition | None = None
        self._config: ServiceConfig | None = None
        self._loaded_at: datetime | None = None
        self._last_checked_at: datetime | None = None
        self._last_error: WorkflowReloadError | None = None
        self._signature: str | None = None
        self._reload_listeners: list[WorkflowReloadListener] = []
        self._watch_stop_event: threading.Event | None = None
        self._watch_thread: threading.Thread | None = None

    @property
    def definition(self) -> WorkflowDefinition:
        with self._lock:
            definition = self._definition
        if definition is None:
            raise RuntimeError("WorkflowRuntime has not loaded a workflow definition yet.")
        return definition

    @property
    def config(self) -> ServiceConfig:
        with self._lock:
            config = self._config
        if config is None:
            raise RuntimeError("WorkflowRuntime has not loaded a service config yet.")
        return config

    @property
    def last_error(self) -> WorkflowReloadError | None:
        with self._lock:
            return self._last_error

    def get_status(self) -> WorkflowRuntimeStatus:
        with self._lock:
            return WorkflowRuntimeStatus(
                path=self.path,
                loaded_at=self._loaded_at,
                last_checked_at=self._last_checked_at,
                last_error=self._last_error,
            )

    def load_initial(self) -> ServiceConfig:
        with self._reload_lock:
            definition, config, signature = self._load_current_workflow()
            loaded_at = datetime.now(UTC)
            with self._lock:
                self._definition = definition
                self._config = config
                self._signature = signature
                self._loaded_at = loaded_at
                self._last_checked_at = loaded_at
                self._last_error = None
        return config

    def reload_if_changed(self) -> bool:
        return self._reload_if_changed() == "config_changed"

    def add_reload_listener(self, listener: WorkflowReloadListener) -> None:
        with self._lock:
            if listener not in self._reload_listeners:
                self._reload_listeners.append(listener)

    def remove_reload_listener(self, listener: WorkflowReloadListener) -> None:
        with self._lock:
            self._reload_listeners = [
                registered_listener
                for registered_listener in self._reload_listeners
                if registered_listener != listener
            ]

    def start_watching(
        self,
        *,
        interval_seconds: float = DEFAULT_WORKFLOW_WATCH_INTERVAL_SECONDS,
    ) -> None:
        with self._lock:
            if self._config is None:
                raise RuntimeError("WorkflowRuntime must load the workflow before watching it.")
            watch_thread = self._watch_thread
            if watch_thread is not None and watch_thread.is_alive():
                return
            stop_event = threading.Event()
            self._watch_stop_event = stop_event
            self._watch_thread = threading.Thread(
                target=self._watch_loop,
                args=(stop_event, max(interval_seconds, 0.05)),
                daemon=True,
                name="symphony-workflow-watch",
            )
            watch_thread = self._watch_thread

        if watch_thread is not None:
            watch_thread.start()

    def stop_watching(self) -> None:
        with self._lock:
            stop_event = self._watch_stop_event
            watch_thread = self._watch_thread
            self._watch_stop_event = None
            self._watch_thread = None

        if stop_event is not None:
            stop_event.set()
        if watch_thread is not None and watch_thread.is_alive():
            watch_thread.join(timeout=1.0)

    def _load_current_workflow(
        self,
    ) -> tuple[WorkflowDefinition, ServiceConfig, str | None]:
        contents = self._read_workflow_contents()
        definition = parse_workflow_definition(contents)
        config = build_service_config(definition, env=self._env)
        validate_dispatch_config(config)
        return definition, config, _workflow_signature(contents)

    def _read_signature(self) -> str | None:
        try:
            contents = self._read_workflow_contents()
        except WorkflowError:
            return None
        return _workflow_signature(contents)

    def _read_workflow_contents(self) -> str:
        try:
            return self.path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MissingWorkflowFileError(f"Could not read workflow file: {self.path}") from exc

    def _reload_if_changed(self) -> str:
        with self._reload_lock:
            with self._lock:
                if self._config is None:
                    raise RuntimeError("WorkflowRuntime has not loaded a service config yet.")
                previous_signature = self._signature

            checked_at = datetime.now(UTC)
            current_signature = self._read_signature()
            with self._lock:
                self._last_checked_at = checked_at
            if current_signature == previous_signature:
                return "no_change"

            try:
                definition, config, signature = self._load_current_workflow()
            except (WorkflowError, WorkflowConfigError) as exc:
                with self._lock:
                    self._last_error = WorkflowReloadError(
                        code=exc.code,
                        message=exc.message,
                        observed_at=checked_at,
                    )
                    self._signature = current_signature
                return "error_changed"

            with self._lock:
                self._definition = definition
                self._config = config
                self._signature = signature
                self._loaded_at = checked_at
                self._last_error = None
            return "config_changed"

    def _watch_loop(self, stop_event: threading.Event, interval_seconds: float) -> None:
        with self._lock:
            if self._config is None:
                logger.warning(
                    "Workflow watch loop started before the initial workflow load completed."
                )
                return

        while not stop_event.wait(interval_seconds):
            try:
                outcome = self._reload_if_changed()
            except Exception:
                logger.exception("Workflow watch reload failed unexpectedly; retrying.")
                continue
            if outcome != "no_change":
                self._notify_reload_listeners()

    def _notify_reload_listeners(self) -> None:
        with self._lock:
            listeners = list(self._reload_listeners)

        for listener in listeners:
            try:
                listener()
            except Exception:
                logger.warning(
                    "Workflow reload listener failed; continuing with other listeners.",
                    exc_info=True,
                )


def _workflow_signature(contents: str) -> str:
    return sha256(contents.encode("utf-8")).hexdigest()
