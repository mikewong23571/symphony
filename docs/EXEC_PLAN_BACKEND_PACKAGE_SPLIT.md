# Backend Package Split: symphony → symphony / runtime / lib

This ExecPlan is a living document. The sections `Progress`, `Surprises & Discoveries`,
`Decision Log`, and `Outcomes & Retrospective` must be kept up to date as work proceeds.
Maintain this document in accordance with `.agent/PLANS.md`.

## Purpose / Big Picture

Currently all backend Python code lives under the `symphony/` package, mixing three distinct
concerns: Django HTTP infrastructure, a long-running orchestrator engine, and shared domain
logic. This makes it easy to accidentally let the engine depend on Django, or the shared layer
depend on the engine, and it will block any future move toward multi-machine runtime workers
(which must be stateless and framework-free).

After this change the backend has three clearly bounded packages:

- `symphony/` — Django layer only: HTTP views, admin, management commands, CLI entry point.
- `runtime/` — orchestrator engine: agent runner, orchestrator state machine, workspace
  lifecycle, observability. Pure Python, no Django imports.
- `lib/` — shared domain logic: workflow config, tracker adapters, common types. No Django,
  no runtime-specific code.

The dependency direction is strict and one-way:

    symphony/ (Django) → runtime/ and lib/
    runtime/           → lib/
    lib/               → nothing internal

A developer can verify the change by running `make lint`, `make typecheck`, and `make test`
and observing all checks pass. No behaviour changes; only import paths change.

## Progress

- [x] 2026-03-17: Milestone 1: Fix the inverted dependency in `workflow/config.py`.
- [x] 2026-03-17: Milestone 2: Create `runtime/` and `lib/` package skeletons.
- [x] 2026-03-17: Milestone 3: Move modules with `git mv` and rewrite imports.
- [x] 2026-03-17: Milestone 4: Update `pyproject.toml` and `AGENTS.md`.
- [x] 2026-03-17: Milestone 5: Verify — lint, typecheck, tests all pass.

## Surprises & Discoveries

- `symphony/workflow/config.py` imports `DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS` (the
  integer `120`) from `symphony/observability/runtime.py`. After the split this would create
  a forbidden `lib → runtime` dependency. The constant is inlined as a fix in Milestone 1.

- `symphony/tracker/write_service.py` imports `log_event` from
  `symphony/observability/logging.py`. After the split this would create a forbidden
  `lib.tracker → runtime.observability` dependency. Resolution: `observability/logging.py`
  contains only stdlib imports (`logging`, `json`, `sys`, `datetime`, `decimal`, `pathlib`)
  and is safe to move to `lib/common/logging.py`. All four callers of `log_event`
  (`agent_runner/harness.py`, `orchestrator/core.py`, `management/commands/run_orchestrator.py`,
  `tracker/write_service.py`) are updated to import from `lib.common.logging`. See Milestone 1.

## Decision Log

- Decision: name the shared layer `lib/` rather than `shared/` or `core/`.
  Rationale: `shared/` is already used in the Angular frontend; `core/` is generic and often
  implies Django-specific meaning; `lib/` is neutral and signals "domain library".
  Date/Author: 2026-03-17 / Mike

- Decision: name the engine layer `runtime/` rather than `engine/` or `orchestrator/`.
  Rationale: the word "runtime" appears throughout the existing codebase
  (`RuntimeHTTPServer`, `get_runtime_snapshot`, `runtime.py`, `RUNTIME_SNAPSHOT_PATH_ENV_VAR`)
  so it matches the established vocabulary.
  Date/Author: 2026-03-17 / Mike

- Decision: keep `symphony/` as the Django layer name rather than renaming it.
  Rationale: `symphony`, `symphony.api`, and `symphony.adminapp` are already registered in
  `INSTALLED_APPS`. Renaming the Django package would require a `manage.py` migration for
  any existing deployment and adds no clarity over the current separation.
  Date/Author: 2026-03-17 / Mike

- Decision: fix the `workflow/config.py → observability/runtime.py` dependency by inlining
  the constant rather than moving it to `lib/common/`.
  Rationale: the constant is a bare integer (`120`). Introducing a shared constants module
  for a single value is premature abstraction. Both files independently defining the same
  default is clearer.
  Date/Author: 2026-03-17 / Mike

