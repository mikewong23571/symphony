# Agent Runner Streaming, Worker Harness, and Orchestrator Core

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

Symphony already has the foundation required to load `WORKFLOW.md`, validate typed runtime config,
normalize Linear issues, create safe workspace directories, and render prompts. What it cannot do
yet is run a real coding turn to completion. The current app-server client stops after the startup
handshake, so there is no streamed turn processing, no turn timeout handling, no stall handling,
and no single-issue worker that can prove end-to-end behavior before the poll loop exists.

The next usable milestone is not “start the orchestrator.” The next usable milestone is: given one
issue and a fake or real Codex app-server, Symphony can start a turn, stream protocol messages
until the turn ends, normalize the important events, terminate stuck runs deterministically, and
reuse the same session/thread for continuation turns. Once that exists, the worker harness can wrap
it for one issue, and the orchestrator core can consume the exact same normalized event stream
without inventing a second protocol abstraction.

When this plan is complete, a contributor will be able to run focused unit tests for streamed turn
handling, run a single-issue harness against a fake app-server, and then start the Django
management command with confidence that the remaining orchestrator work is about scheduling and
state transitions rather than low-level Codex protocol uncertainty.

## Progress

- [x] 2026-03-10 00:53Z: Confirmed the repository baseline against `docs/SPEC.md` and the current
  code. `apps/api/symphony/workflow/loader.py`, `apps/api/symphony/workflow/config.py`,
  `apps/api/symphony/tracker/linear.py`, `apps/api/symphony/tracker/linear_client.py`,
  `apps/api/symphony/workspace/manager.py`, and `apps/api/symphony/agent_runner/prompting.py`
  already implement the workflow/config/tracker/workspace/prompting foundation.
- [x] 2026-03-10 00:53Z: Verified that the current app-server client in
  `apps/api/symphony/agent_runner/client.py` performs the startup handshake (`initialize`,
  `initialized`, `thread/start`, `turn/start`) and that the focused backend unit suite passes.
- [x] 2026-03-10 00:53Z: Ran the baseline command
  `uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/tracker apps/api/tests/unit/workspace apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_client.py`
  from the repository root and observed `75 passed in 1.64s`.
- [ ] Full streamed turn processing is still missing. `start_app_server_session(...)` returns after
- [x] 2026-03-10 01:53Z: Implemented full streamed turn handling in
  `apps/api/symphony/agent_runner/client.py`, `apps/api/symphony/agent_runner/events.py`, and
  `apps/api/symphony/agent_runner/runner.py`, including terminal turn parsing, malformed stdout
  handling, approval auto-approval, unsupported tool rejection, user-input-required failure,
  `turn_timeout`, and `stall_timeout`.
- [x] 2026-03-10 01:53Z: Implemented the single-issue worker harness in
  `apps/api/symphony/agent_runner/harness.py`, including workspace creation/reuse, required/best-
  effort hooks, prompt rendering, continuation turns on a shared `thread_id`, tracker state
  refresh, and typed attempt results.
- [x] 2026-03-10 01:53Z: Implemented orchestrator core in
  `apps/api/symphony/orchestrator/core.py`, including candidate selection, blocker enforcement,
  running/claimed/retry state, startup terminal cleanup, active-run reconciliation, stall-driven
  cancellation, continuation retry, and exponential backoff retry.
- [x] 2026-03-10 01:53Z: Integrated the management command with the real orchestrator and added a
  `--once` mode in `apps/api/symphony/management/commands/run_orchestrator.py` so tests and manual
  smoke runs can execute one startup-cleanup + dispatch cycle without blocking indefinitely.
- [x] 2026-03-10 01:53Z: Validated the backend surface with
  `uv run ruff check apps/api`, `uv run mypy apps/api`, and `uv run pytest`, ending at
  `103 passed in 6.52s`.

## Surprises & Discoveries

