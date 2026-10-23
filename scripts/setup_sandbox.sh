#!/usr/bin/env bash
# One-time (idempotent) prep of an EXISTING OpenShell sandbox for the web-search egress demo:
# installs langgraph + langchain-openai inside it and uploads the agent. Needs outbound pypi from the sandbox
# (the default 'pypi' policy preset allows python3/pip -> pypi.org, files.pythonhosted.org).
#   SANDBOX=egress-demo bash scripts/setup_sandbox.sh
set -euo pipefail
SB="${SANDBOX:-egress-demo}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
strip() { sed 's/\x1b\[[0-9;]*m//g'; }
sx() { timeout "${T:-120}" openshell sandbox exec -n "$SB" -- "$@"; }       # program + args, not a shell string
retry() { for i in 1 2 3; do "$@" && return 0; echo "  (retry $i: sandbox exec sometimes stalls before starting)" >&2; sleep 2; done; return 1; }

echo "== sandbox '$SB' state"
openshell sandbox list 2>&1 | strip | grep -E "NAME|$SB" || { echo "sandbox '$SB' not found: run scripts/onboard.sh first (or set SANDBOX=<name>)"; exit 1; }
openshell sandbox list 2>&1 | strip | grep "$SB" | grep -q Ready || { echo "sandbox '$SB' is not Ready"; exit 1; }

echo "== install python deps inside the sandbox (/sandbox/lg)"
retry env T=600 openshell sandbox exec -n "$SB" -- sh -c 'python3 -m pip install -q --target /sandbox/lg langgraph langchain-openai' 2>&1 | tail -3

echo "== upload agent code"
openshell sandbox upload "$SB" "$HERE/agent/langgraph_demo.py" /sandbox/ 2>&1 | strip | tail -1
openshell sandbox upload "$SB" "$HERE/agent/tool_debug.py" /sandbox/ 2>&1 | strip | tail -1

echo "== check imports and the model route"
retry sx sh -c 'cd /sandbox && python3 -c "import sys; sys.path.insert(0,\"/sandbox/lg\"); import langgraph, langchain_openai; print(\"imports ok\")"'
retry sx sh -c 'curl -sS -m20 https://inference.local/v1/models | head -c 200; echo' || echo "  inference.local not answering: see docs/SETUP_E2E.md section 4"
echo "done. Start the demo UI:  bash scripts/run.sh"
