from __future__ import annotations

import asyncio
import warnings
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from symphony.agent_runner import AgentRuntimeEvent, AttemptResult
from symphony.agent_runner.events import UsageSnapshot
from symphony.orchestrator import Orchestrator
from symphony.orchestrator.core import RunningEntry
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
