#!/bin/bash
set -euo pipefail
cp /tmp/notifier.py /opt/autonomous-trade-alerts/app/notifier.py
sed -i 's/\r$//' /tmp/gateway-health.sh
sudo cp /tmp/gateway-health.sh /home/ubuntu/ibc/gateway-health.sh
sudo chown ubuntu:ubuntu /home/ubuntu/ibc/gateway-health.sh
chmod +x /home/ubuntu/ibc/gateway-health.sh
cd /opt/autonomous-trade-alerts
set -a
# shellcheck disable=SC1091
source .env
set +a
. .venv/bin/activate
python <<'PY'
from app.notifier import format_eastern_now, send_signal_email
print("eastern_now", format_eastern_now())
ok = send_signal_email(
    "Trade bot time format check",
    "All alert times should show Eastern (EST/EDT), not Zulu.",
)
print("sent", ok)
PY
