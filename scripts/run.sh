#!/usr/bin/env bash
# Start the live demo server (serves web/ and runs prompts inside the sandbox). 127.0.0.1 only.
#   SANDBOX=egress-demo PORT=8890 bash scripts/run.sh
SB="${SANDBOX:-egress-demo}"; PORT="${PORT:-8890}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python3 -c "import yaml" 2>/dev/null || { echo "PyYAML missing (needed by the Policy editor's 'set YAML'): pip install -r $HERE/server/requirements.txt"; }
if ! openshell sandbox list 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g' | awk 'NR>1{print $1}' | grep -qx "$SB"; then
  echo "sandbox '$SB' not found. Existing sandboxes:"; openshell sandbox list 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
  echo "Re-run with SANDBOX=<name> bash scripts/run.sh"; exit 1
fi
if ss -ltn 2>/dev/null | grep -q ":${PORT} "; then echo "port ${PORT} busy; try PORT=8891 bash scripts/run.sh"; exit 1; fi
echo "Open http://127.0.0.1:${PORT}/langgraph_viewer.html   (remote host: ssh -N -L ${PORT}:127.0.0.1:${PORT} <user>@<host>)"
SANDBOX="$SB" PORT="$PORT" exec python3 "$HERE/server/live_server.py"
