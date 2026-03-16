# Migrate Python App-Server Transport to the Official Codex SDK

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

This plan builds on the runtime work recorded in `docs/EXEC_PLAN_LINEAR_GRAPHQL_RUNTIME.md`. That
earlier plan established the current `linear_graphql` dynamic-tool behavior on top of the
repository’s handwritten JSON-RPC client. This plan keeps that user-visible behavior, but replaces
the lower transport layer with the official Python SDK for `codex app-server`.

## Purpose / Big Picture

After this change, Symphony’s Python runtime will talk to `codex app-server` through the official
`codex_app_server_sdk` Python SDK instead of maintaining its own JSON-RPC request/response loop. The
benefit is operational, not cosmetic: thread startup, turn startup, notification decoding, request
correlation, and future protocol drift will be delegated to the upstream SDK rather than re-created
inside this repository.

The user-visible acceptance remains the same as today. Starting an issue run still creates a Codex
thread, streams a turn, auto-approves requests when the workflow says `approval_policy: never`,
fails fast on user-input requirements, and supports the local `linear_graphql` dynamic tool for
Linear-backed workflows. The difference is that the implementation path uses the official SDK under
the hood, and the repository no longer owns the lowest-level app-server transport details.

## Progress

- [x] 2026-03-16 14:35Z: Read `.agent/PLANS.md`, the current
  `docs/EXEC_PLAN_LINEAR_GRAPHQL_RUNTIME.md`, and the relevant runtime files under
  `apps/api/symphony/agent_runner/` to identify the current handwritten transport boundaries.
- [x] 2026-03-16 14:35Z: Inspected the official Python SDK package metadata and source to confirm
  the practical migration constraints: the package name is `codex-app-server-sdk`, the import path
  is `codex_app_server_sdk`, the primary client is the async `CodexClient`, `connect_stdio(...)`
  can preserve the current shell-based `codex.command` behavior, and the built-in approval handler
  only auto-handles approval-style requests.
- [x] 2026-03-16 14:35Z: Confirmed that the released SDK thread config models do not yet expose a
  typed `dynamicTools` field, so dynamic-tool advertisement must use raw dict params even after
  transport migration.
- [x] 2026-03-16 15:25Z: Completed Milestone 1. Added `start_sdk_app_server_session(...)` as an
  additive SDK handshake spike in `apps/api/symphony/agent_runner/client.py`, preserved the old
  handwritten path, pinned `codex-app-server-sdk==0.3.2` in `pyproject.toml`, and added focused
  SDK-monkeypatch tests in `apps/api/tests/unit/agent_runner/test_client.py`.
- [x] 2026-03-16 15:25Z: Validated the Milestone 1 spike with
  `uv run pytest apps/api/tests/unit/agent_runner/test_client.py -q` -> `13 passed in 3.03s`,
  `uv run ruff check apps/api/symphony/agent_runner/client.py apps/api/tests/unit/agent_runner/test_client.py`,
  and `uv run mypy apps/api/symphony/agent_runner/client.py apps/api/tests/unit/agent_runner/test_client.py`.
- [x] 2026-03-16 16:45Z: Completed Milestone 2. `start_app_server_session(...)` now defaults to
  the SDK-backed transport, `AppServerSession` carries adapter callbacks for SDK notification
  reads / request replies / continuation turns, and `runner.py` now exercises those callbacks
  without changing higher-level timeout or event semantics.
- [x] 2026-03-16 16:45Z: Added focused SDK-backed streaming tests for approval handling, tool
  execution, and continuation turns; kept the legacy fake-app-server path only as an internal test
  helper for JSONL regression coverage and harness tests.
- [x] 2026-03-16 16:45Z: Validated the Milestone 2 surface with
  `uv run pytest apps/api/tests/unit/agent_runner -q` -> `72 passed in 12.50s`,
  `uv run pytest apps/api/tests/unit/tracker/test_linear_client.py -q` -> `28 passed in 0.05s`,
  `uv run ruff check apps/api/symphony/tracker/linear_client.py apps/api/symphony/agent_runner apps/api/tests/unit/agent_runner`,
  and `uv run mypy apps/api/symphony/tracker/linear_client.py apps/api/symphony/agent_runner apps/api/tests/unit/agent_runner`.
