#!/usr/bin/env bash
set -euo pipefail

HOST="${TRADER_WEB_HOST:-127.0.0.1}"
PORT="${TRADER_WEB_PORT:-5000}"
BASE_URL="http://${HOST}:${PORT}"

fetch() {
  local path="$1"
  local response
  echo "== ${path} =="
  if ! response="$(curl -fsS "${BASE_URL}${path}")"; then
    echo "request_failed: ${BASE_URL}${path}"
    return 1
  fi
  printf '%s\n' "$response" | python -m json.tool
  echo
}

fetch "/api/system/workers"
fetch "/api/system/review"
fetch "/api/system/replay"
fetch "/api/system/snapshots?limit=5"
