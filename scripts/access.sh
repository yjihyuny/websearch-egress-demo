#!/usr/bin/env bash
# View the demo pages + the OpenClaw dashboard from your laptop through an SSH tunnel.
#
#   On the DEMO HOST (spark-1d3c):   bash access.sh serve        # keeps running; Ctrl+C to stop
#   On your LAPTOP:                  bash access.sh tunnel <user>@<host>
#   (or just copy the printed ssh line)
#
# Local-only binds (127.0.0.1); nothing is exposed to the network.
HTML_PORT="${HTML_PORT:-8890}"      # static files (web/ pages)
DASH_PORT="${DASH_PORT:-18800}"     # OpenClaw dashboard for egress-demo (nemoclaw list shows it)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${1:-help}" in
  serve)
    if ss -ltn | grep -q ":${HTML_PORT} "; then echo "port ${HTML_PORT} busy; try HTML_PORT=8891 bash access.sh serve"; exit 1; fi
    echo "Live server + pages on http://127.0.0.1:${HTML_PORT}/  (Ctrl+C to stop)"
    echo "Dashboard forward on host: $(openshell forward list 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | grep egress-demo || echo 'none: run: openshell forward start '"${DASH_PORT}"' egress-demo --background')"
    # live_server.py serves the pages AND runs prompts in the sandbox (LangGraph viewer). Binds 127.0.0.1 only.
    PORT="${HTML_PORT}" exec python3 "${DIR}/../server/live_server.py"
    ;;
  tunnel)
    target="${2:?usage: bash access.sh tunnel user@host}"
    echo "Opening tunnel (Ctrl+C to close). Then browse:"
    echo "  Viewer:     http://127.0.0.1:${HTML_PORT}/langgraph_viewer.html"
    echo "  Guide:      http://127.0.0.1:${HTML_PORT}/visual_guide.html"
    echo "  Console:    http://127.0.0.1:${HTML_PORT}/demo_console.html"
    echo "  Dashboard:  http://127.0.0.1:${DASH_PORT}/   (needs the gateway token, see 'token' below)"
    exec ssh -N -L "${HTML_PORT}:127.0.0.1:${HTML_PORT}" -L "${DASH_PORT}:127.0.0.1:${DASH_PORT}" "${target}"
    ;;
  token)
    # Prints a secret. Run it yourself, do not paste the output into chats or tickets.
    nemoclaw egress-demo dashboard-url --quiet 2>&1 || echo "no dashboard-url on this version: read the token with:
  openshell sandbox exec -n egress-demo -- sh -c 'printf %s \"\$OPENCLAW_GATEWAY_TOKEN\"'  then open http://127.0.0.1:${DASH_PORT}/#token=<token>"
    ;;
  *)
    sed -n '2,8p' "$0";;
esac
