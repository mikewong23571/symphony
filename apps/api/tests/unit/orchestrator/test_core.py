from __future__ import annotations

import asyncio
import json
import warnings
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from symphony.agent_runner import AgentRuntimeEvent, AttemptResult
from symphony.agent_runner.events import UsageSnapshot
from symphony.observability.runtime import (
    RuntimeSnapshotUnavailableError,
    get_runtime_snapshot_path,
)
from symphony.observability.snapshots import parse_snapshot_timestamp
from symphony.orchestrator import Orchestrator
from symphony.orchestrator.core import CodexTotals, RunningEntry
from symphony.tracker.models import Issue, IssueBlocker
from symphony.workflow.config import ServiceConfig, build_service_config
from symphony.workflow.loader import WorkflowDefinition
from symphony.workspace import WorkspaceManager, WorkspaceRemoveError


class FakeTrackerClient:
    def __init__(
        self,
        *,
        candidate_batches: list[list[Issue]] | None = None,
        refresh_batches: list[list[Issue]] | None = None,
        terminal_issues: list[Issue] | None = None,
    ) -> None:
        self.candidate_batches = list(candidate_batches or [[]])
        self.refresh_batches = list(refresh_batches or [[]])
        self.terminal_issues = list(terminal_issues or [])

    def fetch_candidate_issues(self) -> list[Issue]:
        if self.candidate_batches:
            return self.candidate_batches.pop(0)
        return []

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]:
        if not issue_ids:
            return []
        if self.refresh_batches:
            return self.refresh_batches.pop(0)
        return []

    def fetch_issues_by_states(self, state_names: Sequence[str]) -> list[Issue]:
        return list(self.terminal_issues)


def build_issue(
    *,
    issue_id: str = "issue-1",
    identifier: str = "SYM-123",
    state: str = "In Progress",
    priority: int | None = 1,
    blocked_by: tuple[IssueBlocker, ...] = (),
) -> Issue:
    return Issue(
        id=issue_id,
        identifier=identifier,
        title="Implement orchestrator core",
        description="Run issue attempts via the orchestrator.",
        priority=priority,
        state=state,
        branch_name=None,
        url=None,
        labels=(),
        blocked_by=blocked_by,
        created_at=datetime(2026, 3, 10, tzinfo=UTC),
        updated_at=None,
    )


def build_config(
    *,
    tmp_path: Path,
    before_remove: str | None = None,
    stall_timeout_ms: int = 300_000,
) -> ServiceConfig:
    return build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                    "active_states": ["Todo", "In Progress"],
                    "terminal_states": ["Done"],
                },
                "workspace": {"root": str(tmp_path / "workspaces")},
                "agent": {"max_concurrent_agents": 2, "max_retry_backoff_ms": 120_000},
                "codex": {
                    "command": "codex app-server",
                    "turn_timeout_ms": 1_000,
                    "read_timeout_ms": 1_000,
                    "stall_timeout_ms": stall_timeout_ms,
                },
                "hooks": {"before_remove": before_remove},
            },
            prompt_template="Prompt body",
        )
    )


