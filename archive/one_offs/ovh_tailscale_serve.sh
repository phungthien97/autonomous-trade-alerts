#!/bin/bash
set -euo pipefail
# Serve local Streamlit (127.0.0.1:8501) over Tailscale HTTPS
sudo systemctl is-active streamlit-dashboard.service
# Clear any previous serve config, then publish 8501
sudo tailscale serve reset 2>/dev/null || true
sudo tailscale serve --bg 8501
echo "=== serve status ==="
sudo tailscale serve status
echo "=== funnels/status ==="
tailscale status | head -10
IP=$(tailscale ip -4)
echo "VPS_TAILSCALE_IP=$IP"
echo "Try: https://$(tailscale status --json 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || echo "$IP")"