- Observation: The typed config layer is ahead of the runtime. The defaults for
  `codex.turn_timeout_ms`, `codex.read_timeout_ms`, and `codex.stall_timeout_ms` already exist in
  `apps/api/symphony/workflow/config.py`, even though only the startup handshake currently consumes
  `read_timeout_ms`.
  Evidence: `CodexConfig` includes all three fields, while `apps/api/symphony/agent_runner/client.py`
  currently accepts only `read_timeout_ms` in the live protocol path.

- Observation: The spec assigns stall detection to the coordination layer, not to the raw stdout
  parser. That means stall logic should not be buried in the lowest-level JSON line reader.
  Evidence: `docs/SPEC.md` Section 10.6 defines `codex.stall_timeout_ms` as “enforced by
  orchestrator based on event inactivity.”

- Observation: The current management command intentionally stops at config validation and prints a
  skeleton message. This is useful because it keeps the remaining gap visible and proves there is
  no hidden orchestrator implementation elsewhere in the repo.
  Evidence: `apps/api/symphony/management/commands/run_orchestrator.py` prints
  `Orchestrator skeleton created. Implementation is pending.`

- Observation: `--once` is needed even after the real orchestrator exists, because the default
  long-running loop is correct for production but wrong for deterministic unit tests and local
  smoke runs.
  Evidence: `apps/api/tests/unit/management/test_run_orchestrator.py` now patches
  `Orchestrator.run_once()` and `Orchestrator.run_forever()` separately and verifies both command
  paths without hanging the test process.

## Decision Log

- Decision: Rewrite `docs/EXEC_PLAN.md` as a living execution document centered on the current
  implementation frontier rather than keeping a generic milestone roadmap.
  Rationale: The repository already contains substantial M1 and partial M2 work. A novice now needs
  precise sequencing, concrete file targets, and proof commands more than a broad architectural
  outline.
  Date/Author: 2026-03-10 / Codex

- Decision: Treat the immediate critical path as three consecutive layers: streamed agent runner,
  then single-issue worker harness, then orchestrator core.
  Rationale: The harness and orchestrator both depend on stable turn completion/error semantics,
  event normalization, and timeout behavior. Implementing them before the streamed runner would
  create duplicate protocol parsing and force later rewrites.
  Date/Author: 2026-03-10 / Codex

- Decision: Keep the raw app-server protocol logic and the higher-level runtime event semantics in
  separate modules.
  Rationale: `apps/api/symphony/agent_runner/client.py` already owns subprocess launch, stdin
  writes, and stdout JSON decoding. Timeout policy, approval policy, unsupported-tool handling, and
  normalized runtime events belong one layer up so both the worker harness and the orchestrator can
  consume the same abstraction.
  Date/Author: 2026-03-10 / Codex

- Decision: Implement stall handling in the worker-facing turn runner first, but make it use the
  same “last protocol activity” semantics that the orchestrator will later surface in runtime
  state.
  Rationale: The spec places stall policy in the coordination layer, but the repository needs a
  testable implementation before the full poll loop exists. A worker-facing watchdog gives that
  proof without forcing stall logic into the lowest-level parser.
  Date/Author: 2026-03-10 / Codex

- Decision: Keep continuation retry and failure retry scheduling inside the orchestrator, even
  though the worker harness now knows why a run ended.
  Rationale: Retry policy belongs to the single authoritative coordination layer. The harness
  returns typed outcomes; the orchestrator decides whether those outcomes mean continuation,
  exponential backoff, release, or cleanup.
  Date/Author: 2026-03-10 / Codex

## Outcomes & Retrospective

- 2026-03-10: Replaced the generic execution roadmap with a repository-state-aware ExecPlan. The
  immediate outcome is clarity: the next deliverable is no longer “more M2 work” in the abstract;
  it is a streamed agent runner that can terminate success, failure, timeout, and stall cases and
  feed a single-issue harness. The remaining gap is implementation, not planning.
- 2026-03-10: Completed the planned critical path. The repository now has a normalized streamed
  agent runner, a single-issue worker harness, and a working orchestrator core with retry and
  reconciliation tests. Remaining work is no longer foundational execution plumbing; it is follow-on
  product and operational surface area.

