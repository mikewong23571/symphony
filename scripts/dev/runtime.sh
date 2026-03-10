#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

RUNTIME_HOST="${RUNTIME_HOST:-127.0.0.1}"
RUNTIME_PORT="${RUNTIME_PORT:-9000}"

cd "${REPO_ROOT}"
exec uv run python apps/api/manage.py run_orchestrator --port "${RUNTIME_PORT}" --host "${RUNTIME_HOST}"
