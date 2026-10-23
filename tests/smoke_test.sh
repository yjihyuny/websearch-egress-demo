#!/usr/bin/env bash
# Smoke test of the whole demo against a live sandbox. Read-only for policy; runs two agent prompts.
#   SANDBOX=egress-demo bash tests/smoke_test.sh
set -u
SB="${SANDBOX:-egress-demo}"; PORT="${PORT:-8899}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
pass=0; fail=0
ok()  { echo "  [pass] $*"; pass=$((pass+1)); }
bad() { echo "  [FAIL] $*"; fail=$((fail+1)); }
SANDBOX="$SB" PORT="$PORT" python3 "$HERE/server/live_server.py" >/tmp/egress-smoke.log 2>&1 & SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
for i in $(seq 1 20); do curl -sf -m2 "127.0.0.1:$PORT/api/health" >/dev/null && break; sleep 0.5; done
curl -sf "127.0.0.1:$PORT/api/health" | grep -q "\"$SB\"" && ok "server up, sandbox $SB" || bad "server health"
curl -sf "127.0.0.1:$PORT/api/samples" | python3 -c "import sys,json;d=json.load(sys.stdin);sys.exit(0 if len(d)>=15 else 1)" && ok "samples served" || bad "samples"
for p in langgraph_viewer.html demo_console.html visual_guide.html policy_tools.js; do curl -sf -o /dev/null "127.0.0.1:$PORT/$p" && ok "serves $p" || bad "serves $p"; done
curl -sf "127.0.0.1:$PORT/api/policy?sandbox=$SB" | python3 -c "import sys,json;d=json.load(sys.stdin);sys.exit(0 if 'network_policies' in d.get('yaml','') else 1)" && ok "live policy readable" || bad "policy read"
run() { curl -sf -m260 -X POST "127.0.0.1:$PORT/api/run" -H 'content-type: application/json' -d "$1"; }
r=$(run '{"prompt":"Use write_file to write hello to /etc/agent-note.txt. Report the exact result.","graph":"react"}') \
  && echo "$r" | python3 -c "import sys,json;d=json.load(sys.stdin);ev=d['trace']['events'];print('   steps',len(ev),'inference calls',d['inference_calls']);sys.exit(0 if any(e['kind']=='tool_result' and 'ERROR' in e['content'] for e in ev) else 1)" \
  && ok "agent run: /etc write refused by sandbox" || bad "agent run (file deny)"
r=$(run '{"prompt":"Use http_get on https://example.com and tell me the page title. If it fails, say exactly what error you got.","graph":"react"}') \
  && echo "$r" | python3 -c "import sys,json;d=json.load(sys.stdin);print('   network events',[(e['verdict'],e['text'][:60]) for e in d['events']][:3]);sys.exit(0)" \
  && ok "agent run: example.com attempt traced" || bad "agent run (network)"
echo "$pass passed, $fail failed"; [ "$fail" = 0 ]