- Decision: move `observability/logging.py` to `lib/common/logging.py` rather than keeping
  it in `runtime/observability/`.
  Rationale: `log_event` is a pure stdlib formatting helper with zero internal dependencies.
  Moving it to `lib/common/` fixes the forbidden `lib.tracker → runtime.observability`
  dependency introduced by `write_service.py`, while keeping it accessible to all layers
  (`runtime/` and `symphony/` can both import from `lib/`). The remaining files in
  `runtime/observability/` (`events.py`, `runtime.py`, `snapshots.py`) all have runtime
  coupling and stay in `runtime/`.
  Date/Author: 2026-03-17 / Mike

## Outcomes & Retrospective

The split is complete. The backend now has three cleanly bounded packages under `apps/api/`:

- `symphony/` — Django layer only (apps.py, cli.py, api/, adminapp/, management/).
- `runtime/` — orchestrator engine (agent_runner/, orchestrator/, workspace/, observability/).
- `lib/` — shared domain logic (workflow/, tracker/, common/).

All 378 Python unit tests pass, mypy reports zero issues across 87 source files, and ruff is clean. The only deviation from the written plan was in Milestone 3: `symphony/common/` could not be moved with a single `git mv` because `lib/common/` already existed from the Milestone 1 Fix B skeleton. The two files (`types.py` and `__init__.py`) were moved individually instead, producing the same result. Fifteen ruff import-ordering errors were auto-fixed during Milestone 5; these arose because `lib` and `runtime` sort before `symphony` under isort's first-party rules, requiring reordering in files that mix imports from all three packages.

## Context and Orientation

### Repository layout

The Python source root is `apps/api/`. All paths below are relative to that directory unless
stated otherwise. The root is declared in `pyproject.toml` at the repo root:

    [tool.setuptools.packages.find]
    where = ["apps/api"]
    include = ["config*", "symphony*"]

After this plan, the `include` list expands to cover `runtime*` and `lib*` as well.

### Current package structure (under apps/api/)

    config/                  Django configuration (settings, urls, wsgi, asgi) — unchanged
    symphony/
      apps.py                root AppConfig
      cli.py                 CLI entry point (`symphony-orchestrator` script)
      adminapp/              Django admin AppConfig
      api/                   Django HTTP layer (views.py, server.py, apps.py)
      management/commands/   run_orchestrator management command
      common/types.py        ServiceInfo dataclass           → moves to lib/
      workflow/              workflow config & loader        → moves to lib/
      tracker/               tracker adapters & write layer  → moves to lib/
      agent_runner/          Codex SDK integration           → moves to runtime/
      orchestrator/          state machine                   → moves to runtime/
      workspace/             workspace lifecycle             → moves to runtime/
      observability/         logging, snapshots, SSE events  → moves to runtime/
    tests/unit/              unit tests mirroring the module structure above

### Known cross-dependencies to fix before moving

Two layer violations must be resolved before any files are moved.

**Violation A** — `workflow/config.py` imports from `observability/runtime.py`:

    from symphony.observability.runtime import DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS

`observability` will move to `runtime/`; `workflow` will move to `lib/`. After the split,
`lib/workflow/config.py` importing from `runtime/observability/` would violate the rule.
The constant is the integer `120`. Fix: delete the import and replace the assignment on
line 27 with the literal `120`.

**Violation B** — `tracker/write_service.py` imports from `observability/logging.py`:

    from symphony.observability.logging import log_event

`tracker` will move to `lib/`; `observability` will move to `runtime/`. After the split,
`lib/tracker/write_service.py` importing from `runtime/observability/` would violate the
rule. Fix: move `observability/logging.py` itself to `lib/common/logging.py` before the
bulk `git mv`. The file is stdlib-only and belongs in the shared layer. All four callers
of `log_event` then import from `lib.common.logging` instead:

    agent_runner/harness.py
    orchestrator/core.py
    management/commands/run_orchestrator.py
    tracker/write_service.py

Note: after this move, `runtime/observability/` will contain only `events.py`,
`runtime.py`, and `snapshots.py`. Its `__init__.py` must be updated to remove any
re-export of `log_event` if present.

