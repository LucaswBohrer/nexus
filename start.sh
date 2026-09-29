#!/bin/sh
# NEXUS launcher — starts the backend API and the frontend dashboard
# together, reachable from this computer AND from phones on the same Wi-Fi.
#
# Usage:
#   ./start.sh
#
# Environment overrides (all optional):
#   NEXUS_HOST          API bind address (default: 0.0.0.0 = LAN-accessible)
#   NEXUS_PORT          API port (default: 8000)
#   FRONTEND_PORT       Dashboard port (default: 3000)
#   NEXUS_CORS_ORIGINS  Comma-separated browser origins allowed to call the
#                       API. When unset, the script allows localhost plus the
#                       detected LAN IP on the dashboard port.
#
# Press Ctrl+C to stop both processes.
set -eu

ROOT="$(cd "$(dirname "$0")" && pwd)"

NEXUS_HOST="${NEXUS_HOST:-0.0.0.0}"
NEXUS_PORT="${NEXUS_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

export NEXUS_HOST NEXUS_PORT

# --- Detect the LAN IP so the dashboard URL can be shown (and the phone
# --- origin allowed by CORS). Never hardcoded: detected at runtime.
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -z "$LAN_IP" ]; then
  LAN_IP="$(ip route get 1.1.1.1 2>/dev/null | awk '/src/ {for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}')"
fi

# --- CORS: explicit allowlist (never "*"). Auto-include the LAN origin
# --- unless the user already configured NEXUS_CORS_ORIGINS.
if [ -z "${NEXUS_CORS_ORIGINS:-}" ]; then
  if [ -n "$LAN_IP" ]; then
    export NEXUS_CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://${LAN_IP}:${FRONTEND_PORT}"
    echo "CORS auto-configured for local + LAN dashboard:"
    echo "  $NEXUS_CORS_ORIGINS"
  else
    export NEXUS_CORS_ORIGINS="http://localhost:${FRONTEND_PORT}"
    echo "Warning: could not detect LAN IP; CORS allows only"
    echo "  $NEXUS_CORS_ORIGINS"
    echo "Set NEXUS_CORS_ORIGINS manually to reach the API from your phone."
  fi
fi

# --- Backend: create venv + install deps on first run, then launch. ---
if [ ! -x "$ROOT/backend/.venv/bin/python" ]; then
  echo "Creating backend virtualenv..."
  python3 -m venv "$ROOT/backend/.venv"
fi
echo "Installing backend dependencies (no-op when up to date)..."
"$ROOT/backend/.venv/bin/pip" install -q -r "$ROOT/backend/requirements.txt"

# --- Frontend: install deps on first run. ---
if [ ! -d "$ROOT/frontend/node_modules" ]; then
  echo "Installing frontend dependencies (first run only)..."
  (cd "$ROOT/frontend" && npm install)
fi

cleanup() {
  echo ""
  echo "Stopping NEXUS..."
  kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup INT TERM

echo "Starting NEXUS backend on ${NEXUS_HOST}:${NEXUS_PORT}..."
(cd "$ROOT/backend" && exec "$ROOT/backend/.venv/bin/python" -m uvicorn app.main:app \
  --host "$NEXUS_HOST" --port "$NEXUS_PORT") &
BACKEND_PID=$!

echo "Starting NEXUS dashboard on 0.0.0.0:${FRONTEND_PORT}..."
(cd "$ROOT/frontend" && exec npx next dev --hostname 0.0.0.0 --port "$FRONTEND_PORT") &
FRONTEND_PID=$!

echo ""
echo "NEXUS is running:"
echo "  Dashboard (this computer): http://localhost:${FRONTEND_PORT}"
if [ -n "$LAN_IP" ]; then
  echo "  Dashboard (phone on same Wi-Fi): http://${LAN_IP}:${FRONTEND_PORT}"
  echo "  API docs: http://${LAN_IP}:${NEXUS_PORT}/docs"
fi
echo ""
echo "Press Ctrl+C to stop."

wait "$BACKEND_PID" "$FRONTEND_PID"
