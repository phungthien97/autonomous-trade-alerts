#!/bin/bash
# Harden IBC for unattended daily Auto-Restart + restart Gateway via systemd.
set -euo pipefail

CFG=/home/ubuntu/ibc/config.ini
START=/home/ubuntu/ibc/gatewaystart.sh

python3 - "$CFG" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
lines = []
for line in path.read_text().splitlines():
    if line.startswith("AutoRestartTime="):
        # Gateway host timezone is UTC; daily restart ~23:45 UTC (was prior exit window)
        lines.append("AutoRestartTime=11:45 PM")
    elif line.startswith("ClosedownAt="):
        lines.append("ClosedownAt=")
    elif line.startswith("AutoLogoffTime="):
        lines.append("AutoLogoffTime=")
    elif line.startswith("ReloginAfterSecondFactorAuthenticationTimeout="):
        lines.append("ReloginAfterSecondFactorAuthenticationTimeout=yes")
    elif line.startswith("SecondFactorAuthenticationExitInterval="):
        lines.append("SecondFactorAuthenticationExitInterval=120")
    elif line.startswith("ExistingSessionDetectedAction="):
        lines.append("ExistingSessionDetectedAction=primary")
    elif line.startswith("AcceptIncomingConnectionAction="):
        lines.append("AcceptIncomingConnectionAction=accept")
    elif line.startswith("OverrideTwsApiPort="):
        lines.append("OverrideTwsApiPort=4002")
    elif line.startswith("ReadOnlyApi="):
        lines.append("ReadOnlyApi=no")
    elif line.startswith("TradingMode="):
        lines.append("TradingMode=paper")
    elif line.startswith("SaveTwsSettingsAt=") and not line.startswith("SaveTwsSettingsAt=Every"):
        # keep settings so Auto-Restart time persists
        lines.append("SaveTwsSettingsAt=08:00")
    else:
        lines.append(line)
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
print("config.ini hardened")
PY

# TWOFA_TIMEOUT_ACTION=restart so weekly IB Key can retry after approve
python3 - "$START" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
text = path.read_text()
text = text.replace("TWOFA_TIMEOUT_ACTION=exit", "TWOFA_TIMEOUT_ACTION=restart")
if "TWOFA_TIMEOUT_ACTION=restart" not in text:
    raise SystemExit("failed to set TWOFA_TIMEOUT_ACTION")
path.write_text(text)
print("gatewaystart.sh TWOFA_TIMEOUT_ACTION=restart")
PY

# Hand control to systemd (stop timer while Gateway comes up)
sudo systemctl stop live-worker.timer || true
sudo cp /tmp/xvfb.service /tmp/ibgateway.service /tmp/live-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable xvfb.service ibgateway.service

# Prefer systemd stop; fall back to gentle kills of Gateway/Java only
sudo systemctl stop ibgateway.service 2>/dev/null || true
if pgrep -f 'ibcalpha.ibc.IbcGateway' >/dev/null; then
  pgrep -f 'ibcalpha.ibc.IbcGateway' | xargs -r kill || true
  sleep 2
fi
if pgrep -x Xvfb >/dev/null; then
  pgrep -x Xvfb | xargs -r kill || true
  sleep 1
fi

sudo systemctl restart xvfb.service
sleep 1
sudo systemctl restart ibgateway.service

echo "Waiting for Gateway login / port 4002..."
ok=0
for i in $(seq 1 36); do
  sleep 5
  if ss -ltn | grep -q ':4002'; then
    echo "PORT_4002_UP after ${i}x5s"
    ok=1
    break
  fi
  # show brief status
  systemctl is-active ibgateway.service || true
done

systemctl status xvfb.service --no-pager -l | head -15 || true
systemctl status ibgateway.service --no-pager -l | head -25 || true
ss -ltn | grep 4002 || echo NO_4002_YET
pgrep -c java || echo 0_java

# Re-enable worker timer
sudo systemctl enable --now live-worker.timer
systemctl list-timers live-worker.timer --no-pager || true

if [ "$ok" -eq 1 ]; then
  cd /opt/autonomous-trade-alerts
  . .venv/bin/activate
  python - <<'PY'
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from app.broker.ibkr import IbkrBroker
b = IbkrBroker()
print("accounts", b.ib.managedAccounts())
print("snapshot", b.get_account_snapshot())
b.ib.disconnect()
print("SMOKE_OK")
PY
  echo HARDEN_OK
else
  echo HARDEN_WAIT_LOGIN
  echo "Check: journalctl -u ibgateway.service -n 80 --no-pager"
  echo "If IB Key prompt: approve on phone, wait, re-check port 4002"
fi