- [x] 2026-03-16 07:37Z: Completed Milestone 3. Removed the handwritten JSONL transport path from
  `apps/api/symphony/agent_runner/client.py`, reduced `AppServerSession` to callback-backed SDK
  adaptation plus stderr diagnostics, and moved the fake-app-server JSONL handshake/stream logic
  into the test-only helper `apps/api/tests/unit/agent_runner/legacy_transport.py`.
- [x] 2026-03-16 07:37Z: Validated the Milestone 3 surface with
  `uv run pytest apps/api/tests/unit/agent_runner -q` -> `72 passed in 12.57s`,
  `uv run ruff check apps/api/symphony/agent_runner apps/api/tests/unit/agent_runner` -> `All checks passed!`,
  and `uv run mypy apps/api/symphony/agent_runner apps/api/tests/unit/agent_runner` ->
  `Success: no issues found in 17 source files`.
- [x] 2026-03-16 07:44Z: Completed the Milestone 4 documentation sweep. Updated `docs/SPEC.md` so
  the app-server contract describes a transport-agnostic stdio session with SDK-compatible
  notification handling instead of requiring repository-owned JSONL parsing, and updated
  `apps/api/symphony/agent_runner/README.md` to describe the module as SDK-backed.
- [x] 2026-03-16 07:46Z: Completed Milestone 4 validation with `make format`, `make lint`,
  `make typecheck`, and `make test`. Evidence: `make format` reported `87 files left unchanged`
  plus unchanged Prettier targets; `make lint` reported `All checks passed!` plus a clean frontend
  eslint run; `make typecheck` reported `Success: no issues found in 86 source files` plus a clean
  frontend `tsc --noEmit`; `make test` reported `376 passed in 16.78s` for backend pytest and
  `28 passed` for frontend Vitest.

## Surprises & Discoveries

- Observation: the published package differs from the earlier planning assumption in both import
  path and client shape.
  Evidence: `uv run --with codex-app-server-sdk python` exposed package `codex_app_server_sdk`
  version `0.3.2`; the top-level exports include async `CodexClient`, not `codex_app_server.AppServerClient`.

- Observation: the current SDK is already async and owns its own receiver loop, so the first
  migration slice does not need `asyncio.to_thread(...)`.
  Evidence: `codex_app_server_sdk.client.CodexClient.connect_stdio(...)` returns an async client,
  `start()` launches an async receiver loop, and `request(...)` is awaitable.

- Observation: the SDK has enough surface for the handshake spike, but it does not expose a public
  notification iterator that cleanly matches Symphony’s current `read_protocol_message(...)`.
  Evidence: `CodexClient` exposes async `request(...)`, `initialize()`, and higher-level chat
  helpers, but notification buffering currently lives behind `_notifications` and `_receiver_loop`.

- Observation: the SDK can still preserve the current `codex.command` configuration model.
  Evidence: `CodexClient.connect_stdio(command=["bash", "-lc", ...], cwd=...)` accepts explicit
  argv and cwd values, so the repository can continue honoring shell commands such as
  `bash -lc "<configured command>"` instead of forcing contributors onto a different launcher path.

- Observation: typed SDK request models are not yet sufficient for the entire current runtime
  feature set.
  Evidence: `codex_app_server_sdk.models.ThreadConfig` includes `approval_policy`, `sandbox`, and
  `cwd`, but does not include `dynamicTools`, which the current runtime needs for `linear_graphql`.

- Observation: the SDK’s private notification queue is sufficient for the migration adapter even
  though the package does not yet expose a public notification iterator.
  Evidence: `CodexClient._notifications` receives raw server notifications after the receiver loop
  handles request/response correlation, which lets Symphony preserve its existing streaming event
  normalization with a small repository-owned adapter.

- Observation: the repository still needs a narrow legacy handshake entry point for tests that
  intentionally exercise malformed JSONL and oversized-line behavior.
  Evidence: the fake app-server fixtures in `apps/api/tests/unit/agent_runner/` only implement the
  handwritten JSONL loop, so SDK-first runtime tests were added separately while legacy transport
  remains available as an internal helper.