### Import volume (approximate, from `grep` counts)

    symphony.workflow      30 references across src + tests
    symphony.tracker       25 references
    symphony.observability 18 references
    symphony.agent_runner  13 references
    symphony.workspace      8 references
    symphony.common         7 references
    symphony.orchestrator   6 references
    symphony.api            5 references  (stays in symphony/)
    symphony.management     2 references  (stays in symphony/)
    symphony.cli            1 reference   (stays in symphony/)

Total references to update: ~107 import lines across ~30 files.

### Test tooling

Run tests from the repo root with:

    make test

Run lint with:

    make lint

Run type checking with:

    make typecheck

All three commands must pass before this plan is considered complete.

## Plan of Work

### Milestone 1 — Fix layer violations before any moves

All cross-layer imports must be eliminated while files are still in their original locations,
so that tests can confirm nothing is broken before the bulk restructure begins.

**Fix A — inline the constant in `workflow/config.py`.**

Open `apps/api/symphony/workflow/config.py` and make two edits:

1. Delete: `from symphony.observability.runtime import DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS`
2. Change: `DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS`
   to:     `DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 120`

The constant value is unchanged.

**Fix B — move `observability/logging.py` to `lib/common/logging.py`.**

This file is stdlib-only and must land in `lib/` before the bulk `git mv` in Milestone 3.

1. Create `apps/api/lib/` and `apps/api/lib/common/` with empty `__init__.py` files
   (these are the skeleton files that would otherwise be created in Milestone 2; create
   them now since Fix B needs them).

2. Copy the file: `cp apps/api/symphony/observability/logging.py apps/api/lib/common/logging.py`
   Do not `git mv` yet — the original stays in place temporarily so existing imports keep
   working during this milestone.

3. In the four callers, change `from symphony.observability.logging import log_event` to
   `from lib.common.logging import log_event`:

       apps/api/symphony/agent_runner/harness.py
       apps/api/symphony/orchestrator/core.py
       apps/api/symphony/management/commands/run_orchestrator.py
       apps/api/symphony/tracker/write_service.py

4. Check `apps/api/symphony/observability/__init__.py` for any re-export of `log_event`
   and remove it if present.

5. Delete the now-unreferenced original:
   `git rm apps/api/symphony/observability/logging.py`

After both fixes, run `make test` to confirm nothing breaks. The `lib/` skeleton created
here does not need to be re-created in Milestone 2.

### Milestone 2 — Create package skeletons

Create the `runtime/` package skeleton under `apps/api/`. The `lib/` skeleton was already
created in Milestone 1 Fix B, so only `runtime/` needs to be added here.

    apps/api/runtime/__init__.py   (empty)

### Milestone 3 — Move modules and rewrite imports

Use `git mv` for each move so git history is preserved. After all moves, rewrite every
import in every `.py` file under `apps/api/` (source and tests) that references the old
paths. The full mapping is:

    OLD                              NEW
    symphony.common              →   lib.common
    symphony.workflow            →   lib.workflow
    symphony.tracker             →   lib.tracker
    symphony.agent_runner        →   runtime.agent_runner
    symphony.orchestrator        →   runtime.orchestrator
    symphony.workspace           →   runtime.workspace
    symphony.observability       →   runtime.observability

All `git mv` commands run from `apps/api/`. The paths are relative to that directory.

    cd apps/api
    git mv symphony/common      lib/common
    git mv symphony/workflow    lib/workflow
    git mv symphony/tracker     lib/tracker
    git mv symphony/agent_runner    runtime/agent_runner
    git mv symphony/orchestrator    runtime/orchestrator
    git mv symphony/workspace       runtime/workspace
    git mv symphony/observability   runtime/observability
    cd ../..

Note: `lib/common/logging.py` was already placed there in Milestone 1. After
`git mv symphony/common lib/common`, git will merge the moved directory with the
existing `lib/common/` content — confirm that `lib/common/logging.py` is still present
after the move.

