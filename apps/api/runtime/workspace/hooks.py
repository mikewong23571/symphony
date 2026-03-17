from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


class HookError(Exception):
    code = "hook_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class HookTimeoutError(HookError):
    code = "hook_timeout"


class HookExecutionError(HookError):
    code = "hook_execution"


@dataclass(slots=True, frozen=True)
class HookResult:
    name: str
    returncode: int
    stdout: str
    stderr: str


def build_hook_start_error(*, name: str, exc: OSError) -> HookError:
    detail = str(exc).strip() or exc.__class__.__name__
    return HookError(f"Hook '{name}' could not start: {detail}.")


async def run_hook(
    *,
    name: str,
    script: str,
    cwd: Path,
    timeout_ms: int,
) -> HookResult:
    process = await asyncio.create_subprocess_exec(
        "bash",
        "-lc",
        script,
        cwd=str(cwd.resolve()),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            process.communicate(),
            timeout=timeout_ms / 1000,
        )
    except TimeoutError as exc:
        if process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except TimeoutError:
                process.kill()
                await process.wait()
        raise HookTimeoutError(f"Hook '{name}' timed out.") from exc

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")
    result = HookResult(
        name=name,
        returncode=process.returncode or 0,
        stdout=stdout,
        stderr=stderr,
    )

    if result.returncode != 0:
        raise HookExecutionError(f"Hook '{name}' failed with exit code {result.returncode}.")

    return result


async def run_hook_best_effort(
    *,
    name: str,
    script: str | None,
    cwd: Path,
    timeout_ms: int,
) -> HookResult | None:
    if script is None:
        return None

    try:
        return await run_hook(name=name, script=script, cwd=cwd, timeout_ms=timeout_ms)
    except HookError:
        return None