- Observation: the malformed-JSONL regression coverage can be preserved without keeping any raw
  JSONL transport code in production modules.
  Evidence: after moving the old stdout/stderr/request-id logic into
  `apps/api/tests/unit/agent_runner/legacy_transport.py`, the full focused suite still reported
  `72 passed in 12.57s` while `apps/api/symphony/agent_runner/client.py` retained only SDK-backed
  callbacks.

- Observation: `docs/SPEC.md` still described the execution layer as if Symphony itself owned raw
  stdout JSONL framing even after the runtime had switched to the official SDK.
  Evidence: before the M4 doc sweep, Section 10 required “line-delimited protocol messages on
  stdout” and the Section 17 acceptance bullets required buffering partial JSON lines, which no
  longer matched the repository’s production implementation in `apps/api/symphony/agent_runner/client.py`.

## Decision Log

- Decision: migrate only the transport/client layer first and keep the current higher-level
  `harness.py`, timeout rules, and `dynamic_tool.py` semantics intact.
  Rationale: the user asked to use the official SDK to interact with `app-server`. The safest
  interpretation is to replace the lowest layer while preserving repository-owned runtime behavior.
  Date/Author: 2026-03-16 / Codex

- Decision: continue honoring `codex.command` through SDK `launch_args_override` rather than
  switching immediately to the SDK’s pinned runtime package.
  Rationale: the repository already treats the Codex launch command as workflow configuration.
  Removing that flexibility during the migration would create an unnecessary behavior change and
  complicate local testing.
  Date/Author: 2026-03-16 / Codex

- Decision: keep dynamic-tool execution as repository-owned logic even after adopting the SDK.
  Rationale: the SDK does not provide a built-in dynamic-tool executor. `linear_graphql` uses
  Symphony-managed Linear auth and tracker configuration, which belongs in this repository rather
  than upstream.
  Date/Author: 2026-03-16 / Codex

- Decision: preserve the current async API exported by `symphony.agent_runner`.
  Rationale: upstream SDK adoption should not ripple through the orchestrator and workspace code
  unless there is a strong technical reason. An async adapter layer keeps the rest of the runtime
  stable.
  Date/Author: 2026-03-16 / Codex

- Decision: keep Milestone 1 as an additive handshake spike instead of switching the default
  runtime path immediately.
  Rationale: the released SDK package differs from the earlier assumptions and does not yet expose
  a public notification stream that cleanly replaces `read_protocol_message(...)`. Landing the
  startup path first proves feasibility without breaking the current runner.
  Date/Author: 2026-03-16 / Codex

- Decision: isolate the fake-app-server JSONL transport in test-only code instead of keeping a
  hidden legacy runtime branch inside `client.py`.
  Rationale: Milestone 3 requires production ownership of low-level JSON-RPC transport to disappear,
  but the repository still benefits from regression tests that exercise malformed lines, EOF, and
  oversized notifications against a real subprocess. A test-local helper preserves that coverage
  without leaving dead runtime code in the shipped module.
  Date/Author: 2026-03-16 / Codex

- Decision: revise the spec to describe transport-level behavior in logical terms rather than
  requiring repository-owned stdout JSONL parsing.
  Rationale: after the SDK migration, the stable contract is handshake order, notification
  semantics, timeout behavior, and stderr diagnostics handling. Requiring line-buffer management in
  the spec would falsely constrain the implementation and contradict the current production code.
  Date/Author: 2026-03-16 / Codex

## Outcomes & Retrospective

Milestone 1 is now complete as an additive spike. `apps/api/symphony/agent_runner/client.py`
contains a narrow `start_sdk_app_server_session(...)` path that uses the released SDK to perform
`initialize`, `thread/start`, and `turn/start` while returning the same `thread_id`, `turn_id`,
and `session_id` shape as the handwritten client. The main lesson from this milestone is that the
SDK is viable for the handshake path, but the full migration still depends on introducing an
adapter-owned notification surface for `runner.py`.

