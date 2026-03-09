# Symphony

Symphony is a coding-agent orchestration service with:

- Django as the backend host and API surface
- an `asyncio`-based orchestrator running as a management command
- Angular + Tailwind CSS for the optional operator dashboard

## Repository Layout

- `apps/api`: Django project, orchestrator, integrations, tests
- `apps/web`: Angular dashboard
- `docs`: specification, execution plan, ADRs
- `scripts`: dev and CI helpers
- `infra`: deployment scaffolding

## Tooling

- Python package management: `uv`
- Node package management: `pnpm`

## Next Steps

1. Install Python and Node toolchains
2. Run `uv sync`
3. Run `pnpm install`
4. Start implementing `docs/EXEC_PLAN.md`
