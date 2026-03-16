from __future__ import annotations

import sys
from pathlib import Path

from symphony.agent_runner import AgentRuntimeEvent, AppServerSession, start_app_server_session
from symphony.common.types import ServiceInfo

FAKE_APP_SERVER_PATH = Path(__file__).with_name("fake_app_server.py")


async def collect_events(
    events: list[AgentRuntimeEvent],
    event: AgentRuntimeEvent,
) -> None:
    events.append(event)


async def start_fake_app_server_session(
    tmp_path: Path,
    *,
    log_path: Path,
    mode: str,
    read_timeout_ms: int = 1_000,
    approval_policy: str = "never",
    dynamic_tools: list[dict[str, object]] | None = None,
) -> AppServerSession:
    log_path.write_text("", encoding="utf-8")
    command = (
        f"FAKE_SERVER_MODE={mode} FAKE_SERVER_LOG={log_path} "
        f"{sys.executable} {FAKE_APP_SERVER_PATH}"
    )

    return await start_app_server_session(
        command=command,
        workspace_path=tmp_path,
        prompt_text="Summarize this repo.",
        title="SYM-123: Handshake",
        service_info=ServiceInfo(name="symphony", version="0.1.0"),
        approval_policy=approval_policy,
        thread_sandbox="workspace-write",
        turn_sandbox_policy={"type": "workspace-write"},
        read_timeout_ms=read_timeout_ms,
        capabilities={},
        dynamic_tools=dynamic_tools,
        model="gpt-5.1-codex",
    )