Milestone 2 is now complete. The default `start_app_server_session(...)` path is SDK-backed, and
the rest of Symphony continues to talk to a repository-owned `AppServerSession` abstraction rather
than to raw SDK objects. That adapter now owns exactly the Symphony-specific pieces needed for full
streamed turns: notification reads, server-request responses, continuation-turn startup, stderr
diagnostics, and transport-error normalization. The main remaining work for Milestone 3 is to
delete or isolate the handwritten JSONL code that now survives primarily for tests.

Milestone 3 is now complete. `apps/api/symphony/agent_runner/client.py` no longer owns raw stdout
parsing, request id sequencing, pending notification queues, or handwritten handshake matching.
Those behaviors now live only in `apps/api/tests/unit/agent_runner/legacy_transport.py`, which is
explicitly a fake-app-server regression harness rather than production runtime code. The result is
that Symphony’s shipped transport layer is now exclusively SDK-backed while the test suite keeps
the valuable malformed-JSONL coverage that motivated the temporary legacy path.

Milestone 4 is now complete. The remaining developer-facing transport wording has been updated in
`docs/SPEC.md` and `apps/api/symphony/agent_runner/README.md` so the repository now describes an
SDK-backed or otherwise transport-abstracted app-server client instead of claiming that production
code owns raw JSONL framing. Repository-wide validation then passed cleanly through `make format`,
`make lint`, `make typecheck`, and `make test`, so the migration is closed out with both code and
documentation aligned.

## Context and Orientation

The production transport now lives mainly in `apps/api/symphony/agent_runner/client.py`. That file
starts `codex app-server` through the official `codex_app_server_sdk`, adapts SDK requests and
notifications into Symphony’s `AppServerSession` abstraction, and handles the startup handshake for
`initialize`, `thread/start`, and `turn/start`. `runner.py` sits one level above it and interprets
stream messages during a turn. `harness.py` is the orchestration-facing wrapper that starts a
session, runs turns, refreshes tracker state, and closes the session. The old raw JSONL handshake
reader now survives only in `apps/api/tests/unit/agent_runner/legacy_transport.py` as a test
harness for malformed-stream regressions.

The repository now also contains `apps/api/symphony/agent_runner/dynamic_tool.py`, which owns the
local `linear_graphql` tool spec and execution. That logic must remain available after the SDK
migration. The tracker-facing work for raw Linear GraphQL execution lives in
`apps/api/symphony/tracker/linear_client.py`.

The upstream SDK surface relevant to this plan is in the official `codex_app_server_sdk` package.
`CodexClient` is an async client that launches `codex app-server`, sends requests, owns a receiver
loop, and exposes higher-level thread/chat helpers on top of JSON-RPC. It is not an orchestration
framework. Symphony still needs to own long-running issue execution, workflow policy, dynamic-tool
behavior, timeout decisions, and structured runtime events.

A “transport adapter” in this plan means a repository-local wrapper that presents the same async
interface the rest of Symphony already expects, but internally delegates actual app-server
communication to the official SDK.

## Plan of Work

Create an SDK-backed transport adapter in `apps/api/symphony/agent_runner/client.py`. The file
should stop owning raw JSONL parsing and instead wrap `codex_app_server_sdk.CodexClient`. Preserve
the current exported concepts that the rest of Symphony uses: an `AppServerSession` carrying
thread/turn/session ids, a startup function, a way to start continuation turns, and a way to read
the next message from the app-server stream. The released SDK is already async, so the repository
adapter should preserve the current async call pattern directly instead of introducing a thread
bridge unless a later SDK change forces it.

During startup, build the SDK client with `CodexClient.connect_stdio(command=["bash", "-lc", ...])`
so the existing shell command from `config.codex.command` still works. Use SDK `initialize()` and
raw `request(...)` calls for `thread/start` and `turn/start` wherever `dynamicTools` must be
included, because the current typed SDK config models do not expose that field.

Add a repository-owned server-request handler that sits between the SDK and Symphony runtime
policy. That handler must auto-approve approvals when policy allows, reject or answer
`item/tool/requestUserInput` consistently with existing behavior, and execute `item/tool/call`
through `apps/api/symphony/agent_runner/dynamic_tool.py`. Unsupported tools must still return a
structured failure result without stalling the turn.

