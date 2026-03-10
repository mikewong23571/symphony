#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"

WEB_HOST="${WEB_HOST:-127.0.0.1}"
WEB_PORT="${WEB_PORT:-4200}"
API_PROXY_TARGET="${API_PROXY_TARGET:-http://127.0.0.1:8000}"
PROXY_CONFIG_DIR="${REPO_ROOT}/.tmp"
PROXY_CONFIG_PATH="${PROXY_CONFIG_DIR}/proxy.conf.json"

mkdir -p "${PROXY_CONFIG_DIR}"
cat > "${PROXY_CONFIG_PATH}" <<EOF
{
  "/api": {
    "target": "${API_PROXY_TARGET}",
    "secure": false,
    "changeOrigin": true
  }
}
EOF

cd "${REPO_ROOT}"
exec pnpm --dir apps/web exec ng serve --host "${WEB_HOST}" --port "${WEB_PORT}" --proxy-config "${PROXY_CONFIG_PATH}"
