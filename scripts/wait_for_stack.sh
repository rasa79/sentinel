#!/usr/bin/env bash
# Wait for the Sentinel demo-stack infrastructure to be ready.
# Usage: bash scripts/wait_for_stack.sh [compose-file]
# Env overrides: SERVICES (space-separated), WAIT_TIMEOUT (seconds), WAIT_INTERVAL (seconds).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${1:-deploy/docker-compose.yaml}"
SERVICES="${SERVICES:-postgres prometheus loki}"
TIMEOUT="${WAIT_TIMEOUT:-180}"
INTERVAL="${WAIT_INTERVAL:-3}"

now() { date +%s; }
start="$(now)"

for svc in ${SERVICES}; do
  echo "waiting for '${svc}' ..."
  while :; do
    cid="$(docker compose -f "${COMPOSE_FILE}" ps -q "${svc}" 2>/dev/null | head -n1 || true)"
    if [ -z "${cid}" ]; then
      if [ $(( $(now) - start )) -ge "${TIMEOUT}" ]; then
        echo "TIMEOUT: '${svc}' container was never created (after ${TIMEOUT}s)" >&2
        exit 1
      fi
      sleep "${INTERVAL}"
      continue
    fi

    state="$(docker inspect -f '{{.State.Status}}' "${cid}" 2>/dev/null || echo unknown)"
    health="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${cid}" 2>/dev/null || echo none)"
    if [ "${state}" = "running" ] && { [ "${health}" = "healthy" ] || [ "${health}" = "none" ]; }; then
      echo "  '${svc}' is up (state=${state}, health=${health})"
      break
    fi
    if [ $(( $(now) - start )) -ge "${TIMEOUT}" ]; then
      echo "TIMEOUT: '${svc}' not ready (state=${state}, health=${health}) after ${TIMEOUT}s" >&2
      exit 1
    fi
    sleep "${INTERVAL}"
  done
done

echo "All infra services are up."

# Wait for the Sentinel API (Phase 5) and the toy service endpoints (Phase 1).
API_URL="${API_URL:-http://localhost:8000}"
SERVICE_BASE="${SERVICE_BASE:-http://localhost}"
SERVICE_PORTS="${SERVICE_PORTS:-9001 9002 9003}"

echo "waiting for the Sentinel API at ${API_URL} ..."
api_deadline=$(( $(now) + ${TIMEOUT} ))
until curl -fsS "${API_URL}/health" >/dev/null 2>&1; do
  if [ $(( $(now) )) -ge "${api_deadline}" ]; then
    echo "TIMEOUT: API at ${API_URL} did not become healthy" >&2
    exit 1
  fi
  sleep "${INTERVAL}"
done
echo "  Sentinel API is up."

echo "waiting for toy services ..."
svc_deadline=$(( $(now) + ${TIMEOUT} ))
until curl -fsS "${SERVICE_BASE}:${SERVICE_PORTS%% *}/chaos/status" >/dev/null 2>&1; do
  if [ $(( $(now) )) -ge "${svc_deadline}" ]; then
    echo "TIMEOUT: toy services at ${SERVICE_BASE} (${SERVICE_PORTS}) did not become ready" >&2
    exit 1
  fi
  sleep "${INTERVAL}"
done
echo "  toy services are up."

echo "All infra, services, and the API are up."