Update `apps/api/symphony/agent_runner/runner.py` so it consumes SDK notifications rather than raw
decoded dicts from a subprocess reader, but preserves the current timeout model: total turn
timeout, stall timeout based on inactivity, and the same event names used by the orchestrator.
Where the SDK provides typed notifications, normalize them back into the payload shapes that
current tests and orchestrator code expect. Avoid rewriting orchestrator event semantics unless the
SDK makes an existing shape impossible.

Update `apps/api/symphony/agent_runner/harness.py` only as needed to pass the right startup
configuration into the new client layer. The goal is that `run_issue_attempt(...)` remains
structurally the same from the orchestrator’s point of view.

Add the SDK dependency to this repository’s Python project metadata. The dependency strategy should
be explicit: either pin a released `codex-app-server-sdk` version in `pyproject.toml`, or if the
migration requires unreleased SDK behavior, document the exact temporary source install strategy
and its replacement plan. The preferred outcome is a normal pinned package dependency.

Finally, update tests in `apps/api/tests/unit/agent_runner/` so they validate the SDK-backed
adapter rather than the handwritten JSONL transport. Keep fake-server or monkeypatch-based tests
where they still prove behavior cleanly. The new tests must prove both that the SDK path works and
that Symphony-specific policies still hold.

### Milestone 1: Build an SDK transport spike

At the end of this milestone, the repository will have a narrow prototype proving that the official
SDK can start a thread and a turn through Symphony’s configured shell command without changing the
rest of the runtime. The code may still live alongside the handwritten transport temporarily, but
the spike must demonstrate that launch, initialize, `thread/start`, and `turn/start` all work under
test.

Implement a small internal adapter in `apps/api/symphony/agent_runner/client.py` or a sibling
module, keeping the old transport path available behind a temporary branch or helper if needed.
Write focused tests that monkeypatch the SDK client rather than the subprocess directly. The proof
is a passing handshake test that shows the adapter can produce `thread_id`, `turn_id`, and
`session_id` in the same shape as today.

### Milestone 2: Move turn streaming and request handling

At the end of this milestone, a full streamed turn will run through the SDK-backed adapter,
including approval handling, user-input detection, and `linear_graphql` dynamic-tool execution. The
handwritten raw message reader should no longer be the primary runtime path.

Wire `runner.py` to consume notifications from the SDK adapter, then route server-initiated
requests through a repository-owned request handler. Preserve `tool_call_completed`,
`unsupported_tool_call`, `approval_auto_approved`, `turn_input_required`, `turn_failed`, and
`turn_completed` event semantics. The proof is that the existing focused `agent_runner` tests still
pass after being adapted to the new transport boundary.

### Milestone 3: Remove handwritten JSON-RPC ownership

At the end of this milestone, `apps/api/symphony/agent_runner/client.py` will no longer own raw
JSONL request/response logic. Any remaining handwritten transport code should either be deleted or
reduced to thin SDK adaptation glue.

Delete dead helpers for manual request ids, pending message queues, raw stdout parsing, and
handwritten handshake response matching. Keep only the repository-owned pieces that the SDK does
not provide, such as async adaptation, stderr capture if still needed, dynamic-tool execution, and
Symphony-specific event normalization. The proof is that the repository still passes the same test
surface while the low-level transport code shrinks materially.

### Milestone 4: Lock validation and documentation

At the end of this milestone, the dependency metadata, tests, and developer documentation will all
describe the SDK-backed transport path accurately. A new contributor will be able to understand why
the repository uses the SDK and where repository-specific behavior still lives.

Update `pyproject.toml`, any relevant `README` or development notes, and this ExecPlan with the
final validation evidence. If the migration changes how fake app-server tests are structured,
explain the new test strategy directly in the docs. The proof is a clean validation run plus a
clear record of what remains owned by Symphony versus what is delegated to the official SDK.

## Concrete Steps

Start with repository-local exploration and a transport spike:

    cd /Users/mike/projs/main/symphony
    uv run pytest apps/api/tests/unit/agent_runner/test_client.py -q

