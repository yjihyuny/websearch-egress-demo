#!/usr/bin/env bash
# Create the demo sandbox non-interactively against an OpenAI-compatible endpoint (local vLLM/Ollama/NIM, or any /v1 URL).
# This is the exact form that worked on NemoClaw v0.0.55 / OpenShell 0.0.44. For NVIDIA-hosted endpoints use the
# interactive wizard instead:  nemoclaw onboard   (see docs/SETUP_E2E.md section 3).
#
#   ENDPOINT_URL=http://172.20.0.1:8080/v1 MODEL=/models/your-model bash scripts/onboard.sh
# Required: ENDPOINT_URL, MODEL.   Optional: SANDBOX (egress-demo), API_KEY (none), GATEWAY_PORT (18080), CONTROL_UI_PORT (18801, because guide-demo may own 18800)
set -euo pipefail
: "${ENDPOINT_URL:?set ENDPOINT_URL (reachable from the Docker bridge, e.g. http://172.20.0.1:8080/v1)}"
: "${MODEL:?set MODEL (the served model id)}"
SB="${SANDBOX:-egress-demo}"
export PATH="$HOME/.local/bin:$PATH"   # make sure openshell 0.0.44 wins over /usr/bin/openshell 0.0.38
echo "About to create sandbox '$SB'. Onboarding can recreate the OpenShell gateway and restart OTHER sandboxes' containers."
echo "Run 'nemoclaw backup-all' first if other sandboxes matter. Ctrl+C within 10 s to abort."; sleep 10
NEMOCLAW_NON_INTERACTIVE=1 NEMOCLAW_AGENT=openclaw NEMOCLAW_SANDBOX_NAME="$SB" \
NEMOCLAW_PROVIDER=custom NEMOCLAW_ENDPOINT_URL="$ENDPOINT_URL" NEMOCLAW_MODEL="$MODEL" NEMOCLAW_PROVIDER_KEY="${API_KEY:-none}" \
NEMOCLAW_DASHBOARD_PORT="${CONTROL_UI_PORT:-18801}" NEMOCLAW_GATEWAY_PORT="${GATEWAY_PORT:-18080}" NEMOCLAW_POLICY_MODE=suggested \
nemoclaw onboard --fresh --control-ui-port "${CONTROL_UI_PORT:-18801}" --yes-i-accept-third-party-software
echo; openshell sandbox list
