# Add `linear_graphql` Dynamic Tool Support to the Python Runtime

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`, `Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.

This document must be maintained in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

After this change, a Codex app-server session started by the Python runtime can discover and call a
local `linear_graphql` dynamic tool. The tool lets the agent run raw Linear GraphQL queries and
mutations using Symphony’s configured Linear endpoint and auth without reading tokens from disk.

The visible proof is behavioral. During `thread/start`, the runtime advertises a `dynamicTools`
entry for `linear_graphql`. During a turn, when the app-server emits `item/tool/call`, the runtime
executes the requested GraphQL document locally, returns a structured `success`/`output` result,
and continues the turn instead of failing with `unsupported_tool_call`.

## Progress

- [x] 2026-03-16 13:30Z: Read `.agent/PLANS.md`, the `linear_graphql` sections in `docs/SPEC.md`,
  the Elixir reference document at `/Users/mike/projs/fork/symphony/elixir/docs/linear_graphql_tool.md`,
  and the current Python `agent_runner` modules to identify the injection and execution seams.
- [x] 2026-03-16 13:43Z: Confirmed that the Python runtime still speaks JSON-RPC directly and does
  not use the Codex Python SDK package locally; therefore the implementation should preserve the
  existing client and align only the wire behavior with the SDK/app-server protocol.
- [x] 2026-03-16 14:05Z: Added `apps/api/symphony/agent_runner/dynamic_tool.py` and wired
  `client.py`, `runner.py`, and `harness.py` so Linear workflows advertise `linear_graphql` during
  `thread/start` and execute supported `item/tool/call` requests locally.
- [x] 2026-03-16 14:05Z: Extended `apps/api/symphony/tracker/linear_client.py` with a raw GraphQL
  execution path that preserves top-level GraphQL `errors` for dynamic-tool callers while leaving
  the existing tracker read/write paths unchanged.
- [x] 2026-03-16 14:18Z: Added focused tests for dynamic-tool specs, argument validation, handshake
  advertisement, supported tool execution, and unsupported-tool fallback under
  `apps/api/tests/unit/agent_runner/`.
- [x] 2026-03-16 14:22Z: Validated the touched surfaces with
  `uv run pytest apps/api/tests/unit/agent_runner -q`,
  `uv run pytest apps/api/tests/unit/tracker/test_linear_client.py -q`,
  `uv run ruff check apps/api/symphony/agent_runner apps/api/symphony/tracker/linear_client.py apps/api/tests/unit/agent_runner`,
  and
  `uv run mypy apps/api/symphony/agent_runner apps/api/symphony/tracker/linear_client.py apps/api/tests/unit/agent_runner`.
- [x] 2026-03-16 07:46Z: Recorded the follow-on Codex SDK migration in
  `docs/EXEC_PLAN_CODEX_SDK_MIGRATION.md` and updated this plan so its transport assumptions match
  the current repository state. `linear_graphql` remains implemented and validated, but the runtime
  transport is now SDK-backed instead of repository-owned JSON-RPC.

## Surprises & Discoveries

- Observation: the current Codex Python SDK README is not the main source of dynamic-tool protocol
  details; the README only confirms that the SDK is a wrapper around `codex app-server` JSON-RPC v2.
  Evidence: `sdk/python/README.md` contains the quickstart and thread/turn examples, while the
  generated wire models under `sdk/python/src/codex_app_server/generated/v2_all.py` define
  `DynamicToolSpec`, `DynamicToolCallThreadItem`, and `inputText` content items.

- Observation: the SDK source auto-responds to approval requests but does not execute dynamic tools
  for the caller.
  Evidence: `sdk/python/src/codex_app_server/client.py` handles request messages through
  `_approval_handler`, with no built-in dynamic-tool dispatch path. The Python runtime therefore
  still needs its own `item/tool/call` executor.

- Observation: the existing Python runtime already had the correct interception point for dynamic
  tools.
  Evidence: `apps/api/symphony/agent_runner/runner.py` already recognized `item/tool/call`, but it
  always replied with `unsupported_tool_call`.

## Decision Log

- Decision: Keep the current Python JSON-RPC app-server client and add dynamic-tool support in
  place instead of migrating to the Codex Python SDK first.
  Rationale: the user only requested the `linear_graphql` runtime behavior, and the repository does
  not currently depend on `codex_app_server`. Replacing the transport client would expand the scope
  far beyond the requested feature.
  Date/Author: 2026-03-16 / Codex

- Decision: Preserve this ExecPlan as the record of `linear_graphql` capability semantics after the
  later SDK migration, rather than rewriting it into a second transport-migration plan.
  Rationale: the feature-level behavior introduced here is still current, but the transport decision
  above was superseded by `docs/EXEC_PLAN_CODEX_SDK_MIGRATION.md`. Updating this plan in place keeps
  a novice reader aligned with the current codebase while retaining the original implementation
  rationale and validation evidence for the dynamic tool itself.
  Date/Author: 2026-03-16 / Codex

