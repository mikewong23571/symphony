from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from symphony.common.types import ServiceInfo
from symphony.observability.logging import log_event
from symphony.tracker.models import Issue
from symphony.workflow.config import ServiceConfig
from symphony.workspace import Workspace, WorkspaceError, WorkspaceManager, WorkspaceRemoveError
from symphony.workspace.hooks import HookError, build_hook_start_error, run_hook

from .client import (
    AppServerDiagnosticContext,
    AppServerError,
    AppServerSession,
    start_app_server_session,
    start_next_turn,
)
from .events import AgentRuntimeEvent, utcnow
from .prompting import (
    PromptTemplateError,
    build_continuation_guidance,
    render_issue_prompt,
)
from .runner import stream_turn

logger = logging.getLogger(__name__)


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
    stderr_callback = (
        (
            lambda line, context: _emit_stderr_diagnostic(
                line=line,
                context=context,
                on_event=on_event,
            )
        )
        if on_event is not None
        else None
    )

    try:
        prompt_text = render_issue_prompt(config.prompt_template, current_issue, attempt=attempt)
        workspace = manager.ensure_workspace(issue.identifier)
        workspace_path = workspace.path
        manager.remove_temporary_artifacts(workspace.path)
        after_create_succeeded = not workspace.created_now

        if workspace.created_now:
            await _run_required_hook(
                name="after_create",
                script=config.hooks.after_create,
                issue=current_issue,
                workspace=workspace,
                timeout_ms=config.hooks.timeout_ms,
            )
            after_create_succeeded = True

        await _run_required_hook(
            name="before_run",
            script=config.hooks.before_run,
            issue=current_issue,
            workspace=workspace,
            timeout_ms=config.hooks.timeout_ms,
        )
        after_run_needed = True

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
            stderr_callback=stderr_callback,
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
        _log_workspace_prepare_failure(
            issue=current_issue,
            workspace_path=workspace_path,
            exc=exc,
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
    except PromptTemplateError as exc:
        _log_prompt_template_failure(
            issue=current_issue,
            workspace_path=workspace_path,
            session_id=session.session_id if session is not None else None,
            exc=exc,
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
            await _run_best_effort_hook(
                name="after_run",
                script=active_config.hooks.after_run,
                issue=current_issue,
                workspace_path=workspace.path,
                timeout_ms=active_config.hooks.timeout_ms,
                session_id=session.session_id if session is not None else None,
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
    issue: Issue,
    workspace: Workspace,
    timeout_ms: int,
) -> None:
    if script is None:
        return
    _log_hook_event(
        level=logging.INFO,
        event="hook_started",
        name=name,
        issue=issue,
        workspace_path=workspace.path,
        session_id=None,
    )
    try:
        await run_hook(name=name, script=script, cwd=workspace.path, timeout_ms=timeout_ms)
    except OSError as exc:
        hook_error = build_hook_start_error(name=name, exc=exc)
        _log_hook_error(
            name=name,
            issue=issue,
            workspace_path=workspace.path,
            session_id=None,
            exc=hook_error,
        )
        raise hook_error from exc
    except HookError as exc:
        _log_hook_error(
            name=name,
            issue=issue,
            workspace_path=workspace.path,
            session_id=None,
            exc=exc,
        )
        raise


async def _run_best_effort_hook(
    *,
    name: str,
    script: str | None,
    issue: Issue,
    workspace_path: Path,
    timeout_ms: int,
    session_id: str | None,
) -> None:
    if script is None:
        return
    _log_hook_event(
        level=logging.INFO,
        event="hook_started",
        name=name,
        issue=issue,
        workspace_path=workspace_path,
        session_id=session_id,
    )
    try:
        await run_hook(name=name, script=script, cwd=workspace_path, timeout_ms=timeout_ms)
    except OSError as exc:
        _log_hook_error(
            name=name,
            issue=issue,
            workspace_path=workspace_path,
            session_id=session_id,
            exc=build_hook_start_error(name=name, exc=exc),
        )
    except HookError as exc:
        _log_hook_error(
            name=name,
            issue=issue,
            workspace_path=workspace_path,
            session_id=session_id,
            exc=exc,
        )


async def _emit_stderr_diagnostic(
    *,
    line: str,
    context: AppServerDiagnosticContext,
    on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None,
) -> None:
    if on_event is None:
        return
    await on_event(
        AgentRuntimeEvent(
            event="stderr_diagnostic",
            timestamp=utcnow(),
            session_id=context.session_id or "",
            thread_id=context.thread_id or "",
            turn_id=context.turn_id or "",
            codex_app_server_pid=context.codex_app_server_pid,
            usage=None,
            payload={"line": line},
        )
    )


def _resolve_approval_policy(config: ServiceConfig) -> str:
    return config.codex.approval_policy or "never"


def _resolve_thread_sandbox(config: ServiceConfig) -> str:
    return config.codex.thread_sandbox or "workspace-write"


_LEGACY_SANDBOX_POLICY_TYPES = {
    "danger-full-access": "dangerFullAccess",
    "external-sandbox": "externalSandbox",
    "read-only": "readOnly",
    "workspace-write": "workspaceWrite",
}


def _resolve_turn_sandbox_policy(config: ServiceConfig) -> dict[str, object]:
    policy = config.codex.turn_sandbox_policy or {"type": _resolve_thread_sandbox(config)}
    return _normalize_turn_sandbox_policy(policy)


def _normalize_turn_sandbox_policy(policy: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(policy)
    sandbox_type = normalized.get("type")
    if isinstance(sandbox_type, str):
        stripped = sandbox_type.strip()
        normalized["type"] = _LEGACY_SANDBOX_POLICY_TYPES.get(stripped, stripped)
    return normalized


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


def _log_hook_event(
    *,
    level: int,
    event: str,
    name: str,
    issue: Issue,
    workspace_path: Path,
    session_id: str | None,
) -> None:
    log_event(
        logger,
        level,
        event,
        fields={
            "hook": name,
            "issue_id": issue.id,
            "issue_identifier": issue.identifier,
            "session_id": session_id,
            "workspace_path": workspace_path,
        },
    )


def _log_hook_error(
    *,
    name: str,
    issue: Issue,
    workspace_path: Path,
    session_id: str | None,
    exc: HookError,
) -> None:
    event_name = "hook_timed_out" if exc.code == "hook_timeout" else "hook_failed"
    log_event(
        logger,
        logging.WARNING,
        event_name,
        fields={
            "hook": name,
            "issue_id": issue.id,
            "issue_identifier": issue.identifier,
            "session_id": session_id,
            "workspace_path": workspace_path,
            "error_code": exc.code,
            "message": exc.message,
        },
    )


def _log_workspace_prepare_failure(
    *,
    issue: Issue,
    workspace_path: Path,
    exc: WorkspaceError,
) -> None:
    event_name = (
        "workspace_prepare_failed"
        if isinstance(exc, WorkspaceRemoveError)
        else "workspace_resolution_failed"
    )
    log_event(
        logger,
        logging.WARNING,
        event_name,
        fields={
            "issue_id": issue.id,
            "issue_identifier": issue.identifier,
            "workspace_path": workspace_path,
            "error_code": exc.code,
            "message": exc.message,
        },
    )


def _log_prompt_template_failure(
    *,
    issue: Issue,
    workspace_path: Path,
    session_id: str | None,
    exc: PromptTemplateError,
) -> None:
    log_event(
        logger,
        logging.WARNING,
        "prompt_template_failed",
        fields={
            "issue_id": issue.id,
            "issue_identifier": issue.identifier,
            "session_id": session_id,
            "workspace_path": workspace_path,
            "error_code": exc.code,
            "message": exc.message,
        },
    )