After the moves, do a global search-and-replace across all `.py` files under `apps/api/`
(including `tests/`). The sed patterns below are each specific enough that order does not
affect correctness — none is a substring of another — but the order shown is safe:

    symphony.agent_runner   →   runtime.agent_runner
    symphony.orchestrator   →   runtime.orchestrator
    symphony.workspace      →   runtime.workspace
    symphony.observability  →   runtime.observability
    symphony.common         →   lib.common
    symphony.workflow       →   lib.workflow
    symphony.tracker        →   lib.tracker

Also rewrite bare module imports such as:

    import symphony.agent_runner.harness as harness_module
    →
    import runtime.agent_runner.harness as harness_module

After rewriting, run `make lint` to catch any missed references.

### Milestone 4 — Update project metadata and documentation

**`pyproject.toml`** (repo root): extend the `include` list so setuptools discovers the new
packages:

    [tool.setuptools.packages.find]
    where = ["apps/api"]
    include = ["config*", "symphony*", "runtime*", "lib*"]

After editing `pyproject.toml`, re-install the package so the Python environment picks up
the new package paths:

    uv sync

**`AGENTS.md`** (repo root): update the Code Map section to reflect the new structure.
Replace the backend module entries so they read:

    - apps/api/symphony/: Django layer — apps.py, cli.py, api/ (HTTP views + embedded server),
      adminapp/, management/commands/run_orchestrator.py
    - apps/api/runtime/: orchestrator engine — agent_runner/, orchestrator/, workspace/,
      observability/ (events.py, runtime.py, snapshots.py)
    - apps/api/lib/: shared domain logic — workflow/, tracker/, common/ (includes logging.py)

Note on naming: the file `runtime/observability/runtime.py` has a module path of
`runtime.observability.runtime` — the package name and file name are both "runtime".
This is valid Python and is a pre-existing naming quirk, not a mistake introduced by
this restructure.

### Milestone 5 — Verify

From the repo root, run all three checks in order:

    make lint
    make typecheck
    make test

Expected outcome: all checks pass with zero errors. If `mypy` reports `Module not found`
errors for `runtime` or `lib`, confirm that `apps/api` appears in `tool.mypy.mypy_path`
in `pyproject.toml` (it already does: `mypy_path = ["apps/api"]`).

## Concrete Steps

Work from the repo root unless a different directory is specified.

Step 1 — Fix layer violations (all edits while files are still in original locations).

Fix A — inline constant in workflow/config.py:

    Edit apps/api/symphony/workflow/config.py:
      remove:  from symphony.observability.runtime import DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS
      change:  DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = DEFAULT_RUNTIME_SNAPSHOT_MAX_AGE_SECONDS
          to:  DEFAULT_SNAPSHOT_MAX_AGE_SECONDS = 120

Fix B — move logging.py to lib/common/ and update all callers:

    mkdir -p apps/api/lib/common
    touch apps/api/lib/__init__.py
    touch apps/api/lib/common/__init__.py
    cp apps/api/symphony/observability/logging.py apps/api/lib/common/logging.py

    # Update the four callers (change from symphony.observability.logging to lib.common.logging):
    # apps/api/symphony/agent_runner/harness.py
    # apps/api/symphony/orchestrator/core.py
    # apps/api/symphony/management/commands/run_orchestrator.py
    # apps/api/symphony/tracker/write_service.py

    # Remove the original (after confirming the four callers all point to lib.common.logging):
    git rm apps/api/symphony/observability/logging.py

    # Check observability/__init__.py for any re-export of log_event and remove it:
    grep "log_event" apps/api/symphony/observability/__init__.py

    make test   # must pass before proceeding

Step 2 — Create runtime/ skeleton (lib/ was already created in Step 1).

    touch apps/api/runtime/__init__.py

Step 3 — Move modules (run from apps/api/).

    cd apps/api
    git mv symphony/common      lib/common
    git mv symphony/workflow    lib/workflow
    git mv symphony/tracker     lib/tracker
    git mv symphony/agent_runner    runtime/agent_runner
    git mv symphony/orchestrator    runtime/orchestrator
    git mv symphony/workspace       runtime/workspace
    git mv symphony/observability   runtime/observability
    cd ../..

Step 4 — Rewrite imports (run from apps/api/).

