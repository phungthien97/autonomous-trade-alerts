#!/bin/bash
set -u
echo "=== status ==="
tailscale status 2>&1 | head -30 || true
echo "=== ip ==="
tailscale ip -4 2>&1 || true
echo "=== backend ==="
sudo tailscale status --json 2>/dev/null | python3 - <<'PY'
import json,sys
d=json.load(sys.stdin)
print("BackendState", d.get("BackendState"))
print("AuthURL", d.get("AuthURL") or "")
print("Self", (d.get("Self") or {}).get("DNSName"), (d.get("Self") or {}).get("TailscaleIPs"))
PY