def test_orchestrator_dispatches_and_schedules_continuation_retry(tmp_path: Path) -> None:
    issue = build_issue()
    tracker_client = FakeTrackerClient(candidate_batches=[[issue]])
    config = build_config(tmp_path=tmp_path)

    async def successful_worker_runner(**kwargs: object) -> AttemptResult:
        on_event = kwargs["on_event"]
        assert callable(on_event)
        await on_event(
            AgentRuntimeEvent(
                event="session_started",
                timestamp=datetime.now(UTC),
                session_id="thr_123-turn_1",
                thread_id="thr_123",
                turn_id="turn_1",
                codex_app_server_pid=123,
                usage=None,
                payload={"phase": "turn_started"},
            )
        )
        return AttemptResult(
            status="succeeded",
            issue=issue,
            attempt=None,
            workspace_path=tmp_path / "workspaces" / issue.identifier,
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            turns_run=1,
            error_code=None,
            message=None,
        )

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=successful_worker_runner,
        )
        try:
            await orchestrator.run_once()
            await asyncio.sleep(0)

            assert issue.id not in orchestrator.state.running
            assert issue.id in orchestrator.state.retry_attempts
            assert orchestrator.state.retry_attempts[issue.id].attempt == 1
            assert issue.id in orchestrator.state.claimed
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_cleans_workspace_when_success_returns_terminal_issue(tmp_path: Path) -> None:
    issue = build_issue()
    terminal_issue = build_issue(state="Done")
    marker_path = tmp_path / "before_remove.marker"
    config = build_config(tmp_path=tmp_path, before_remove=f"touch {marker_path}")
    workspace_manager = WorkspaceManager(config.workspace.root)
    workspace_manager.ensure_workspace(issue.identifier)
    tracker_client = FakeTrackerClient(candidate_batches=[[issue]])

    async def successful_worker_runner(**kwargs: object) -> AttemptResult:
        return AttemptResult(
            status="succeeded",
            issue=terminal_issue,
            attempt=None,
            workspace_path=tmp_path / "workspaces" / issue.identifier,
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            turns_run=1,
            error_code=None,
            message=None,
        )

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=successful_worker_runner,
            workspace_manager=workspace_manager,
        )
        try:
            await orchestrator.run_once()
            await orchestrator.wait_for_running_workers()

            assert issue.id not in orchestrator.state.running
            assert issue.id not in orchestrator.state.retry_attempts
            assert issue.id not in orchestrator.state.claimed
            assert issue.id in orchestrator.state.completed
            assert not workspace_manager.resolve_workspace_path(issue.identifier).exists()
            assert marker_path.is_file()
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_reconcile_cleans_terminal_workspaces(tmp_path: Path) -> None:
    issue = build_issue()
    terminal_issue = build_issue(state="Done")
    marker_path = tmp_path / "before_remove.marker"
    after_run_marker = tmp_path / "after_run.marker"
    config = build_service_config(
        WorkflowDefinition(
            config={
                "tracker": {
                    "kind": "linear",
                    "api_key": "linear-token",
                    "project_slug": "symphony",
                    "active_states": ["Todo", "In Progress"],
                    "terminal_states": ["Done"],
                },
                "workspace": {"root": str(tmp_path / "workspaces")},
                "agent": {"max_concurrent_agents": 2, "max_retry_backoff_ms": 120_000},
                "codex": {
                    "command": "codex app-server",
                    "turn_timeout_ms": 1_000,
                    "read_timeout_ms": 1_000,
                    "stall_timeout_ms": 1_000,
                },
                "hooks": {
                    "before_remove": f"touch {marker_path}",
                    "after_run": f"touch {after_run_marker}",
                },
            },
            prompt_template="Prompt body",
        )
    )
    workspace_manager = WorkspaceManager(config.workspace.root)
    workspace_manager.ensure_workspace(issue.identifier)
    tracker_client = FakeTrackerClient(
        candidate_batches=[[issue]],
        refresh_batches=[[terminal_issue]],
    )
    started = asyncio.Event()

    async def hanging_worker_runner(**kwargs: object) -> AttemptResult:
        on_event = kwargs["on_event"]
        workspace_manager = kwargs["workspace_manager"]
        assert callable(on_event)
        assert isinstance(workspace_manager, WorkspaceManager)
        await on_event(
            AgentRuntimeEvent(
                event="session_started",
                timestamp=datetime.now(UTC),
                session_id="thr_123-turn_1",
                thread_id="thr_123",
                turn_id="turn_1",
                codex_app_server_pid=321,
                usage=None,
                payload={"phase": "turn_started"},
            )
        )
        started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            assert workspace_manager.resolve_workspace_path(issue.identifier).exists()
            after_run_marker.touch()
            raise
        raise AssertionError("unreachable")

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=hanging_worker_runner,
            workspace_manager=workspace_manager,
        )
        try:
            await orchestrator.run_once()
            await started.wait()
            assert issue.id in orchestrator.state.running

            await orchestrator.reconcile_running_issues()
            await asyncio.sleep(0)

            assert issue.id not in orchestrator.state.running
            assert not workspace_manager.resolve_workspace_path(issue.identifier).exists()
            assert after_run_marker.is_file()
            assert marker_path.is_file()
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_reschedules_retry_when_retry_candidate_fetch_fails(tmp_path: Path) -> None:
    issue = build_issue()
    config = build_config(tmp_path=tmp_path)

    class FailingRetryTracker(FakeTrackerClient):
        def fetch_candidate_issues(self) -> list[Issue]:
            raise RuntimeError("tracker unavailable")

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=FailingRetryTracker(),
        )
        try:
            await orchestrator._schedule_retry(
                issue_id=issue.id,
                identifier=issue.identifier,
                attempt=1,
                delay_ms=0,
                error="initial retry",
            )
            await asyncio.wait_for(
                _wait_for_retry_attempt(orchestrator, issue.id, 2),
                timeout=1.0,
            )

            retry_entry = orchestrator.state.retry_attempts[issue.id]
            assert retry_entry.attempt == 2
            assert retry_entry.error == "retry poll failed"
            assert issue.id in orchestrator.state.claimed
            assert retry_entry.timer_handle is not None
            assert retry_entry.timer_handle.done() is False
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


