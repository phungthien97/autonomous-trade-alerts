#!/bin/bash
set -euo pipefail
if command -v tailscale >/dev/null 2>&1; then
  echo "tailscale already installed: $(tailscale version | head -1)"
else
  curl -fsSL https://tailscale.com/install.sh | sh
fi
sudo systemctl enable --now tailscaled
# Start auth if not already logged in (prints URL)
status=$(tailscale status --json 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('BackendState',''))" 2>/dev/null || echo unknown)
echo "backend_state=$status"
if [ "$status" != "Running" ]; then
  echo "=== AUTH REQUIRED: open the URL below, log in, approve this device ==="
  sudo tailscale up --ssh=false --accept-dns=true 2>&1 || true
else
  echo "already running"
  tailscale status
  tailscale ip -4
fi
