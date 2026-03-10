from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from symphony.common.types import ServiceInfo
from symphony.tracker.models import Issue
from symphony.workflow.config import ServiceConfig
from symphony.workspace import Workspace, WorkspaceError, WorkspaceManager
from symphony.workspace.hooks import HookError, run_hook, run_hook_best_effort

from .client import AppServerError, AppServerSession, start_app_server_session, start_next_turn
from .events import AgentRuntimeEvent, utcnow
from .prompting import build_continuation_guidance, render_issue_prompt
from .runner import stream_turn


class IssueStateRefresher(Protocol):
    def fetch_issue_states_by_ids(self, issue_ids: Sequence[str]) -> list[Issue]: ...


@dataclass(slots=True, frozen=True)
class AttemptResult:
    status: str
    issue: Issue
    attempt: int | None
    workspace_path: Path
    session_id: str | None
    thread_id: str | None
    turn_id: str | None
    turns_run: int
    error_code: str | None
    message: str | None


class IssueRefreshStatus(StrEnum):
    REFRESHED = "refreshed"
    MISSING = "missing"
    ERROR = "error"


async def run_issue_attempt(
    *,
    issue: Issue,
    attempt: int | None,
    config: ServiceConfig,
    config_provider: Callable[[], ServiceConfig] | None = None,
    service_info: ServiceInfo,
    tracker_client: IssueStateRefresher,
    on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None = None,
    workspace_manager: WorkspaceManager | None = None,
) -> AttemptResult:
    manager = workspace_manager or WorkspaceManager(config.workspace.root)
    workspace_path = _best_effort_workspace_path(manager, issue.identifier)
    workspace: Workspace | None = None
    session: AppServerSession | None = None
    after_run_needed = False
    after_create_succeeded = True
    current_issue = issue
    turns_run = 0
    approval_policy = _resolve_approval_policy(config)
    thread_sandbox = _resolve_thread_sandbox(config)
    turn_sandbox_policy = _resolve_turn_sandbox_policy(config)

    try:
        workspace = manager.ensure_workspace(issue.identifier)
        workspace_path = workspace.path
        after_create_succeeded = not workspace.created_now

        if workspace.created_now:
            await _run_required_hook(
                name="after_create",
                script=config.hooks.after_create,
                workspace=workspace,
                timeout_ms=config.hooks.timeout_ms,
            )
            after_create_succeeded = True

        await _run_required_hook(
            name="before_run",
            script=config.hooks.before_run,
            workspace=workspace,
            timeout_ms=config.hooks.timeout_ms,
        )
        after_run_needed = True

        prompt_text = render_issue_prompt(config.prompt_template, current_issue, attempt=attempt)
        session = await start_app_server_session(
            command=config.codex.command,
            workspace_path=workspace.path,
            prompt_text=prompt_text,
            title=_build_turn_title(current_issue),
            service_info=service_info,
            approval_policy=approval_policy,
            thread_sandbox=thread_sandbox,
            turn_sandbox_policy=turn_sandbox_policy,
            read_timeout_ms=config.codex.read_timeout_ms,
        )
        await _emit_worker_event(
            session=session,
            on_event=on_event,
            event_name="session_started",
            payload={
                "workspace_path": str(workspace.path),
                "turn_number": 1,
            },
        )

        while True:
            turn_result = await stream_turn(
                session,
                approval_policy=approval_policy,
                turn_timeout_ms=config.codex.turn_timeout_ms,
                stall_timeout_ms=config.codex.stall_timeout_ms,
                on_event=on_event,
            )
            turns_run += 1

            if turn_result.outcome != "completed":
                return _build_attempt_result(
                    status=turn_result.outcome,
                    issue=current_issue,
                    attempt=attempt,
                    workspace_path=workspace_path,
                    session=session,
                    turns_run=turns_run,
                    error_code=turn_result.error_code,
                    message=turn_result.message,
                )

            refresh_status, refreshed_issue = await _refresh_issue_state(
                tracker_client,
                current_issue,
            )
            if refresh_status == IssueRefreshStatus.ERROR:
                return _build_attempt_result(
                    status="failed",
                    issue=current_issue,
                    attempt=attempt,
                    workspace_path=workspace_path,
                    session=session,
                    turns_run=turns_run,
                    error_code="issue_state_refresh_error",
                    message="Could not refresh issue state after a completed turn.",
                )
            if refresh_status == IssueRefreshStatus.MISSING:
                break
            if refreshed_issue is None:
                break
            current_issue = refreshed_issue

            if not _is_active_issue_state(current_issue, config):
                break

            if turns_run >= config.agent.max_turns:
                break

            next_prompt = build_continuation_guidance(current_issue, attempt=attempt)
            await start_next_turn(
                session,
                prompt_text=next_prompt,
                title=_build_turn_title(current_issue),
                approval_policy=approval_policy,
                sandbox_policy=turn_sandbox_policy,
                cwd=workspace.path,
                read_timeout_ms=config.codex.read_timeout_ms,
            )
            await _emit_worker_event(
                session=session,
                on_event=on_event,
                event_name="notification",
                payload={
                    "phase": "turn_started",
                    "turn_number": turns_run + 1,
                },
            )

        return _build_attempt_result(
            status="succeeded",
            issue=current_issue,
            attempt=attempt,
            workspace_path=workspace_path,
            session=session,
            turns_run=turns_run,
            error_code=None,
            message=None,
        )
    except asyncio.CancelledError:
        raise
    except WorkspaceError as exc:
        return _build_attempt_result(
            status="failed",
            issue=current_issue,
            attempt=attempt,
            workspace_path=workspace_path,
            session=session,
            turns_run=turns_run,
            error_code=exc.code,
            message=exc.message,
        )
    except HookError as exc:
        if workspace is not None and workspace.created_now and not after_create_succeeded:
            try:
                manager.remove_workspace(issue.identifier)
            except (OSError, WorkspaceError):
                pass
        return _build_attempt_result(
            status="failed",
            issue=current_issue,
            attempt=attempt,
            workspace_path=workspace_path,
            session=session,
            turns_run=turns_run,
            error_code=exc.code,
            message=exc.message,
        )
    except AppServerError as exc:
        if session is not None:
            await _emit_worker_event(
                session=session,
                on_event=on_event,
                event_name="startup_failed",
                payload={"message": exc.message},
            )
        return _build_attempt_result(
            status="failed",
            issue=current_issue,
            attempt=attempt,
            workspace_path=workspace_path,
            session=session,
            turns_run=turns_run,
            error_code=exc.code,
            message=exc.message,
        )
    finally:
        if session is not None:
            await session.aclose()
        if after_run_needed and workspace is not None:
            # `before_run` belongs to the dispatch-time config, but `after_run`
            # is a future hook execution and should observe the latest live
            # workflow settings if they changed mid-run.
            active_config = config_provider() if config_provider is not None else config
            await run_hook_best_effort(
                name="after_run",
                script=active_config.hooks.after_run,
                cwd=workspace.path,
                timeout_ms=active_config.hooks.timeout_ms,
            )