async def _wait_for_retry_attempt(
    orchestrator: Orchestrator,
    issue_id: str,
    attempt: int,
) -> None:
    while True:
        retry_entry = orchestrator.state.retry_attempts.get(issue_id)
        if retry_entry is not None and retry_entry.attempt == attempt:
            return
        await asyncio.sleep(0.01)


def test_orchestrator_keeps_clean_continuation_retries_at_attempt_one(tmp_path: Path) -> None:
    issue = build_issue()
    tracker_client = FakeTrackerClient(candidate_batches=[[issue], [issue]])
    config = build_config(tmp_path=tmp_path)
    attempts_seen: list[int | None] = []

    async def successful_worker_runner(**kwargs: object) -> AttemptResult:
        attempt = kwargs["attempt"]
        assert attempt is None or isinstance(attempt, int)
        attempts_seen.append(attempt)
        return AttemptResult(
            status="succeeded",
            issue=issue,
            attempt=attempt,
            workspace_path=tmp_path / "workspaces" / issue.identifier,
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            turns_run=1,
            error_code=None,
            message=None,
        )

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=successful_worker_runner,
        )
        try:
            await orchestrator.run_once()
            await orchestrator.wait_for_running_workers()

            assert orchestrator.state.retry_attempts[issue.id].attempt == 1

            await orchestrator._dispatch_retry_issue(issue.id)
            await orchestrator.wait_for_running_workers()

            assert attempts_seen == [None, 1]
            assert orchestrator.state.retry_attempts[issue.id].attempt == 1
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_stall_reconciliation_cancels_and_retries(tmp_path: Path) -> None:
    issue = build_issue()
    tracker_client = FakeTrackerClient(candidate_batches=[[issue]])
    config = build_config(tmp_path=tmp_path, stall_timeout_ms=50)
    started = asyncio.Event()

    async def stalled_worker_runner(**kwargs: object) -> AttemptResult:
        on_event = kwargs["on_event"]
        assert callable(on_event)
        await on_event(
            AgentRuntimeEvent(
                event="notification",
                timestamp=datetime.now(UTC),
                session_id="thr_123-turn_1",
                thread_id="thr_123",
                turn_id="turn_1",
                codex_app_server_pid=456,
                usage=None,
                payload={"phase": "turn_started"},
            )
        )
        started.set()
        await asyncio.Future()
        raise AssertionError("unreachable")

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=stalled_worker_runner,
        )
        try:
            await orchestrator.run_once()
            await started.wait()
            await asyncio.sleep(0.06)
            await orchestrator.reconcile_running_issues()
            await asyncio.sleep(0)

            assert issue.id not in orchestrator.state.running
            assert issue.id in orchestrator.state.retry_attempts
            assert orchestrator.state.retry_attempts[issue.id].error == "stalled"
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_respects_todo_blockers(tmp_path: Path) -> None:
    blocked_issue = build_issue(
        issue_id="issue-2",
        identifier="SYM-999",
        state="Todo",
        blocked_by=(IssueBlocker(id="b1", identifier="SYM-1", state="In Progress"),),
    )
    tracker_client = FakeTrackerClient(candidate_batches=[[blocked_issue]])
    config = build_config(tmp_path=tmp_path)
    dispatched = False

    async def worker_runner(**kwargs: object) -> AttemptResult:
        nonlocal dispatched
        dispatched = True
        raise AssertionError("worker should not be dispatched")

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=worker_runner,
        )
        try:
            await orchestrator.run_once()
            await asyncio.sleep(0)
            assert dispatched is False
            assert not orchestrator.state.running
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_startup_cleanup_ignores_workspace_remove_failures(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    terminal_issue = build_issue(state="Done")
    tracker_client = FakeTrackerClient(terminal_issues=[terminal_issue])
    config = build_config(tmp_path=tmp_path)
    workspace_manager = WorkspaceManager(config.workspace.root)

    def fail_remove(self: WorkspaceManager, issue_identifier: str) -> bool:
        raise WorkspaceRemoveError(f"cannot remove {issue_identifier}")

    monkeypatch.setattr(WorkspaceManager, "remove_workspace", fail_remove)

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            workspace_manager=workspace_manager,
        )
        try:
            await orchestrator.startup()
            assert orchestrator.state.running == {}
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())
    assert "Workspace cleanup failed for SYM-123" in caplog.text