- Decision: Advertise `linear_graphql` only for Linear-backed workflows.
  Rationale: this repository now supports multiple tracker kinds. Advertising a Linear-only dynamic
  tool to Plane sessions would misrepresent available capabilities and invite invalid tool calls.
  Date/Author: 2026-03-16 / Codex

- Decision: Preserve the Elixir reference behavior that forwards multi-operation GraphQL documents
  unchanged instead of enforcing the stricter single-operation rule in `docs/SPEC.md`.
  Rationale: the user asked to reproduce the runtime behavior from the Elixir reference document.
  Matching the current production behavior was more important for this task than spec-tightening.
  Date/Author: 2026-03-16 / Codex

- Decision: Add a dedicated raw GraphQL execution path to `LinearTrackerClient` instead of
  reaching into transport internals from `agent_runner`.
  Rationale: the transport/auth logic already belongs to the Linear client. Exposing a small public
  helper keeps the dynamic tool layered cleanly and preserves one owner for Linear HTTP behavior.
  Date/Author: 2026-03-16 / Codex

## Outcomes & Retrospective

The Python runtime now matches the requested Elixir-style `linear_graphql` behavior on the critical
path. Linear sessions advertise a dynamic tool during `thread/start`, supported tool calls execute
locally with Symphony-managed auth, GraphQL error bodies are preserved for debugging, and the turn
loop continues after the tool call completes. That behavior survived the later Codex SDK transport
migration recorded in `docs/EXEC_PLAN_CODEX_SDK_MIGRATION.md`, so the feature outcome in this plan
is still current even though the original transport strategy is not. The remaining value of this
document is therefore feature-level: it captures the `linear_graphql` contract, layering decisions,
and validation evidence that must remain true regardless of whether the runtime transport is
handwritten or SDK-backed.

## Context and Orientation

The relevant runtime code lives under `apps/api/symphony/agent_runner/`. In the current repository,
`client.py` is an SDK-backed transport adapter that starts `codex app-server`, performs the
`initialize` / `thread/start` / `turn/start` handshake, and exposes the repository-local session
callbacks that `runner.py` uses. `runner.py` consumes one turn of app-server notifications and
handles request-like messages such as approval prompts and `item/tool/call`. `harness.py` is the
higher-level loop that creates a workspace, starts a session, streams turns, and refreshes issue
state between turns.

Tracker transport code lives under `apps/api/symphony/tracker/`. `linear_client.py` already owns
Linear HTTP requests and GraphQL payload decoding for the repository’s tracker reads and writes.
That file is therefore the correct place to add a raw GraphQL execution helper for dynamic tools.

A “dynamic tool” in this repository means a tool spec injected by the runtime into the Codex
app-server session during `thread/start`. The app-server later asks the runtime to execute that
tool via `item/tool/call`, and the runtime must answer with a structured success or failure payload
that includes `success` and tool output. In the current implementation, the SDK-backed transport
still carries that same logical request/response flow even though the repository no longer owns the
lowest-level JSON-RPC framing.

## Plan of Work

Add a new module at `apps/api/symphony/agent_runner/dynamic_tool.py`. This module should define the
stable `linear_graphql` tool spec, normalize arguments, call the Linear transport using runtime
config, and produce normalized `success`/`output`/`contentItems` responses. The response format
should use `inputText` content items because the generated Codex Python SDK wire models advertise
that as the text output item for dynamic tools.

Update `apps/api/symphony/agent_runner/client.py` so `start_app_server_session(...)` accepts an
optional list of dynamic tool specs and includes them in the `thread/start` params as
`dynamicTools`. In the current repository this happens through the SDK-backed transport adapter, but
the handshake behavior must stay unchanged when no dynamic tools are provided.

Update `apps/api/symphony/agent_runner/runner.py` so `stream_turn(...)` accepts an optional dynamic
tool executor. When the app-server emits `item/tool/call`, extract the tool name and arguments from
the tolerant request shapes used by the current runtime tests and the Elixir reference, execute the
local tool, normalize the returned payload, and respond with the same request id. Unsupported tool
requests should still fail without stalling the session.

Update `apps/api/symphony/agent_runner/harness.py` so it builds the dynamic-tool runtime once per
issue attempt from `ServiceConfig`, passes the tool specs into `start_app_server_session(...)`, and
passes the executor into each `stream_turn(...)` call.

Update `apps/api/symphony/tracker/linear_client.py` with a public raw GraphQL helper that reuses
the existing transport/auth path but optionally preserves top-level GraphQL `errors` in the decoded
payload. Existing tracker read/write callers must continue to reject top-level GraphQL errors as
before.

