#!/usr/bin/env bash
# Preflight for the NemoClaw/OpenShell walkthrough. Strictly read-only.
# NOTE: deliberately avoids `nemoclaw <name> status`, which prunes stale local registry entries.
set -u
ok()   { printf '  [ok]   %s\n' "$*"; }
warn() { printf '  [warn] %s\n' "$*"; }
need() { command -v "$1" >/dev/null 2>&1 && ok "$1: $("$1" --version 2>&1 | head -1)" || warn "$1 not found"; }

echo "== Platform"; uname -srm; grep PRETTY_NAME /etc/os-release 2>/dev/null
echo "== Tools"; for t in node npm python3 docker nemoclaw openshell; do need "$t"; done
if command -v node >/dev/null; then
  node -e 'const [a,b]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&b>=16)?0:1)' \
    && ok "node >= 22.16" || warn "node < 22.16 (playbook requirement) [verify]"
fi
echo "== Docker"; docker info >/dev/null 2>&1 && ok "docker daemon reachable" || warn "docker not usable by this user"
echo "== GPU"; nvidia-smi --query-gpu=name,driver_version --format=csv,noheader 2>/dev/null || warn "no nvidia-smi (CPU-only is possible)"
echo "== Memory/disk"; free -g | awk 'NR==2{print "  RAM total/avail GB: "$2"/"$7}'; df -h / | awk 'NR==2{print "  / free: "$4}'
echo "== OpenShell gateway"; openshell status 2>&1 | sed 's/\x1b\[[0-9;]*m//g' | sed -n 1,12p
echo "== Sandboxes (live)"; openshell sandbox list 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
echo "== Policy presets known to nemoclaw (needs a sandbox name as \$1)"
[ -n "${1:-}" ] && nemoclaw "$1" policy-list 2>&1 || echo "  (pass a sandbox name to list)"