Apply substitutions across all .py files. A safe sequence using sed on macOS:

    cd apps/api
    find . -name "*.py" -not -path "./__pycache__/*" | xargs sed -i '' \
      -e 's/symphony\.agent_runner/runtime.agent_runner/g' \
      -e 's/symphony\.orchestrator/runtime.orchestrator/g' \
      -e 's/symphony\.workspace/runtime.workspace/g' \
      -e 's/symphony\.observability/runtime.observability/g' \
      -e 's/symphony\.common/lib.common/g' \
      -e 's/symphony\.workflow/lib.workflow/g' \
      -e 's/symphony\.tracker/lib.tracker/g'
    cd ../..

Verify no stale references remain (the following should print nothing):

    grep -r "symphony\.workflow\|symphony\.tracker\|symphony\.observability\|symphony\.agent_runner\|symphony\.orchestrator\|symphony\.workspace\|symphony\.common" apps/api --include="*.py" | grep -v __pycache__

Step 5 — Update pyproject.toml.

    Edit pyproject.toml:
      change:  include = ["config*", "symphony*"]
      to:      include = ["config*", "symphony*", "runtime*", "lib*"]

    uv sync   # re-install to pick up new package paths

Step 6 — Update AGENTS.md Code Map (backend section).

Step 7 — Run full verification.

    make lint
    make typecheck
    make test

All three must exit 0.

## Validation and Acceptance

The change is purely structural — no runtime behaviour changes. Acceptance criteria:

1. `make lint` exits 0 with no errors.
2. `make typecheck` exits 0 with no mypy errors.
3. `make test` exits 0 with all previously passing tests still passing.
4. Running `grep -r "symphony\.tracker\|symphony\.workflow\|symphony\.observability\|symphony\.agent_runner\|symphony\.orchestrator\|symphony\.workspace\|symphony\.common" apps/api --include="*.py" | grep -v __pycache__` prints nothing.
5. The directory tree shows `apps/api/runtime/` and `apps/api/lib/` each containing their
   respective modules, and `apps/api/symphony/` containing only `apps.py`, `cli.py`,
   `api/`, `adminapp/`, and `management/`.

## Idempotence and Recovery

The `git mv` commands in Step 3 are safe to re-run only if the destination does not already
exist. If you need to restart: `git checkout -- .` and `git clean -fd apps/api/runtime apps/api/lib`
to remove any partially created directories, then begin again from Step 1.

The import rewrite with `sed -i ''` is idempotent — running it twice on already-rewritten
files produces no further changes.

## Artifacts and Notes

Modules that remain in `symphony/` after the split:

    symphony/__init__.py
    symphony/apps.py
    symphony/cli.py
    symphony/adminapp/__init__.py
    symphony/adminapp/apps.py
    symphony/api/__init__.py
    symphony/api/apps.py
    symphony/api/server.py
    symphony/api/views.py
    symphony/management/__init__.py
    symphony/management/commands/__init__.py
    symphony/management/commands/run_orchestrator.py

## Interfaces and Dependencies

No public interfaces change. All moved modules export the same names; only their import
paths change. The `pyproject.toml` entry point is unchanged:

    [project.scripts]
    symphony-orchestrator = "symphony.cli:run_orchestrator_main"

After the split, the enforced layering is:

    runtime.agent_runner    imports from: lib.common, lib.common.logging, lib.tracker,
                                          lib.workflow, runtime.observability, runtime.workspace
    runtime.orchestrator    imports from: lib.common, lib.common.logging, lib.tracker,
                                          lib.workflow, runtime.agent_runner,
                                          runtime.observability, runtime.workspace
    runtime.workspace       imports from: (stdlib only)
    runtime.observability   imports from: (stdlib only — logging.py has moved to lib.common)
    lib.tracker             imports from: lib.workflow, lib.common, lib.common.logging
    lib.workflow            imports from: lib.common, (stdlib only)
    lib.common              imports from: (stdlib only)
    lib.common.logging      imports from: (stdlib only)
    symphony.api.views      imports from: lib.tracker, lib.workflow, runtime.observability
    symphony.management     imports from: lib.common.logging, lib.workflow,
                                          runtime.observability, runtime.orchestrator,
                                          symphony.api.server
