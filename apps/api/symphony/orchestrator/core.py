from __future__ import annotations

import asyncio
import logging
import warnings
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from symphony.agent_runner import AgentRuntimeEvent, AttemptResult, run_issue_attempt
from symphony.common.types import ServiceInfo
from symphony.tracker import Issue, LinearTrackerClient
from symphony.workflow import ServiceConfig, validate_dispatch_config
from symphony.workspace import WorkspaceError, WorkspaceManager
from symphony.workspace.hooks import run_hook_best_effort

CONTINUATION_RETRY_DELAY_MS = 1_000
FAILURE_RETRY_BASE_DELAY_MS = 10_000
logger = logging.getLogger(__name__)


class TrackerClientProtocol(Protocol):
    def fetch_candidate_issues(self) -> list[Issue]: ...

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]: ...

    def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]: ...


class WorkerRunner(Protocol):
    def __call__(
        self,
        *,
        issue: Issue,
        attempt: int | None,
        config: ServiceConfig,
        service_info: ServiceInfo,
        tracker_client: TrackerClientProtocol,
        on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None,
        workspace_manager: WorkspaceManager | None,
    ) -> Coroutine[Any, Any, AttemptResult]: ...


@dataclass(slots=True)
class RetryEntry:
    issue_id: str
    identifier: str
    attempt: int
    due_at_ms: float
    timer_handle: asyncio.Task[None] | None
    error: str | None


@dataclass(slots=True)
class RunningEntry:
    issue: Issue
    attempt: int | None
    worker_task: asyncio.Task[AttemptResult]
    monitor_task: asyncio.Task[None]
    started_at: datetime
    session_id: str | None = None
    thread_id: str | None = None
    turn_id: str | None = None
    codex_app_server_pid: int | None = None
    last_codex_event: str | None = None
    last_codex_timestamp: datetime | None = None
    last_codex_message: str | None = None
    codex_input_tokens: int = 0
    codex_output_tokens: int = 0
    codex_total_tokens: int = 0
    last_reported_input_tokens: int = 0
    last_reported_output_tokens: int = 0
    last_reported_total_tokens: int = 0


@dataclass(slots=True, frozen=True)
class RetrySchedule:
    issue_id: str
    identifier: str
    attempt: int
    delay_ms: int
    error: str | None


@dataclass(slots=True)
class OrchestratorState:
    poll_interval_ms: int
    max_concurrent_agents: int
    running: dict[str, RunningEntry] = field(default_factory=dict)
    claimed: set[str] = field(default_factory=set)
    retry_attempts: dict[str, RetryEntry] = field(default_factory=dict)
    completed: set[str] = field(default_factory=set)
    runtime_seconds_total: float = 0.0