## Context and Orientation

The relevant backend code lives under `apps/api/symphony/`. The repository already has working
modules for workflow loading (`workflow/loader.py`), typed config and defaults
(`workflow/config.py`), Linear normalization (`tracker/linear.py`), Linear API transport and
queries (`tracker/linear_client.py`), workspace directory safety (`workspace/manager.py`), and
prompt construction (`agent_runner/prompting.py`). The Django command
`apps/api/symphony/management/commands/run_orchestrator.py` currently validates workflow startup
inputs and then exits with a “skeleton pending” message.

In this plan, “app-server” means the Codex subprocess launched with `bash -lc <codex.command>` in
the workspace directory. Its stdout carries one JSON protocol message per line. Its stderr is
diagnostic text only and must never be parsed as protocol. A “turn” means one `turn/start`
request followed by the streamed protocol messages that end in a terminal outcome such as
`turn/completed`, `turn/failed`, or `turn/cancelled`. A “stall” means the subprocess stays alive
but emits no relevant protocol activity for longer than `codex.stall_timeout_ms`.

The current app-server client is `apps/api/symphony/agent_runner/client.py`. It launches the
subprocess, sends the startup handshake, extracts `thread_id` and `turn_id`, and then returns an
`AppServerSession`. That session is real and useful, but it is incomplete because the rest of the
turn stream is still unread. The existing tests in `apps/api/tests/unit/agent_runner/test_client.py`
prove only the handshake path. They do not prove streamed notifications, terminal turn outcomes,
approval requests, user-input-required failures, unsupported tool calls, total turn timeout, or
stalls.

The orchestrator package exists only as a placeholder (`apps/api/symphony/orchestrator/README.md`,
`apps/api/symphony/orchestrator/__init__.py`). This is important for sequencing. The next code
should not begin in the orchestrator package. It should begin in `agent_runner/`, because that is
where the protocol contract becomes stable enough for the orchestrator to consume.

## Plan of Work

### Milestone 1: Extend the app-server client from handshake-only to streamed turn processing

The first milestone is to make one turn observable from `turn/start` until terminal outcome. Keep
`apps/api/symphony/agent_runner/client.py` as the subprocess/protocol module, but expand it beyond
the handshake. Add a reusable stdout reader that returns decoded JSON objects one complete line at a
time, keeps stderr separate, and surfaces malformed JSON as typed protocol errors without crashing
the surrounding process cleanup.

Introduce a small event model in a new module `apps/api/symphony/agent_runner/events.py`. This
module should define plain dataclasses for normalized runtime events and terminal turn results. The
names should be boring and explicit. A novice should be able to read the type names and understand
what they carry without opening the spec. At minimum, define a runtime event type carrying the
event name, UTC timestamp, `session_id`, `thread_id`, `turn_id`, the app-server PID if available,
an optional usage snapshot, and a small payload map for event-specific fields. Also define a turn
termination object that records whether the turn completed successfully, failed, was cancelled,
timed out, or ended because input was required.

Update `apps/api/symphony/agent_runner/client.py` so that after `start_app_server_session(...)`
returns, a caller can invoke a streaming function such as `stream_turn(...)` or `run_turn_stream(...)`
against the same `AppServerSession`. That function must read stdout until it sees a terminal turn
message, process interleaved notifications, and keep enough structured information to emit
normalized runtime events. Do not make the caller parse raw Codex JSON payloads. The caller should
receive normalized events and one terminal result.

Expand `apps/api/tests/unit/agent_runner/test_client.py` with a richer fake app-server transcript.
Add tests for at least: interleaved notifications before terminal completion, `turn/completed`,
`turn/failed`, `turn/cancelled`, malformed JSON lines, subprocess exit before terminal message, and
usage payload extraction when the fake server includes token totals.

The result of this milestone is observable: the unit tests should prove that a session can survive
the startup handshake and then produce a normalized terminal outcome from a streamed turn.

### Milestone 2: Add timeout, inactivity, and policy handling to the streamed runner

