#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

declare -A INITIAL_ENV=()
while IFS= read -r -d '' line; do
  name="${line%%=*}"
  value="${line#*=}"
  if [[ -n "${value}" ]]; then
    INITIAL_ENV["${name}"]="${value}"
  fi
done < <(env -0)

load_env_file() {
  local env_file="$1"
  if [[ ! -f "${env_file}" ]]; then
    return 0
  fi

  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a

  for name in "${!INITIAL_ENV[@]}"; do
    printf -v "${name}" '%s' "${INITIAL_ENV[${name}]}"
    export "${name}"
  done
}

if ! command -v hivemind >/dev/null 2>&1; then
  echo "hivemind is required to run the unified dev server." >&2
  echo "Install it first: https://github.com/DarthSim/hivemind" >&2
  exit 127
fi

load_env_file "${REPO_ROOT}/.env"
load_env_file "${REPO_ROOT}/.env.local"

: "${DEV_MODE:=local}"
: "${API_PORT:=8000}"
: "${WEB_PORT:=4200}"
: "${RUNTIME_PORT:=9000}"
: "${RUNTIME_ROOT:=${REPO_ROOT}/.runtime/dev}"
: "${WORKFLOW_TEMPLATE_PATH:=${REPO_ROOT}/examples/WORKFLOW.dev.md}"

case "${DEV_MODE}" in
  local)
    : "${API_HOST:=127.0.0.1}"
    : "${WEB_HOST:=127.0.0.1}"
    : "${RUNTIME_HOST:=127.0.0.1}"
    : "${DJANGO_ALLOWED_HOSTS:=127.0.0.1,localhost}"
    ;;
  lan)
    : "${API_HOST:=0.0.0.0}"
    : "${WEB_HOST:=0.0.0.0}"
    : "${RUNTIME_HOST:=0.0.0.0}"
    : "${DJANGO_ALLOWED_HOSTS:=*}"
    ;;
  *)
    echo "Unsupported DEV_MODE: ${DEV_MODE}. Expected 'local' or 'lan'." >&2
    exit 2
    ;;
esac

if [[ ! -f "${WORKFLOW_TEMPLATE_PATH}" ]]; then
  echo "Workflow template not found: ${WORKFLOW_TEMPLATE_PATH}" >&2
  exit 2
fi

mkdir -p "${RUNTIME_ROOT}"
cp "${WORKFLOW_TEMPLATE_PATH}" "${RUNTIME_ROOT}/WORKFLOW.md"

: "${API_PROXY_TARGET:=http://127.0.0.1:${API_PORT}}"
: "${SYMPHONY_WORKFLOW_PATH:=${RUNTIME_ROOT}/WORKFLOW.md}"
: "${SYMPHONY_RUNTIME_SNAPSHOT_PATH:=${RUNTIME_ROOT}/snapshot.json}"
: "${SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH:=${RUNTIME_ROOT}/refresh-request.json}"
: "${SYMPHONY_RUNTIME_RECOVERY_PATH:=${RUNTIME_ROOT}/recovery.json}"

export DEV_MODE
export API_HOST API_PORT
export WEB_HOST WEB_PORT
export RUNTIME_HOST RUNTIME_PORT
export RUNTIME_ROOT WORKFLOW_TEMPLATE_PATH
export API_PROXY_TARGET
export DJANGO_ALLOWED_HOSTS
export SYMPHONY_WORKFLOW_PATH
export SYMPHONY_RUNTIME_SNAPSHOT_PATH
export SYMPHONY_RUNTIME_REFRESH_REQUEST_PATH
export SYMPHONY_RUNTIME_RECOVERY_PATH

cd "${REPO_ROOT}"
exec hivemind Procfile.dev