def test_orchestrator_warns_once_about_unknown_usage_semantics(tmp_path: Path) -> None:
    config = build_config(tmp_path=tmp_path)

    async def done_result() -> AttemptResult:
        return AttemptResult(
            status="succeeded",
            issue=build_issue(),
            attempt=None,
            workspace_path=tmp_path / "workspaces" / "SYM-123",
            session_id=None,
            thread_id=None,
            turn_id=None,
            turns_run=0,
            error_code=None,
            message=None,
        )

    async def run_test() -> None:
        orchestrator = Orchestrator(config=config, tracker_client=FakeTrackerClient())
        worker_task: asyncio.Task[AttemptResult] = asyncio.create_task(done_result())
        monitor_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
        orchestrator.state.running["issue-1"] = RunningEntry(
            issue=build_issue(),
            attempt=None,
            worker_task=worker_task,
            monitor_task=monitor_task,
            started_at=datetime.now(UTC),
        )

        event = AgentRuntimeEvent(
            event="turn_completed",
            timestamp=datetime.now(UTC),
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            codex_app_server_pid=123,
            usage=UsageSnapshot(input_tokens=10, output_tokens=5, total_tokens=15),
            payload={},
        )

        with pytest.warns(RuntimeWarning, match="cumulative snapshots"):
            await orchestrator._handle_worker_event("issue-1", event)
        with warnings.catch_warnings(record=True) as warnings_record:
            warnings.simplefilter("always")
            await orchestrator._handle_worker_event("issue-1", event)
        assert len(warnings_record) == 0

        await asyncio.gather(worker_task, monitor_task)
        await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_runtime_snapshot_includes_running_retry_totals_and_rate_limits(
    tmp_path: Path,
) -> None:
    issue = build_issue()
    retry_issue = build_issue(issue_id="issue-2", identifier="SYM-124")
    config = build_config(tmp_path=tmp_path)

    async def run_test() -> None:
        orchestrator = Orchestrator(config=config, tracker_client=FakeTrackerClient())

        async def pending_attempt() -> AttemptResult:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

        worker_task = asyncio.create_task(pending_attempt())
        monitor_task = asyncio.create_task(asyncio.sleep(0))
        started_at = datetime.now(UTC) - timedelta(seconds=5)

        orchestrator.state.running[issue.id] = RunningEntry(
            issue=issue,
            attempt=None,
            worker_task=worker_task,
            monitor_task=monitor_task,
            started_at=started_at,
        )
        orchestrator.state.codex_totals = CodexTotals(
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            seconds_running=12.5,
        )

        event = AgentRuntimeEvent(
            event="notification",
            timestamp=datetime.now(UTC),
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            codex_app_server_pid=123,
            usage=UsageSnapshot(input_tokens=10, output_tokens=5, total_tokens=15),
            payload={
                "phase": "turn_started",
                "rate_limits": {"requests_remaining": 7, "tokens_remaining": 900},
            },
        )
        second_event_same_turn = AgentRuntimeEvent(
            event="notification",
            timestamp=datetime.now(UTC),
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            codex_app_server_pid=123,
            usage=None,
            payload={"phase": "still_turn_1"},
        )
        third_event_next_turn = AgentRuntimeEvent(
            event="notification",
            timestamp=datetime.now(UTC),
            session_id="thr_123-turn_2",
            thread_id="thr_123",
            turn_id="turn_2",
            codex_app_server_pid=123,
            usage=None,
            payload={"phase": "turn_2_started"},
        )

        try:
            with pytest.warns(RuntimeWarning, match="cumulative snapshots"):
                await orchestrator._handle_worker_event(issue.id, event)
            await orchestrator._handle_worker_event(issue.id, second_event_same_turn)
            await orchestrator._handle_worker_event(issue.id, third_event_next_turn)
            await orchestrator._schedule_retry(
                issue_id=retry_issue.id,
                identifier=retry_issue.identifier,
                attempt=3,
                delay_ms=30_000,
                error="no available orchestrator slots",
            )

            snapshot = orchestrator.get_runtime_snapshot()

            assert snapshot["counts"] == {"running": 1, "retrying": 1}
            assert snapshot["rate_limits"] == {
                "requests_remaining": 7,
                "tokens_remaining": 900,
            }

            running_row = snapshot["running"][0]
            assert running_row["issue_id"] == issue.id
            assert running_row["issue_identifier"] == issue.identifier
            assert running_row["attempt"] is None
            assert running_row["state"] == issue.state
            assert running_row["session_id"] == "thr_123-turn_2"
            assert running_row["turn_count"] == 2
            assert running_row["last_event"] == "notification"
            assert running_row["workspace_path"].endswith(f"/{issue.identifier}")
            assert running_row["tokens"] == {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            }
            assert isinstance(running_row["started_at"], str)
            assert isinstance(running_row["last_event_at"], str)

            retry_row = snapshot["retrying"][0]
            assert retry_row["issue_id"] == retry_issue.id
            assert retry_row["issue_identifier"] == retry_issue.identifier
            assert retry_row["attempt"] == 3
            assert retry_row["error"] == "no available orchestrator slots"
            assert retry_row["workspace_path"].endswith(f"/{retry_issue.identifier}")
            assert isinstance(retry_row["due_at"], str)

            codex_totals = snapshot["codex_totals"]
            assert codex_totals["input_tokens"] == 110
            assert codex_totals["output_tokens"] == 55
            assert codex_totals["total_tokens"] == 165
            assert 17.5 <= codex_totals["seconds_running"] <= 18.5
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_runtime_snapshot_tolerates_degenerate_workspace_identifiers(
    tmp_path: Path,
) -> None:
    running_issue = build_issue(issue_id="issue-1", identifier="..")
    retry_issue = build_issue(issue_id="issue-2", identifier="   ")
    config = build_config(tmp_path=tmp_path)

    async def run_test() -> None:
        orchestrator = Orchestrator(config=config, tracker_client=FakeTrackerClient())

        async def pending_attempt() -> AttemptResult:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

        worker_task = asyncio.create_task(pending_attempt())
        monitor_task = asyncio.create_task(asyncio.sleep(0))

        orchestrator.state.running[running_issue.id] = RunningEntry(
            issue=running_issue,
            attempt=None,
            worker_task=worker_task,
            monitor_task=monitor_task,
            started_at=datetime.now(UTC),
        )

        try:
            await orchestrator._schedule_retry(
                issue_id=retry_issue.id,
                identifier=retry_issue.identifier,
                attempt=1,
                delay_ms=30_000,
                error="retry me",
            )

            snapshot = orchestrator.get_runtime_snapshot()

            assert snapshot["running"][0]["issue_identifier"] == running_issue.identifier
            assert snapshot["running"][0]["workspace_path"] == str(
                config.workspace.root / running_issue.identifier
            )
            assert snapshot["retrying"][0]["issue_identifier"] == retry_issue.identifier
            assert snapshot["retrying"][0]["workspace_path"] == str(
                config.workspace.root / retry_issue.identifier
            )
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_prefers_canonical_nested_rate_limit_payloads(tmp_path: Path) -> None:
    issue = build_issue()
    config = build_config(tmp_path=tmp_path)

    async def run_test() -> None:
        orchestrator = Orchestrator(config=config, tracker_client=FakeTrackerClient())

        async def pending_attempt() -> AttemptResult:
            await asyncio.sleep(3600)
            raise AssertionError("unreachable")

        worker_task = asyncio.create_task(pending_attempt())
        monitor_task = asyncio.create_task(asyncio.sleep(0))
        orchestrator.state.running[issue.id] = RunningEntry(
            issue=issue,
            attempt=None,
            worker_task=worker_task,
            monitor_task=monitor_task,
            started_at=datetime.now(UTC),
        )

        event = AgentRuntimeEvent(
            event="notification",
            timestamp=datetime.now(UTC),
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            codex_app_server_pid=123,
            usage=None,
            payload={
                "rateLimit": {"requests_remaining": 1},
                "params": {"rate_limits": {"requests_remaining": 7}},
            },
        )

        try:
            await orchestrator._handle_worker_event(issue.id, event)
            snapshot = orchestrator.get_runtime_snapshot()
            assert snapshot["rate_limits"] == {"requests_remaining": 7}
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_publishes_runtime_snapshot_for_other_processes(tmp_path: Path) -> None:
    config = build_config(tmp_path=tmp_path)
    snapshot_path = get_runtime_snapshot_path()

    async def run_test() -> None:
        orchestrator = Orchestrator(config=config, tracker_client=FakeTrackerClient())
        try:
            await orchestrator.startup()

            assert snapshot_path.is_file()
            published_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            assert published_snapshot["counts"] == {"running": 0, "retrying": 0}
        finally:
            await orchestrator.aclose()

        assert not snapshot_path.exists()

    asyncio.run(run_test())