Once one streamed turn works, add the time-based behavior required by `docs/SPEC.md`. Keep the
deadline math out of the lowest-level JSON decoder. The low-level parser should know only how to
read one line and decode one message. The higher-level streamed runner should own the monotonic
clock, the overall turn deadline, and the inactivity deadline.

In a new module `apps/api/symphony/agent_runner/runner.py`, define the worker-facing abstraction
that consumes `AppServerSession` plus turn configuration and emits normalized runtime events through
an async callback. This module should enforce:

1. `codex.read_timeout_ms` for synchronous request/response operations.
2. `codex.turn_timeout_ms` for total elapsed time from `turn/start` until terminal result.
3. `codex.stall_timeout_ms` for inactivity since the last protocol activity or policy action.

This module should also implement the policy behaviors required to prevent turns from hanging:
auto-approve approval requests when the configured policy says to auto-approve, fail the turn
immediately on user-input-required signals, and return a structured failure result for unsupported
dynamic tool calls so the session can continue instead of stalling. Keep the policy implementation
simple and explicit; do not introduce a general plugin system here.

Add focused tests under `apps/api/tests/unit/agent_runner/`. The fake app-server should be able to
simulate a silent stall, a never-ending turn, a user-input-required request, an approval request,
and an unsupported tool call. The new tests should assert both the terminal result and the emitted
normalized events. The important outcome is determinism: a turn that would otherwise hang must now
produce a predictable failure category.

The result of this milestone is observable: the unit suite can prove all end states required for a
single turn without relying on orchestrator code.

### Milestone 3: Build the single-issue worker harness around the streamed runner

After the streamed runner semantics are stable, add the worker harness in
`apps/api/symphony/agent_runner/` or a closely related backend module. This harness is the missing
proof that Symphony can execute one issue attempt end-to-end outside the poll loop. It should own:
workspace creation or reuse via `apps/api/symphony/workspace/manager.py`, hook execution, prompt
construction, app-server session startup, continuation-turn logic up to `agent.max_turns`, and
final cleanup/return values.

Implement hook execution before and after the run using the timeout already defined in
`hooks.timeout_ms`. Fatal hook behavior must match the spec: `after_create` and `before_run`
failures abort the current attempt; `after_run` and `before_remove` failures are logged and
ignored. The harness must use the full rendered prompt on the first turn and
`build_continuation_guidance(...)` on subsequent turns within the same thread.

Create a direct harness test path. This can be a dedicated test helper or a small management
command used only for manual proof, but it must be runnable from the repository root without the
orchestrator loop. The harness tests should prove success, retry-worthy failure, timeout, stall,
and multi-turn continuation behavior with one persistent `thread_id`.

The result of this milestone is observable: one issue can be run end-to-end against a fake
app-server without involving tracker polling or concurrency control.

### Milestone 4: Implement orchestrator core on top of the harness and normalized runner events

Only after Milestones 1 through 3 are complete should work move into
`apps/api/symphony/orchestrator/`. Create a plain-Python state model for running issues, claimed
issues, retry entries, and live session metadata. Keep this state machine framework-light so the
Django management command remains a thin host.

The orchestrator core should use the existing Linear client and config layer to fetch eligible
issues, claim them, dispatch worker harness tasks, and reconcile active runs against tracker state.
Normal worker exit should schedule the short continuation retry described in the spec. Abnormal exit
should schedule exponential backoff up to `agent.max_retry_backoff_ms`. Terminal issue state changes
should stop running work and eventually clean the corresponding workspace.

Testing here should focus on deterministic state transitions rather than protocol details. Create
unit tests for candidate selection, claim release, retry scheduling, stall-driven termination, and
reconciliation when an issue leaves the active states. The orchestrator tests must treat the worker
harness as an injected dependency that emits normalized events, not as a place to re-test raw
Codex JSON protocol handling.

The result of this milestone is observable: `uv run --project apps/api python apps/api/manage.py
run_orchestrator` can continuously poll, dispatch eligible issues within concurrency limits, and
recover from failures using the already-proven worker harness behavior.

