# SPEC Gaps

Status: Re-audited through roadmap Milestone 5 on 2026-03-10

Purpose: Record confirmed gaps between the current implementation and `docs/SPEC.md`.

Scope notes:
- This document tracks confirmed gaps only.
- A 2026-03-10 re-audit plus focused pytest runs confirmed that the previously listed
  observability, workspace-prep, prompt-taxonomy, recovery, and workflow-configurable
  observability items are already implemented.
- No currently confirmed core conformance gaps remain after that re-audit.
- `docs/SPEC.md` remains the normative behavior contract.

## Core Conformance Gaps

No currently confirmed core conformance gaps remain after the 2026-03-10 re-audit.

## Recommended Extension Gaps

- [ ] Unfixed | Low | Symphony does not yet expose a first-class tracker write surface.
  Spec references: `docs/SPEC.md` Section 18.2.
  Current gap: tracker comments, state transitions, and PR metadata attachment still depend on
  agent tools rather than a backend-owned service or API with normalized mutation semantics.
  Evidence: `apps/api/symphony/tracker/linear_client.py`, `apps/api/symphony/orchestrator/core.py`.
