#!/usr/bin/env bash
# Bring up the entire Distributed Intelligent Campus IoT stack in one shot:
#   HiveMQ broker, ThingsBoard, sim-engine, and all 10 Node-RED floor gateways.
#
# Usage:
#   ./scripts/run_all.sh           # build (if needed) + up + tail logs
#   ./scripts/run_all.sh down      # stop and remove containers
#   ./scripts/run_all.sh restart   # down then up
#   ./scripts/run_all.sh status    # show service status
#   ./scripts/run_all.sh logs      # tail logs of running stack

set -euo pipefail

# Resolve repo root from this script's location so it works from any CWD.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# Pick `docker compose` (v2) or fall back to `docker-compose` (v1).
if docker compose version >/dev/null 2>&1; then
  DC=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DC=(docker-compose)
else
  echo "ERROR: docker compose is not installed. Install Docker Desktop or the compose plugin." >&2
  exit 1
fi

if [[ ! -f .env ]]; then
  echo "ERROR: .env not found in $REPO_ROOT. Copy .env.example to .env and fill in secrets." >&2
  exit 1
fi

cmd="${1:-up}"

case "$cmd" in
  up)
    echo ">> Building images (if needed) and starting full stack..."
    "${DC[@]}" up -d --build
    echo ""
    echo ">> Services:"
    "${DC[@]}" ps
    echo ""
    echo ">> Endpoints:"
    echo "   HiveMQ MQTT       : tcp://localhost:1883  (TLS 8883)"
    echo "   HiveMQ UI         : http://localhost:8080"
    echo "   ThingsBoard UI    : http://localhost:9090"
    echo ""
    echo ">> Tailing logs (Ctrl+C to stop tail; containers keep running)."
    "${DC[@]}" logs -f --tail=50
    ;;
  down)
    echo ">> Stopping stack..."
    "${DC[@]}" down
    ;;
  restart)
    "${DC[@]}" down
    exec "$0" up
    ;;
  status|ps)
    "${DC[@]}" ps
    ;;
  logs)
    "${DC[@]}" logs -f --tail=100
    ;;
  *)
    echo "Usage: $0 [up|down|restart|status|logs]" >&2
    exit 2
    ;;
esac