class Orchestrator:
    def __init__(
        self,
        *,
        config: ServiceConfig,
        tracker_client: TrackerClientProtocol | None = None,
        worker_runner: WorkerRunner = run_issue_attempt,
        workspace_manager: WorkspaceManager | None = None,
        service_info: ServiceInfo | None = None,
    ) -> None:
        self.config = config
        self.tracker_client = tracker_client or LinearTrackerClient(config.tracker)
        self.worker_runner = worker_runner
        self.workspace_manager = workspace_manager or WorkspaceManager(config.workspace.root)
        self.service_info = service_info or ServiceInfo(name="symphony", version="0.1.0")
        self.state = OrchestratorState(
            poll_interval_ms=config.polling.interval_ms,
            max_concurrent_agents=config.agent.max_concurrent_agents,
        )
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._started = False
        self._cancel_reasons: dict[str, str] = {}
        self._usage_semantics_warned = False

    async def startup(self) -> None:
        if self._started:
            return
        validate_dispatch_config(self.config)
        await self._startup_terminal_workspace_cleanup()
        self._started = True

    async def run_once(self) -> None:
        await self.startup()
        await self.tick()

    async def wait_for_running_workers(self) -> None:
        async with self._lock:
            monitor_tasks = [entry.monitor_task for entry in self.state.running.values()]

        if monitor_tasks:
            await asyncio.gather(*monitor_tasks, return_exceptions=True)

    async def run_forever(self) -> None:
        await self.startup()
        while not self._stop_event.is_set():
            await self.tick()
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self.state.poll_interval_ms / 1000,
                )
            except TimeoutError:
                continue

    async def aclose(self) -> None:
        self._stop_event.set()

        retry_entries = list(self.state.retry_attempts.values())
        for entry in retry_entries:
            if entry.timer_handle is not None:
                entry.timer_handle.cancel()

        running_entries = list(self.state.running.values())
        for running_entry in running_entries:
            running_entry.worker_task.cancel()

        monitor_tasks = [entry.monitor_task for entry in running_entries]
        if monitor_tasks:
            await asyncio.gather(*monitor_tasks, return_exceptions=True)

    async def tick(self) -> None:
        await self.reconcile_running_issues()

        try:
            validate_dispatch_config(self.config)
        except Exception:
            return

        try:
            candidate_issues = await asyncio.to_thread(self.tracker_client.fetch_candidate_issues)
        except Exception:
            return

        for issue in self._sort_issues_for_dispatch(candidate_issues):
            async with self._lock:
                if self._available_slots() <= 0:
                    break
                if not self._should_dispatch(issue):
                    continue
                await self._dispatch_issue(issue, attempt=None)

    async def reconcile_running_issues(self) -> None:
        await self._reconcile_stalled_runs()

        async with self._lock:
            running_ids = list(self.state.running.keys())
        if not running_ids:
            return

        try:
            refreshed_issues = await asyncio.to_thread(
                self.tracker_client.fetch_issue_states_by_ids,
                running_ids,
            )
        except Exception:
            return

        refreshed_by_id = {issue.id: issue for issue in refreshed_issues}
        for issue_id in running_ids:
            refreshed_issue = refreshed_by_id.get(issue_id)
            if refreshed_issue is None:
                continue
            if self._is_terminal_state(refreshed_issue.state):
                await self._terminate_running_issue(
                    issue_id,
                    reason="canceled_by_reconciliation",
                    cleanup_workspace=True,
                )
                continue
            if not self._is_active_state(refreshed_issue.state):
                await self._terminate_running_issue(
                    issue_id,
                    reason="canceled_by_reconciliation",
                    cleanup_workspace=False,
                )
                continue

            async with self._lock:
                running_entry = self.state.running.get(issue_id)
                if running_entry is not None:
                    running_entry.issue = refreshed_issue

    async def _reconcile_stalled_runs(self) -> None:
        if self.config.codex.stall_timeout_ms <= 0:
            return

        threshold_ms = self.config.codex.stall_timeout_ms
        now = datetime.now(UTC)
        stale_issue_ids: list[str] = []

        async with self._lock:
            for issue_id, running_entry in self.state.running.items():
                last_timestamp = running_entry.last_codex_timestamp or running_entry.started_at
                elapsed_ms = (now - last_timestamp).total_seconds() * 1000
                if elapsed_ms > threshold_ms:
                    stale_issue_ids.append(issue_id)

        for issue_id in stale_issue_ids:
            async with self._lock:
                current_entry = self.state.running.get(issue_id)
                if current_entry is None:
                    continue
                last_timestamp = current_entry.last_codex_timestamp or current_entry.started_at
                elapsed_ms = (datetime.now(UTC) - last_timestamp).total_seconds() * 1000
                if elapsed_ms <= threshold_ms:
                    continue
            await self._terminate_running_issue(
                issue_id,
                reason="stalled",
                cleanup_workspace=False,
            )

    async def _startup_terminal_workspace_cleanup(self) -> None:
        try:
            terminal_issues = await asyncio.to_thread(
                self.tracker_client.fetch_issues_by_states,
                self.config.tracker.terminal_states,
            )
        except Exception:
            return

        for issue in terminal_issues:
            try:
                await self._cleanup_workspace(issue.identifier)
            except Exception:
                continue

    async def _dispatch_issue(self, issue: Issue, *, attempt: int | None) -> None:
        async def on_event(event: AgentRuntimeEvent) -> None:
            await self._handle_worker_event(issue.id, event)

        worker_coro = self.worker_runner(
            issue=issue,
            attempt=attempt,
            config=self.config,
            service_info=self.service_info,
            tracker_client=self.tracker_client,
            on_event=on_event,
            workspace_manager=self.workspace_manager,
        )
        worker_task: asyncio.Task[AttemptResult] = asyncio.create_task(worker_coro)
        monitor_task = asyncio.create_task(self._monitor_worker(issue, attempt, worker_task))

        self.state.running[issue.id] = RunningEntry(
            issue=issue,
            attempt=attempt,
            worker_task=worker_task,
            monitor_task=monitor_task,
            started_at=datetime.now(UTC),
        )
        self.state.claimed.add(issue.id)
        existing_retry = self.state.retry_attempts.pop(issue.id, None)
        if existing_retry is not None and existing_retry.timer_handle is not None:
            existing_retry.timer_handle.cancel()

    async def _monitor_worker(
        self,
        issue: Issue,
        attempt: int | None,
        worker_task: asyncio.Task[AttemptResult],
    ) -> None:
        try:
            result = await worker_task
        except asyncio.CancelledError:
            status = self._cancel_reasons.pop(issue.id, "canceled_by_reconciliation")
            result = AttemptResult(
                status=status,
                issue=issue,
                attempt=attempt,
                workspace_path=self.workspace_manager.resolve_workspace_path(issue.identifier),
                session_id=None,
                thread_id=None,
                turn_id=None,
                turns_run=0,
                error_code=status,
                message=f"Worker was cancelled with reason '{status}'.",
            )
        except Exception as exc:
            result = AttemptResult(
                status="failed",
                issue=issue,
                attempt=attempt,
                workspace_path=self.workspace_manager.resolve_workspace_path(issue.identifier),
                session_id=None,
                thread_id=None,
                turn_id=None,
                turns_run=0,
                error_code="worker_runner_error",
                message=str(exc),
            )

        await self._handle_worker_exit(issue.id, result)

    async def _handle_worker_event(self, issue_id: str, event: AgentRuntimeEvent) -> None:
        async with self._lock:
            running_entry = self.state.running.get(issue_id)
            if running_entry is None:
                return

            running_entry.session_id = event.session_id
            running_entry.thread_id = event.thread_id
            running_entry.turn_id = event.turn_id
            running_entry.codex_app_server_pid = event.codex_app_server_pid
            running_entry.last_codex_event = event.event
            running_entry.last_codex_timestamp = event.timestamp
            running_entry.last_codex_message = str(dict(event.payload))

            if event.usage is not None:
                if not self._usage_semantics_warned:
                    warnings.warn(
                        (
                            "Codex usage event semantics are currently treated as cumulative "
                            "snapshots. TODO: confirm whether app-server usage payloads are "
                            "cumulative totals or per-event deltas before changing token "
                            "aggregation behavior."
                        ),
                        RuntimeWarning,
                        stacklevel=2,
                    )
                    self._usage_semantics_warned = True
                # TODO: Confirm whether event.usage values are cumulative snapshots or per-event
                # deltas. The current implementation preserves the latest reported values and keeps
                # last_reported_* as an anchor for future aggregation changes.
                running_entry.codex_input_tokens = event.usage.input_tokens
                running_entry.codex_output_tokens = event.usage.output_tokens
                running_entry.codex_total_tokens = event.usage.total_tokens
                running_entry.last_reported_input_tokens = event.usage.input_tokens
                running_entry.last_reported_output_tokens = event.usage.output_tokens
                running_entry.last_reported_total_tokens = event.usage.total_tokens

    async def _handle_worker_exit(self, issue_id: str, result: AttemptResult) -> None:
        cleanup_identifier: str | None = None
        retry_schedule: RetrySchedule | None = None

        async with self._lock:
            running_entry = self.state.running.pop(issue_id, None)
            self._cancel_reasons.pop(issue_id, None)
            if running_entry is None:
                return

            runtime_seconds = (datetime.now(UTC) - running_entry.started_at).total_seconds()
            self.state.runtime_seconds_total += runtime_seconds

            if result.status == "succeeded":
                self.state.completed.add(issue_id)
                if self._is_terminal_state(result.issue.state):
                    self.state.claimed.discard(issue_id)
                    cleanup_identifier = result.issue.identifier
                elif not self._is_active_state(result.issue.state):
                    self.state.claimed.discard(issue_id)
                else:
                    retry_schedule = RetrySchedule(
                        issue_id=issue_id,
                        identifier=result.issue.identifier,
                        attempt=1,
                        delay_ms=CONTINUATION_RETRY_DELAY_MS,
                        error=None,
                    )
            elif result.status == "canceled_by_reconciliation":
                self.state.claimed.discard(issue_id)
            else:
                next_attempt = 1 if result.attempt is None else result.attempt + 1
                retry_schedule = RetrySchedule(
                    issue_id=issue_id,
                    identifier=result.issue.identifier,
                    attempt=next_attempt,
                    delay_ms=self._compute_failure_retry_delay(next_attempt),
                    error=result.error_code or result.message,
                )

        if cleanup_identifier is not None:
            await self._cleanup_workspace(cleanup_identifier)
            return

        if retry_schedule is not None:
            await self._schedule_retry(
                issue_id=retry_schedule.issue_id,
                identifier=retry_schedule.identifier,
                attempt=retry_schedule.attempt,
                delay_ms=retry_schedule.delay_ms,
                error=retry_schedule.error,
            )

    async def _schedule_retry(
        self,
        *,
        issue_id: str,
        identifier: str,
        attempt: int,
        delay_ms: int,
        error: str | None,
    ) -> None:
        existing_entry = self.state.retry_attempts.pop(issue_id, None)
        current_task = asyncio.current_task()
        if (
            existing_entry is not None
            and existing_entry.timer_handle is not None
            and existing_entry.timer_handle is not current_task
        ):
            existing_entry.timer_handle.cancel()

        loop = asyncio.get_running_loop()
        due_at_ms = loop.time() * 1000 + delay_ms
        timer_handle = asyncio.create_task(self._retry_after_delay(issue_id, delay_ms))
        self.state.retry_attempts[issue_id] = RetryEntry(
            issue_id=issue_id,
            identifier=identifier,
            attempt=attempt,
            due_at_ms=due_at_ms,
            timer_handle=timer_handle,
            error=error,
        )
        self.state.claimed.add(issue_id)

    async def _retry_after_delay(self, issue_id: str, delay_ms: int) -> None:
        try:
            await asyncio.sleep(delay_ms / 1000)
            await self._dispatch_retry_issue(issue_id)
        except asyncio.CancelledError:
            return

    async def _dispatch_retry_issue(self, issue_id: str) -> None:
        async with self._lock:
            retry_entry = self.state.retry_attempts.get(issue_id)
        if retry_entry is None:
            return

        try:
            candidate_issues = await asyncio.to_thread(self.tracker_client.fetch_candidate_issues)
        except Exception:
            next_attempt = retry_entry.attempt + 1
            await self._schedule_retry(
                issue_id=issue_id,
                identifier=retry_entry.identifier,
                attempt=next_attempt,
                delay_ms=self._compute_failure_retry_delay(next_attempt),
                error="retry poll failed",
            )
            return

        issue = next(
            (candidate for candidate in candidate_issues if candidate.id == issue_id),
            None,
        )
        if issue is None:
            async with self._lock:
                self.state.retry_attempts.pop(issue_id, None)
                self.state.claimed.discard(issue_id)
            return

        async with self._lock:
            if self._available_slots() <= 0:
                await self._schedule_retry(
                    issue_id=issue_id,
                    identifier=issue.identifier,
                    attempt=retry_entry.attempt,
                    delay_ms=CONTINUATION_RETRY_DELAY_MS,
                    error="no available orchestrator slots",
                )
                return
            if not self._should_dispatch(issue, ignore_claimed_issue_id=issue_id):
                self.state.retry_attempts.pop(issue_id, None)
                self.state.claimed.discard(issue_id)
                return
            self.state.retry_attempts.pop(issue_id, None)
            await self._dispatch_issue(issue, attempt=retry_entry.attempt)

    async def _terminate_running_issue(
        self,
        issue_id: str,
        *,
        reason: str,
        cleanup_workspace: bool,
    ) -> None:
        async with self._lock:
            running_entry = self.state.running.get(issue_id)
            if running_entry is None:
                return
            self._cancel_reasons[issue_id] = reason
            running_entry.worker_task.cancel()
            issue_identifier = running_entry.issue.identifier
            monitor_task = running_entry.monitor_task

        await asyncio.gather(monitor_task, return_exceptions=True)

        if cleanup_workspace:
            await self._cleanup_workspace(issue_identifier)

    async def _cleanup_workspace(self, issue_identifier: str) -> None:
        try:
            workspace_path = self.workspace_manager.resolve_workspace_path(issue_identifier)
            if workspace_path.is_dir():
                await run_hook_best_effort(
                    name="before_remove",
                    script=self.config.hooks.before_remove,
                    cwd=workspace_path,
                    timeout_ms=self.config.hooks.timeout_ms,
                )
            self.workspace_manager.remove_workspace(issue_identifier)
        except (OSError, WorkspaceError) as exc:
            logger.warning(
                "Workspace cleanup failed for %s: %s",
                issue_identifier,
                exc,
            )
            return

    def _available_slots(self) -> int:
        return max(self.state.max_concurrent_agents - len(self.state.running), 0)

    def _compute_failure_retry_delay(self, attempt: int) -> int:
        max_retry_backoff_ms = int(self.config.agent.max_retry_backoff_ms)
        return int(
            min(
                FAILURE_RETRY_BASE_DELAY_MS * (2 ** max(attempt - 1, 0)),
                max_retry_backoff_ms,
            )
        )

    def _should_dispatch(
        self,
        issue: Issue,
        *,
        ignore_claimed_issue_id: str | None = None,
    ) -> bool:
        if not issue.id or not issue.identifier or not issue.title or not issue.state:
            return False
        if not self._is_active_state(issue.state) or self._is_terminal_state(issue.state):
            return False
        if issue.id in self.state.running:
            return False
        if issue.id in self.state.claimed and issue.id != ignore_claimed_issue_id:
            return False
        if self._available_slots() <= 0:
            return False
        if self._state_slots_exhausted(issue.state):
            return False
        if issue.state.strip().lower() == "todo" and self._has_non_terminal_blockers(issue):
            return False
        return True

    def _state_slots_exhausted(self, state_name: str) -> bool:
        normalized_state = state_name.strip().lower()
        configured_limit = self.config.agent.max_concurrent_agents_by_state.get(normalized_state)
        if configured_limit is None:
            return False

        running_count = sum(
            1
            for entry in self.state.running.values()
            if entry.issue.state.strip().lower() == normalized_state
        )
        return running_count >= configured_limit

    def _has_non_terminal_blockers(self, issue: Issue) -> bool:
        for blocker in issue.blocked_by:
            blocker_state = (blocker.state or "").strip()
            if blocker_state and not self._is_terminal_state(blocker_state):
                return True
        return False

    def _sort_issues_for_dispatch(self, issues: Sequence[Issue]) -> list[Issue]:
        return sorted(
            issues,
            key=lambda issue: (
                issue.priority if issue.priority is not None else 999,
                issue.created_at or datetime.max.replace(tzinfo=UTC),
                issue.identifier,
            ),
        )

    def _is_active_state(self, state_name: str) -> bool:
        normalized = state_name.strip().lower()
        return normalized in {value.strip().lower() for value in self.config.tracker.active_states}

    def _is_terminal_state(self, state_name: str) -> bool:
        normalized = state_name.strip().lower()
        return normalized in {
            value.strip().lower() for value in self.config.tracker.terminal_states
        }