During the spike, add or adapt tests so they can be re-run quickly while replacing the transport
layer. Expect the final command set to include at least:

    cd /Users/mike/projs/main/symphony
    uv run pytest apps/api/tests/unit/agent_runner -q
    uv run pytest apps/api/tests/unit/tracker/test_linear_client.py -q
    uv run ruff check apps/api/symphony/agent_runner \
      apps/api/symphony/tracker/linear_client.py \
      apps/api/tests/unit/agent_runner
    uv run mypy apps/api/symphony/agent_runner \
      apps/api/symphony/tracker/linear_client.py \
      apps/api/tests/unit/agent_runner

If dependency metadata changes, also run:

    cd /Users/mike/projs/main/symphony
    uv sync

The finished implementation should include short evidence snippets in this plan showing the passing
test counts and any dependency install or import validation needed for the SDK package.

## Validation and Acceptance

Acceptance is behavior-focused and must prove parity with the current runtime semantics.

The most important acceptance scenario is a normal issue attempt under a fake app-server. The
runtime must still start a thread, start a turn, stream notifications, and report terminal status
without exposing any JSON-RPC implementation detail to the orchestrator.

The second acceptance scenario is dynamic-tool parity. Under a Linear-backed workflow, the runtime
must still advertise `linear_graphql` during `thread/start`, handle `item/tool/call` requests,
return `success`/`output`/`contentItems`, and continue the turn. This proves that switching to the
SDK did not silently remove repository-specific runtime capabilities.

The third acceptance scenario is policy parity. When approval policy is `never`, approval requests
must still auto-approve. When the app-server requests user input, the run must still fail fast with
`turn_input_required`. When the turn stalls or exceeds its total timeout, the runtime must still
map those cases to the same normalized outcomes the orchestrator expects.

## Idempotence and Recovery

This migration should be performed as an additive refactor until the SDK path is proven. It is safe
to keep a temporary handwritten path or helper in parallel during Milestone 1 if that helps compare
behavior under test. Delete the old path only after the SDK-backed path passes the same regression
checks.

If a milestone fails halfway, revert only the incomplete adapter wiring and keep the last passing
test baseline. Avoid changing orchestrator-facing APIs and transport internals in the same patch
until the SDK adapter is stable; that separation makes retries and review materially easier.

## Artifacts and Notes

Current migration facts captured during planning:

    Official package name: codex-app-server-sdk
    Import path: codex_app_server_sdk
    Core client: codex_app_server_sdk.client.CodexClient
    Important launch knob: CodexClient.connect_stdio(command=["bash", "-lc", ...])
    Important limitation: typed thread config models do not currently expose dynamicTools
    Important limitation: SDK request handler only auto-handles approval-style requests by default

Expected final artifacts for this plan include:

    1. A diff showing `apps/api/symphony/agent_runner/client.py` no longer owns raw JSON line
       parsing.
    2. Passing `agent_runner` and `linear_client` tests.
    3. A dependency diff in `pyproject.toml`.

## Interfaces and Dependencies

The official dependency introduced by this plan should be the upstream Python SDK package:

    codex-app-server-sdk

The final repository should still expose these repository-local interfaces:

In `apps/api/symphony/agent_runner/client.py`:

    async def start_app_server_session(...) -> AppServerSession
    async def read_protocol_message(...) -> Mapping[str, Any]
    async def start_next_turn(...) -> str
    async def send_protocol_message(...) -> None

In `apps/api/symphony/agent_runner/runner.py`:

    async def stream_turn(...) -> TurnResult

In `apps/api/symphony/agent_runner/dynamic_tool.py`:

    def build_dynamic_tool_runtime(config: ServiceConfig) -> DynamicToolRuntime
    def execute_dynamic_tool(...) -> dict[str, Any]

The critical dependency boundary is this: the SDK owns transport, message framing, request ids, and
typed notification decoding; Symphony owns workflow policy, timeout policy, event normalization,
dynamic-tool execution, tracker integration, and issue-run orchestration.

Revision note: updated on 2026-03-16 to close Milestone 4. The plan now records the spec and README
wording changes that align repository docs with the SDK-backed transport, updates the context
sections so they describe the current production code accurately, and includes the full
repository-wide validation evidence proving the migration landed cleanly.
