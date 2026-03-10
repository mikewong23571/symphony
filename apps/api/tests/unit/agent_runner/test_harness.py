from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from pathlib import Path

import pytest
from symphony.agent_runner import AgentRuntimeEvent, run_issue_attempt
from symphony.common.types import ServiceInfo
from symphony.tracker.models import Issue
from symphony.workflow.config import ServiceConfig, build_service_config
from symphony.workflow.loader import WorkflowDefinition
from symphony.workspace import WorkspaceManager, WorkspaceRemoveError

from .helpers import FAKE_APP_SERVER_PATH, collect_events


class FakeTrackerClient:
    def __init__(self, issues: list[Issue]) -> None:
        self.issues = list(issues)

    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]:
        if not issue_ids:
            return []
        if self.issues:
            issue = self.issues.pop(0)
            return [issue]
        return []


def build_issue(*, state: str = "In Progress") -> Issue:
    return Issue(
        id="issue-1",
        identifier="SYM-123",
        title="Implement streaming runner",
        description="Make the agent runner stream full turns.",
        priority=1,
        state=state,
        branch_name=None,
        url="https://linear.app/acme/issue/SYM-123",
        labels=("backend",),
        blocked_by=(),
        created_at=None,
        updated_at=None,
    )


def build_config(
    *,
    tmp_path: Path,
    mode: str,
    log_path: Path,
    turns: int | None = None,
    hook_overrides: dict[str, str] | None = None,
    stall_timeout_ms: int = 1_000,
    turn_timeout_ms: int = 1_000,
) -> ServiceConfig:
    turn_env = f" FAKE_SERVER_TURNS={turns}" if turns is not None else ""
    command = (
        f"FAKE_SERVER_MODE={mode} FAKE_SERVER_LOG={log_path}{turn_env} "
        f"{sys.executable} {FAKE_APP_SERVER_PATH}"
    )

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
                "agent": {"max_turns": 3},
                "codex": {
                    "command": command,
                    "approval_policy": "never",
                    "thread_sandbox": "workspace-write",
                    "turn_sandbox_policy": "workspace-write",
                    "read_timeout_ms": 1_000,
                    "turn_timeout_ms": turn_timeout_ms,
                    "stall_timeout_ms": stall_timeout_ms,
                },
                "hooks": hook_overrides or {},
            },
            prompt_template="Issue {{ issue.identifier }} attempt={{ attempt }}",
        )
    )


def test_run_issue_attempt_reuses_thread_for_continuation_turns(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"
    config = build_config(tmp_path=tmp_path, mode="multi_turn", log_path=log_path, turns=2)
    tracker_client = FakeTrackerClient([build_issue(), build_issue(state="Done")])

    async def run_test() -> None:
        events: list[AgentRuntimeEvent] = []
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=None,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=tracker_client,
            on_event=lambda event: collect_events(events, event),
        )

        assert result.status == "succeeded"
        assert result.thread_id == "thr_123"
        assert result.turn_id == "turn_2"
        assert result.turns_run == 2
        assert events[0].event == "session_started"
        assert any(event.payload.get("phase") == "turn_started" for event in events)

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert logged_messages[4]["method"] == "turn/start"
    assert logged_messages[4]["params"]["threadId"] == "thr_123"
    assert (
        "Continue working in the existing thread"
        in logged_messages[4]["params"]["input"][0]["text"]
    )


def test_run_issue_attempt_runs_workspace_hooks(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"
    marker_dir = tmp_path / "markers"
    marker_dir.mkdir()
    config = build_config(
        tmp_path=tmp_path,
        mode="stream_success",
        log_path=log_path,
        hook_overrides={
            "after_create": f"touch {marker_dir / 'after_create'}",
            "before_run": f"touch {marker_dir / 'before_run'}",
            "after_run": f"touch {marker_dir / 'after_run'}",
        },
    )
    tracker_client = FakeTrackerClient([build_issue(state="Done")])

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=1,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=tracker_client,
        )
        assert result.status == "succeeded"

    asyncio.run(run_test())

    assert (marker_dir / "after_create").is_file()
    assert (marker_dir / "before_run").is_file()
    assert (marker_dir / "after_run").is_file()