Add focused tests in `apps/api/tests/unit/agent_runner/test_dynamic_tool.py`,
`apps/api/tests/unit/agent_runner/test_client.py`, and
`apps/api/tests/unit/agent_runner/test_runner.py`. Extend the fake app-server in
`apps/api/tests/unit/agent_runner/fake_app_server.py` only as much as needed to simulate supported
tool calls.

## Concrete Steps

From repository root:

    uv run pytest apps/api/tests/unit/agent_runner/test_dynamic_tool.py \
      apps/api/tests/unit/agent_runner/test_client.py \
      apps/api/tests/unit/agent_runner/test_runner.py -q

Expected result after implementation:

    33 passed in <time>

Then run the broader regression checks:

    uv run pytest apps/api/tests/unit/agent_runner -q
    uv run pytest apps/api/tests/unit/tracker/test_linear_client.py -q
    uv run ruff check apps/api/symphony/agent_runner \
      apps/api/symphony/tracker/linear_client.py \
      apps/api/tests/unit/agent_runner
    uv run mypy apps/api/symphony/agent_runner \
      apps/api/symphony/tracker/linear_client.py \
      apps/api/tests/unit/agent_runner

Expected results after implementation:

    69 passed in <time>
    28 passed in <time>
    All checks passed!
    Success: no issues found in 17 source files

## Validation and Acceptance

Acceptance is behavioral, not just structural.

For handshake validation, start a fake app-server session with injected dynamic tools and inspect
the logged `thread/start` request. The request must include a `dynamicTools` array containing the
`linear_graphql` spec.

For execution validation, run the `tool_call_supported` fake-server scenario and confirm that
`stream_turn(...)` responds to the `item/tool/call` request with `success: true`, normalized
`contentItems`, and a `tool_call_completed` runtime event before the turn completes.

For failure semantics, run the focused dynamic-tool tests and confirm:

- blank `query` input returns `success: false` with a structured error payload
- unsupported tools return `success: false` plus the supported tool list
- top-level GraphQL `errors` preserve the body but mark the tool result as failed

## Idempotence and Recovery

This change is additive and safe to re-run. The tests use a fake app-server and in-memory/fake
Linear clients, so repeated validation does not mutate a real tracker. If a validation step fails,
fix the reported test or type error and rerun the same commands; no cleanup beyond the normal test
workspace removal is required.

## Artifacts and Notes

Focused validation transcript:

    $ uv run pytest apps/api/tests/unit/agent_runner/test_dynamic_tool.py \
        apps/api/tests/unit/agent_runner/test_client.py \
        apps/api/tests/unit/agent_runner/test_runner.py -q
    33 passed in 7.29s

Broader validation transcript:

    $ uv run pytest apps/api/tests/unit/agent_runner -q
    69 passed in 12.57s
    $ uv run pytest apps/api/tests/unit/tracker/test_linear_client.py -q
    28 passed in 0.06s
    $ uv run ruff check apps/api/symphony/agent_runner \
        apps/api/symphony/tracker/linear_client.py \
        apps/api/tests/unit/agent_runner
    All checks passed!
    $ uv run mypy apps/api/symphony/agent_runner \
        apps/api/symphony/tracker/linear_client.py \
        apps/api/tests/unit/agent_runner
    Success: no issues found in 17 source files

## Interfaces and Dependencies

`apps/api/symphony/agent_runner/dynamic_tool.py` must define:

- `LINEAR_GRAPHQL_TOOL_NAME: str`
- `DynamicToolRuntime`
- `build_dynamic_tool_runtime(config: ServiceConfig) -> DynamicToolRuntime`
- `execute_dynamic_tool(...) -> dict[str, Any]`

`apps/api/symphony/agent_runner/client.py` must accept:

- `dynamic_tools: Sequence[Mapping[str, Any]] | None` on `start_app_server_session(...)`

`apps/api/symphony/agent_runner/runner.py` must accept:

- `tool_executor: DynamicToolExecutor | None` on `stream_turn(...)`

`apps/api/symphony/tracker/linear_client.py` must expose:

- `LinearTrackerClient.execute_raw_graphql(query: str, variables: Mapping[str, object])`

Revision note: created after implementation on 2026-03-16 to document the final design and the
exact validation evidence for this feature, without modifying the existing multi-milestone Plane
ExecPlan in `docs/EXEC_PLAN.md`.

Revision note: updated on 2026-03-16 after completing `docs/EXEC_PLAN_CODEX_SDK_MIGRATION.md` so
this plan no longer claims that the current runtime still owns handwritten JSON-RPC transport. The
feature behavior and validation in this document remain authoritative for `linear_graphql`, while
transport ownership now follows the SDK-backed design documented in the later migration plan.