def test_orchestrator_refreshes_runtime_snapshot_immediately_after_dispatch(tmp_path: Path) -> None:
    issue = build_issue()
    config = build_config(tmp_path=tmp_path)
    tracker_client = FakeTrackerClient(candidate_batches=[[issue]])
    snapshot_path = get_runtime_snapshot_path()

    async def pending_worker_runner(**kwargs: object) -> AttemptResult:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=pending_worker_runner,
        )
        try:
            await orchestrator.run_once()

            snapshot = orchestrator.get_runtime_snapshot()
            assert snapshot["counts"] == {"running": 1, "retrying": 0}
            assert snapshot["running"][0]["issue_id"] == issue.id

            published_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            assert published_snapshot["counts"] == {"running": 1, "retrying": 0}
            assert published_snapshot["running"][0]["issue_id"] == issue.id
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_tolerates_runtime_snapshot_publish_failures(tmp_path: Path) -> None:
    config = build_config(tmp_path=tmp_path)

    async def done_result() -> AttemptResult:
        return AttemptResult(
            status="succeeded",
            issue=build_issue(),
            attempt=None,
            workspace_path=tmp_path / "workspaces" / "SYM-123",
            session_id="thr_123-turn_1",
            thread_id="thr_123",
            turn_id="turn_1",
            turns_run=1,
            error_code=None,
            message=None,
        )

    async def run_test() -> None:
        orchestrator = Orchestrator(config=config, tracker_client=FakeTrackerClient())

        with pytest.MonkeyPatch.context() as monkeypatch:

            def fail_publish(_snapshot: object, *, owner_token: str | None = None) -> Path:
                del owner_token
                raise RuntimeSnapshotUnavailableError("snapshot disk unavailable")

            monkeypatch.setattr("symphony.orchestrator.core.publish_runtime_snapshot", fail_publish)

            await orchestrator.startup()

            worker_task: asyncio.Task[AttemptResult] = asyncio.create_task(done_result())
            monitor_task: asyncio.Task[None] = asyncio.create_task(asyncio.sleep(0))
            orchestrator.state.running["issue-1"] = RunningEntry(
                issue=build_issue(),
                attempt=None,
                worker_task=worker_task,
                monitor_task=monitor_task,
                started_at=datetime.now(UTC),
            )

            event = AgentRuntimeEvent(
                event="turn_completed",
                timestamp=datetime.now(UTC),
                session_id="thr_123-turn_1",
                thread_id="thr_123",
                turn_id="turn_1",
                codex_app_server_pid=123,
                usage=UsageSnapshot(input_tokens=10, output_tokens=5, total_tokens=15),
                payload={},
            )

            with pytest.warns(RuntimeWarning, match="cumulative snapshots"):
                await orchestrator._handle_worker_event("issue-1", event)

            snapshot = orchestrator.get_runtime_snapshot()
            assert snapshot["counts"]["running"] == 1

            await asyncio.gather(worker_task, monitor_task)
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_tolerates_invalid_runtime_snapshot_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid_parent = tmp_path / "snapshot-parent"
    invalid_parent.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv(
        "SYMPHONY_RUNTIME_SNAPSHOT_PATH",
        str(invalid_parent / "runtime-snapshot.json"),
    )

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=build_config(tmp_path=tmp_path), tracker_client=FakeTrackerClient()
        )
        try:
            await orchestrator.startup()
            await orchestrator.run_once()

            snapshot = orchestrator.get_runtime_snapshot()
            assert snapshot["counts"] == {"running": 0, "retrying": 0}
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())