## Concrete Steps

Work from the repository root: `/Users/mike/projs/main/symphony`.

1. Re-run the current backend baseline before editing anything:

       uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/tracker apps/api/tests/unit/workspace apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_client.py

   Expected result now:

       ============================== 75 passed in 1.64s ==============================

2. Implement Milestone 1 in `apps/api/symphony/agent_runner/client.py`,
   `apps/api/symphony/agent_runner/events.py`, and the matching tests. Then run:

       uv run pytest apps/api/tests/unit/agent_runner -q

   Expect the suite to include new streaming tests and pass without needing the orchestrator.

3. Implement Milestone 2 in `apps/api/symphony/agent_runner/runner.py` and add the timeout,
   inactivity, approval, and unsupported-tool tests. Then run:

       uv run pytest apps/api/tests/unit/agent_runner -q

   Expect explicit passing cases for `turn_timeout`, stall failure, approval handling, and
   user-input-required failure.

4. Implement Milestone 3 and add a focused single-issue harness test suite. Then run:

       uv run pytest apps/api/tests/unit/agent_runner -q

   Expect harness tests to prove workspace creation, hook semantics, continuation turns, and clean
   subprocess shutdown.

5. Implement Milestone 4 and the management-command integration path. Then run the project quality
   gates:

       make lint
       make typecheck
       make test

   If the repository is not ready for the full `make` targets yet, record the failing command and
   the reason in `Progress`, then keep the narrower targeted suites green while finishing the
   missing setup.

Completed verification transcript:

       uv run ruff check apps/api
       uv run mypy apps/api
       uv run pytest

## Validation and Acceptance

The implementation described by this plan is acceptable only when the following behaviors are
observable.

For the streamed agent runner:

- A fake app-server can emit interleaved notifications and then `turn/completed`, and the runner
  produces normalized runtime events followed by a successful terminal result.
- A fake app-server can emit `turn/failed` or `turn/cancelled`, and the runner maps those to
  deterministic failure categories without leaving the subprocess hanging.
- A fake app-server can stop emitting protocol activity, and the worker-facing runner ends the turn
  with the configured stall failure once `codex.stall_timeout_ms` elapses.
- A fake app-server can keep streaming non-terminal noise forever, and the runner ends the turn
  with the configured `turn_timeout` once `codex.turn_timeout_ms` elapses.
- Approval requests, unsupported tool calls, and user-input-required signals no longer stall the
  session indefinitely.

For the worker harness:

- One issue can execute from workspace acquisition through final result without the poll loop.
- Continuation turns reuse the original `thread_id` and stop when `agent.max_turns` is reached or a
  terminal run result is produced.
- Hook failure semantics match the spec and are proven by tests.

For the orchestrator core:

- The management command can dispatch eligible issues, track active work, and schedule retries
  without reparsing Codex protocol messages.
- Reconciliation stops work when an issue becomes terminal or otherwise ineligible.

The final proof command remains:

    make lint
    make typecheck
    make test

The plan is not complete until these checks pass or any residual blockers are explicitly documented
in `Progress` with their exact failing command and reason.

## Idempotence and Recovery

The planned steps are intentionally additive. Re-running the targeted pytest commands is safe and
should not mutate repository state. The fake app-server tests should always create their own
temporary files under `tmp_path`, so they can be repeated without cleanup.

When editing the agent runner, always preserve process cleanup on failure. Any new streaming or
watchdog code must terminate or kill the subprocess if it exits abnormally or if a timeout fires.
This protects repeated local test runs from accumulating orphaned app-server processes. If a new
test flakes because a subprocess remains alive, treat that as a correctness bug in the harness or
runner rather than as “just a test issue.”

If work on Milestones 3 or 4 reveals that the event model from Milestones 1 or 2 is missing
fields, revise `apps/api/symphony/agent_runner/events.py` and update this ExecPlan in the same
change. Do not bypass the normalized event model by letting higher layers inspect raw protocol
payloads directly.