async def _refresh_issue_state(
    tracker_client: IssueStateRefresher,
    issue: Issue,
) -> tuple[IssueRefreshStatus, Issue | None]:
    try:
        refreshed_issues = await asyncio.to_thread(
            tracker_client.fetch_issue_states_by_ids,
            [issue.id],
        )
    except Exception:
        return (IssueRefreshStatus.ERROR, None)
    if not refreshed_issues:
        return (IssueRefreshStatus.MISSING, None)
    return (IssueRefreshStatus.REFRESHED, refreshed_issues[0])


async def _run_required_hook(
    *,
    name: str,
    script: str | None,
    workspace: Workspace,
    timeout_ms: int,
) -> None:
    if script is None:
        return
    await run_hook(name=name, script=script, cwd=workspace.path, timeout_ms=timeout_ms)


def _resolve_approval_policy(config: ServiceConfig) -> str:
    return config.codex.approval_policy or "never"


def _resolve_thread_sandbox(config: ServiceConfig) -> str:
    return config.codex.thread_sandbox or "workspace-write"


def _resolve_turn_sandbox_policy(config: ServiceConfig) -> dict[str, str]:
    sandbox_type = config.codex.turn_sandbox_policy or _resolve_thread_sandbox(config)
    return {"type": sandbox_type}


def _build_turn_title(issue: Issue) -> str:
    return f"{issue.identifier}: {issue.title}"


async def _emit_worker_event(
    *,
    session: AppServerSession,
    on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None,
    event_name: str,
    payload: dict[str, object],
) -> None:
    if on_event is None:
        return
    await on_event(
        AgentRuntimeEvent(
            event=event_name,
            timestamp=utcnow(),
            session_id=session.session_id,
            thread_id=session.thread_id,
            turn_id=session.turn_id,
            codex_app_server_pid=session.process.pid,
            usage=None,
            payload=payload,
        )
    )


def _build_attempt_result(
    *,
    status: str,
    issue: Issue,
    attempt: int | None,
    workspace_path: Path,
    session: AppServerSession | None,
    turns_run: int,
    error_code: str | None,
    message: str | None,
) -> AttemptResult:
    return AttemptResult(
        status=status,
        issue=issue,
        attempt=attempt,
        workspace_path=workspace_path,
        session_id=session.session_id if session is not None else None,
        thread_id=session.thread_id if session is not None else None,
        turn_id=session.turn_id if session is not None else None,
        turns_run=turns_run,
        error_code=error_code,
        message=message,
    )


def _best_effort_workspace_path(manager: WorkspaceManager, issue_identifier: str) -> Path:
    try:
        return manager.resolve_workspace_path(issue_identifier)
    except WorkspaceError:
        return manager.root / issue_identifier


def _is_active_issue_state(issue: Issue, config: ServiceConfig) -> bool:
    state = issue.state.strip().lower()
    active_states = {value.strip().lower() for value in config.tracker.active_states}
    terminal_states = {value.strip().lower() for value in config.tracker.terminal_states}
    return state in active_states and state not in terminal_states
