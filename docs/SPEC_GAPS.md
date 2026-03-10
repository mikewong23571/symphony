# SPEC Gaps

Status: Audit snapshot as of 2026-03-10

Purpose: Record confirmed gaps between the current implementation and `docs/SPEC.md`.

Scope notes:
- This document tracks confirmed gaps only.
- Every item listed here is currently `Unfixed`.
- `docs/SPEC.md` remains the normative behavior contract.

## Core Conformance Gaps

- [ ] Unfixed | High | Tracker and dispatch failure paths are still silent.
  Spec references: `docs/SPEC.md` Sections 11.4, 13.2, 17.6.
  Current gap: candidate fetch, running-state refresh, and startup terminal-cleanup failures are swallowed without operator-visible logs.
  Evidence: `apps/api/symphony/orchestrator/core.py`.

- [ ] Unfixed | High | `after_run` and `before_remove` hook failures are ignored without logging.
  Spec references: `docs/SPEC.md` Sections 9.4, 15.4, 17.2.
  Current gap: best-effort hook failures/timeouts are suppressed instead of being logged and ignored.
  Evidence: `apps/api/symphony/workspace/hooks.py`, `apps/api/symphony/agent_runner/harness.py`, `apps/api/symphony/orchestrator/core.py`.

- [ ] Unfixed | Medium | Structured logging is not implemented to the level required by the spec.
  Spec references: `docs/SPEC.md` Sections 13.1, 13.2, 17.6.
  Current gap: runtime logging does not consistently emit `key=value` records with required `issue_id`, `issue_identifier`, and `session_id` context.
  Evidence: `apps/api/symphony/observability/README.md`, `apps/api/symphony/orchestrator/core.py`, `apps/api/symphony/management/commands/run_orchestrator.py`.

- [ ] Unfixed | Medium | App-server `stderr` is buffered but not logged as diagnostics.
  Spec references: `docs/SPEC.md` Sections 17.5, 17.6.
  Current gap: non-JSON `stderr` lines are kept in memory on the session object but are not emitted through any logging path.
  Evidence: `apps/api/symphony/agent_runner/client.py`, `apps/api/tests/unit/agent_runner/test_client.py`.

- [ ] Unfixed | Medium | Workspace prep does not remove temporary artifacts like `tmp` and `.elixir_ls`.
  Spec references: `docs/SPEC.md` Section 17.2.
  Current gap: workspace creation/reuse flows proceed directly into hooks and agent launch without a prep cleanup pass.
  Evidence: `apps/api/symphony/workspace/manager.py`, `apps/api/symphony/agent_runner/harness.py`.

- [ ] Unfixed | Low | Token accounting semantics are still explicitly provisional.
  Spec references: `docs/SPEC.md` Sections 13.5, 17.6.
  Current gap: the implementation still warns that usage semantics are unknown and does not yet prove correct aggregation across repeated updates.
  Evidence: `apps/api/symphony/orchestrator/core.py`, `apps/api/symphony/agent_runner/events.py`, `apps/api/tests/unit/orchestrator/test_core.py`.

- [ ] Unfixed | Low | Prompt-rendering error taxonomy is coarser than the spec.
  Spec references: `docs/SPEC.md` Section 5.5.
  Current gap: parse errors and render errors are collapsed into one template error class instead of distinguishing `template_parse_error` from `template_render_error`.
  Evidence: `apps/api/symphony/agent_runner/prompting.py`, `apps/api/tests/unit/agent_runner/test_prompting.py`.

## Recommended Extension Gaps

- [ ] Unfixed | Medium | Retry queue and session metadata are not persisted across process restarts.
  Spec references: `docs/SPEC.md` Section 18.2.
  Current gap: orchestrator state is rebuilt from scratch on process start; no restore path exists for retry/session metadata.
  Evidence: `apps/api/symphony/orchestrator/core.py`, `apps/api/symphony/management/commands/run_orchestrator.py`.

- [ ] Unfixed | Low | Observability settings are not configurable from workflow front matter.
  Spec references: `docs/SPEC.md` Section 18.2.
  Current gap: workflow config currently exposes the HTTP `server` extension, but not configurable observability/logging settings.
  Evidence: `apps/api/symphony/workflow/config.py`.