## Artifacts and Notes

Current proof that the repository foundation exists:

    $ uv run pytest apps/api/tests/unit/workflow apps/api/tests/unit/tracker apps/api/tests/unit/workspace apps/api/tests/unit/agent_runner/test_prompting.py apps/api/tests/unit/agent_runner/test_client.py
    ============================== 75 passed in 1.64s ==============================

Current proof that the orchestrator is still only a startup shell:

    Superseded on 2026-03-10 01:53Z. The management command now instantiates `Orchestrator` and can
    either run one tick with `--once` or enter the long-running loop by default.

Current proof of the handshake-only boundary:

    In `apps/api/symphony/agent_runner/client.py`, `start_app_server_session(...)` sends:
      initialize
      initialized
      thread/start
      turn/start

    It then returns `AppServerSession(...)` immediately after extracting `thread_id` and `turn_id`.
    No function currently reads the remainder of that turn's stdout protocol stream.

## Interfaces and Dependencies

The implementation should stay within the existing backend stack: Python 3.12, `asyncio`, Django
management commands as the host entrypoint, and plain dataclasses for the protocol/runtime models.
Do not introduce Celery, Redis, or a separate job framework for this work.

Create the following interfaces as part of Milestones 1 and 2.

In `apps/api/symphony/agent_runner/events.py`, define:

    @dataclass(slots=True, frozen=True)
    class UsageSnapshot:
        input_tokens: int
        output_tokens: int
        total_tokens: int

    @dataclass(slots=True, frozen=True)
    class AgentRuntimeEvent:
        event: str
        timestamp: datetime
        session_id: str
        thread_id: str
        turn_id: str
        codex_app_server_pid: int | None
        usage: UsageSnapshot | None
        payload: Mapping[str, Any]

    @dataclass(slots=True, frozen=True)
    class TurnResult:
        outcome: str
        error_code: str | None
        message: str | None
        usage: UsageSnapshot | None

In `apps/api/symphony/agent_runner/client.py`, keep and extend:

    async def start_app_server_session(...) -> AppServerSession

    async def start_next_turn(
        session: AppServerSession,
        *,
        prompt_text: str,
        title: str,
        approval_policy: str,
        sandbox_policy: Mapping[str, Any],
        read_timeout_ms: int,
    ) -> str:
        ...

    async def read_protocol_message(
        session: AppServerSession,
        *,
        timeout_seconds: float | None = None,
    ) -> Mapping[str, Any]:
        ...

The exact helper names can change if the final implementation is clearer, but the boundary must
remain: `client.py` owns subprocess I/O and JSON message decoding.

In `apps/api/symphony/agent_runner/runner.py`, define:

    async def stream_turn(
        session: AppServerSession,
        *,
        turn_timeout_ms: int,
        stall_timeout_ms: int,
        on_event: Callable[[AgentRuntimeEvent], Awaitable[None]] | None = None,
    ) -> TurnResult:
        ...

This function is the worker-facing abstraction that Milestone 3 and Milestone 4 should consume.
The worker harness may wrap it, but higher layers must not reimplement raw Codex protocol parsing.

In the future worker harness module, define a single top-level async entrypoint that accepts the
normalized `Issue`, the typed `ServiceConfig`, and a callback for runtime events, and returns a
typed attempt result that the orchestrator can use for retry decisions. Keep the name explicit, for
example `run_issue_attempt(...)`.

Revision note (2026-03-10 00:53Z): rewrote this file from a generic milestone roadmap into a
repository-state-aware living ExecPlan. Reason: the codebase already has workflow/tracker/workspace
foundations and a handshake-only agent runner, so the immediate need is an executable critical-path
plan for streamed turns, timeout/stall handling, the single-issue worker harness, and the
orchestrator core that depends on them.

Revision note (2026-03-10 01:53Z): updated this file after implementation. Reason: the critical
path is now complete, so the plan needed to record the shipped modules, final validation commands,
and the remaining boundary between foundational execution plumbing and later operational work.
