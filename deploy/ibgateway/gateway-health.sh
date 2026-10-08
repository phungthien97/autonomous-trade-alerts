#!/bin/bash
# Post nightly Auto-Restart + morning health check for IB Gateway.
# Also detects weekly IB Key / 2FA wait in recent IBC logs (R5).
set -euo pipefail

LOG=/home/ubuntu/ibc/logs/gateway-health.log
IBC_LOG_DIR=/home/ubuntu/ibc/logs
# Eastern wall clock for emails/logs (EST/EDT) — not Zulu
STAMP=$(TZ=America/Toronto date +"%Y-%m-%d %I:%M:%S %p %Z")
mkdir -p "$(dirname "$LOG")"

port_ok=0
java_ok=0
unit_ok=0
ss -ltn | grep -q ':4002' && port_ok=1
pgrep -c java >/dev/null && java_ok=1
systemctl is-active --quiet ibgateway.service && unit_ok=1

status="FAIL"
if [ "$port_ok" -eq 1 ] && [ "$java_ok" -eq 1 ] && [ "$unit_ok" -eq 1 ]; then
  status="OK"
fi

# Recent IBC log lines suggesting IB Key / second-factor wait
twofa_hit=0
if ls "$IBC_LOG_DIR"/ibc-*.txt >/dev/null 2>&1; then
  if find "$IBC_LOG_DIR" -maxdepth 1 -name 'ibc-*.txt' -mmin -180 -print0 \
    | xargs -0 -r grep -Eiq \
      'Second Factor|second factor|Awaiting .*authentication|IB Key|two.?factor|2FA|authentication code'; then
    twofa_hit=1
  fi
fi

line="$STAMP status=$status port4002=$port_ok java=$java_ok ibgateway_unit=$unit_ok twofa_suspect=$twofa_hit"
echo "$line" | tee -a "$LOG"

# Email via bot notifier if .env is configured
cd /opt/autonomous-trade-alerts
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
if [ -n "${GMAIL_USER:-}" ] && [ -n "${GMAIL_APP_PASSWORD:-}" ] && [ -n "${ALERT_TO_EMAIL:-}" ]; then
  . .venv/bin/activate
  export HEALTH_LINE="$line"
  export HEALTH_STATUS="$status"
  export TWOFA_HIT="$twofa_hit"
  python - <<'PY'
import os
from app.notifier import notify_weekly_2fa_required, send_signal_email

status = os.environ["HEALTH_STATUS"]
line = os.environ["HEALTH_LINE"]
twofa = os.environ.get("TWOFA_HIT") == "1"

if twofa:
    body = (
        line
        + "\n\nIBKR may be waiting for IB Key / second-factor approval.\n"
        + "Open IBKR Mobile → approve login, then wait 1–2 minutes.\n"
        + "IBC ReloginAfterSecondFactorAuthenticationTimeout=yes; "
        + "TWOFA_TIMEOUT_ACTION=restart.\n"
    )
    print("twofa_email_sent" if notify_weekly_2fa_required(body) else "twofa_email_skipped")

subject = f"Gateway health {status}" if status == "OK" else f"ALERT: Gateway health {status}"
body = line + "\n"
if status != "OK":
    body += (
        "\nGateway API is down. Worker cycles will fail until ibgateway is back.\n"
        "Try: sudo systemctl restart ibgateway.service\n"
        "If IB Key is required, approve in IBKR Mobile, then wait 1-2 minutes.\n"
    )
    print("email_sent" if send_signal_email(subject, body) else "email_skipped")
elif not twofa:
    print("email_sent" if send_signal_email(subject, body) else "email_skipped")
PY
fi

if [ "$status" != "OK" ]; then
  exit 1
fi