def test_run_issue_attempt_surfaces_before_run_hook_failures(tmp_path: Path) -> None:
    marker_path = tmp_path / "after_run"
    config = build_config(
        tmp_path=tmp_path,
        mode="stream_success",
        log_path=tmp_path / "messages.jsonl",
        hook_overrides={
            "before_run": "exit 7",
            "after_run": f"touch {marker_path}",
        },
    )

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=1,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=FakeTrackerClient([build_issue(state="Done")]),
        )
        assert result.status == "failed"
        assert result.error_code == "hook_execution"

    asyncio.run(run_test())

    assert not marker_path.exists()


def test_run_issue_attempt_maps_stalled_turns(tmp_path: Path) -> None:
    config = build_config(
        tmp_path=tmp_path,
        mode="silent_stream",
        log_path=tmp_path / "messages.jsonl",
        stall_timeout_ms=50,
        turn_timeout_ms=1_000,
    )

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=1,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=FakeTrackerClient([]),
        )
        assert result.status == "stalled"
        assert result.error_code == "stalled"

    asyncio.run(run_test())


def test_run_issue_attempt_cleans_new_workspace_after_after_create_failure(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    config = build_config(
        tmp_path=tmp_path,
        mode="stream_success",
        log_path=tmp_path / "messages.jsonl",
        hook_overrides={"after_create": "exit 7"},
    )

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=1,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=FakeTrackerClient([build_issue(state="Done")]),
        )
        assert result.status == "failed"
        assert result.error_code == "hook_execution"

    asyncio.run(run_test())

    assert not (workspace_root / "SYM-123").exists()


def test_run_issue_attempt_surfaces_workspace_setup_failures(tmp_path: Path) -> None:
    workspace_root = tmp_path / "blocked-root"
    workspace_root.write_text("not a directory", encoding="utf-8")
    config = build_config(
        tmp_path=tmp_path,
        mode="stream_success",
        log_path=tmp_path / "messages.jsonl",
    )
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
                "workspace": {"root": str(workspace_root)},
                "agent": {"max_turns": 3},
                "codex": {
                    "command": config.codex.command,
                    "approval_policy": "never",
                    "thread_sandbox": "workspace-write",
                    "turn_sandbox_policy": "workspace-write",
                    "read_timeout_ms": 1_000,
                    "turn_timeout_ms": 1_000,
                    "stall_timeout_ms": 1_000,
                },
            },
            prompt_template="Issue {{ issue.identifier }} attempt={{ attempt }}",
        )
    )

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=1,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=FakeTrackerClient([build_issue(state="Done")]),
        )
        assert result.status == "failed"
        assert result.error_code == "workspace_root_error"

    asyncio.run(run_test())


def test_run_issue_attempt_preserves_after_create_hook_failure_when_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_manager = WorkspaceManager(tmp_path / "workspaces")
    config = build_config(
        tmp_path=tmp_path,
        mode="stream_success",
        log_path=tmp_path / "messages.jsonl",
        hook_overrides={"after_create": "touch stuck && exit 7"},
    )

    def fail_remove(self: WorkspaceManager, issue_identifier: str) -> bool:
        raise WorkspaceRemoveError(f"cannot remove {issue_identifier}")

    monkeypatch.setattr(WorkspaceManager, "remove_workspace", fail_remove)

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=1,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=FakeTrackerClient([build_issue(state="Done")]),
            workspace_manager=workspace_manager,
        )
        assert result.status == "failed"
        assert result.error_code == "hook_execution"

    asyncio.run(run_test())


def test_run_issue_attempt_stops_when_issue_refresh_returns_empty(tmp_path: Path) -> None:
    log_path = tmp_path / "messages.jsonl"
    config = build_config(tmp_path=tmp_path, mode="multi_turn", log_path=log_path, turns=2)

    async def run_test() -> None:
        result = await run_issue_attempt(
            issue=build_issue(),
            attempt=None,
            config=config,
            service_info=ServiceInfo(name="symphony", version="0.1.0"),
            tracker_client=FakeTrackerClient([]),
        )

        assert result.status == "succeeded"
        assert result.turns_run == 1
        assert result.turn_id == "turn_1"

    asyncio.run(run_test())

    logged_messages = [
        json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [message["method"] for message in logged_messages] == [
        "initialize",
        "initialized",
        "thread/start",
        "turn/start",
    ]
