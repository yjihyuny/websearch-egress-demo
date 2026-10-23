#!/usr/bin/env bash
# Interactive shell-level checks against a sandbox (3 = show policy, 4 = predict then test allow/deny, 5 = secret-looking env vars) (default: egress-demo).
# Usage: bash demo.sh [scene]   scene: 3 | 4 | 5 | all
# Read-only apart from /tmp inside the sandbox. Press Enter before each command.
SB="${SANDBOX:-egress-demo}"
strip() { sed 's/\x1b\[[0-9;]*m//g'; }
step() { # step "title" "command run inside the sandbox"
  printf '\n\033[1m# %s\033[0m\n$ %s\n' "$1" "$2"; read -rp "   [Enter] " _
  timeout 40 openshell sandbox exec -n "$SB" -- sh -c "$2" 2>&1 | strip | head -8; echo "   [exit ${PIPESTATUS[0]}]"
}
scene3() { openshell policy get "$SB" --full 2>&1 | strip | sed -n 1,60p; }
scene4() {
  step "a. open internet (expect DENY)"            'curl -sS -m10 -o /dev/null -w "http=%{http_code}\n" https://example.com'
  step "b. pypi via curl (expect DENY)"            'curl -sS -m10 -o /dev/null -w "http=%{http_code}\n" https://pypi.org/pypi/idna/json'
  step "c. pypi via pip (expect ALLOW)"            'pip download idna -d /tmp/p -q 2>&1 | tail -2; ls /tmp/p'
  step "d. hosted model API via curl (expect DENY)" 'curl -sS -m10 -o /dev/null -w "http=%{http_code}\n" https://integrate.api.nvidia.com/v1/models'
  step "e. write /etc (expect DENY)"               'touch /etc/x'
  step "f. write /tmp (expect ALLOW)"              'touch /tmp/ok && echo tmp-ok'
  step "g. escalate (expect refused)"              'unshare -n true; mount -t tmpfs none /mnt'
  printf '\n\033[1m# audit trail\033[0m\n'; openshell logs "$SB" 2>&1 | strip | grep -E "DENIED|ALLOWED" | tail -10 | cut -c1-220
}
scene5() { step "secret-looking env vars (values redacted)" 'env | grep -iE "key|token|secret" | sed "s/=.*/=<redacted>/"'; }
case "${1:-all}" in
  3) scene3;; 4) scene4;; 5) scene5;; all) scene3; scene4; scene5;;
  *) echo "usage: $0 [3|4|5|all]"; exit 1;;
esac