def test_orchestrator_shutdown_keeps_newer_snapshot_from_other_process(tmp_path: Path) -> None:
    config = build_config(tmp_path=tmp_path)
    snapshot_path = get_runtime_snapshot_path()

    async def pending_result() -> AttemptResult:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def run_test() -> None:
        orchestrator_a = Orchestrator(config=config, tracker_client=FakeTrackerClient())
        orchestrator_b = Orchestrator(config=config, tracker_client=FakeTrackerClient())
        worker_task: asyncio.Task[AttemptResult] | None = None
        monitor_task: asyncio.Task[None] | None = None
        try:
            await orchestrator_a.startup()

            worker_task = asyncio.create_task(pending_result())
            monitor_task = asyncio.create_task(asyncio.sleep(0))
            orchestrator_b.state.running["issue-2"] = RunningEntry(
                issue=build_issue(issue_id="issue-2", identifier="SYM-456"),
                attempt=None,
                worker_task=worker_task,
                monitor_task=monitor_task,
                started_at=datetime.now(UTC),
            )
            await orchestrator_b.startup()
            orchestrator_b._refresh_runtime_snapshot()

            await orchestrator_a.aclose()

            assert snapshot_path.is_file()
            published_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            assert published_snapshot["counts"] == {"running": 1, "retrying": 0}
            assert published_snapshot["running"][0]["issue_id"] == "issue-2"
        finally:
            if orchestrator_a._started:
                await orchestrator_a.aclose()
            if orchestrator_b._started:
                await orchestrator_b.aclose()
            if worker_task is not None:
                await asyncio.gather(worker_task, return_exceptions=True)
            if monitor_task is not None:
                await asyncio.gather(monitor_task, return_exceptions=True)

    asyncio.run(run_test())


