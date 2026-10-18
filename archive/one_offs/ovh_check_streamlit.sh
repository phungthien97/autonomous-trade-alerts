#!/bin/bash
set -euo pipefail
systemctl is-active streamlit-dashboard.service
systemctl status streamlit-dashboard.service --no-pager -l | head -30
ss -ltn | grep 8501 || echo "port 8501 not listening"
sleep 2
curl -s -o /dev/null -w "http=%{http_code}\n" http://127.0.0.1:8501/ || true
journalctl -u streamlit-dashboard.service -n 40 --no-pager