def test_orchestrator_heartbeat_refreshes_snapshot_while_worker_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = build_issue()
    config = build_config(tmp_path=tmp_path)
    tracker_client = FakeTrackerClient(candidate_batches=[[issue]])
    snapshot_path = get_runtime_snapshot_path()
    monkeypatch.setenv("SYMPHONY_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS", "1")

    async def pending_worker_runner(**kwargs: object) -> AttemptResult:
        await asyncio.sleep(3600)
        raise AssertionError("unreachable")

    async def run_test() -> None:
        orchestrator = Orchestrator(
            config=config,
            tracker_client=tracker_client,
            worker_runner=pending_worker_runner,
        )
        try:
            await orchestrator.run_once()

            first_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            first_generated_at = parse_snapshot_timestamp(first_snapshot["generated_at"])
            assert first_generated_at is not None

            await asyncio.sleep(1.2)

            second_snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
            second_generated_at = parse_snapshot_timestamp(second_snapshot["generated_at"])
            assert second_generated_at is not None
            assert second_generated_at > first_generated_at
            assert second_snapshot["counts"] == {"running": 1, "retrying": 0}
            assert second_snapshot["running"][0]["issue_id"] == issue.id
        finally:
            await orchestrator.aclose()

    asyncio.run(run_test())
