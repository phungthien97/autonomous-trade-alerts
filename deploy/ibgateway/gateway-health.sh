#!/bin/bash
# Gateway health: port + real API liveness. Auto-restarts unhealthy Gateway.
# Covers: zombie (port up, API dead) AND stuck login after failed nightly
# token AutoRestart (port down, Java still holding the error dialog).
# Detects IB Key / bad-login in recent IBC logs.
set -euo pipefail

LOG=/home/ubuntu/ibc/logs/gateway-health.log
RESTART_STAMP=/home/ubuntu/ibc/logs/gateway-health.last-restart
IBC_LOG_DIR=/home/ubuntu/ibc/logs
APP=/opt/autonomous-trade-alerts
# Avoid hammering IBKR if the paper password is actually wrong.
# Full cooldown only after a *successful* password-path recovery.
# Failed restarts (still zombie) use a short retry so we are not stuck for hours.
RESTART_COOLDOWN_SECS=21600  # 6 hours after successful restart
RESTART_RETRY_SECS=1800      # 30 minutes after a failed restart attempt
RESTART_RESULT=/home/ubuntu/ibc/logs/gateway-health.last-restart-ok
STAMP=$(TZ=America/Toronto date +"%Y-%m-%d %I:%M:%S %p %Z")
mkdir -p "$(dirname "$LOG")"

port_ok=0
java_ok=0
unit_ok=0
api_ok=0
ss -ltn | grep -q ':4002' && port_ok=1
pgrep -c java >/dev/null && java_ok=1
systemctl is-active --quiet ibgateway.service && unit_ok=1

probe_api() {
  local client_id="$1"
  local timeout_s="$2"
  (
    cd "$APP"
    # shellcheck disable=SC1091
    . .venv/bin/activate
    CLIENT_ID="$client_id" TIMEOUT_S="$timeout_s" python - <<'PY'
import asyncio
import os
import sys
asyncio.set_event_loop(asyncio.new_event_loop())
from ib_insync import IB
ib = IB()
try:
    ib.connect(
        "127.0.0.1",
        4002,
        clientId=int(os.environ["CLIENT_ID"]),
        timeout=int(os.environ["TIMEOUT_S"]),
    )
    ok = bool(ib.managedAccounts())
    ib.disconnect()
    sys.exit(0 if ok else 1)
except Exception:
    sys.exit(1)
PY
  )
}

# Real API probe — port can be up while Gateway is a zombie (connect hangs).
if [ "$port_ok" -eq 1 ] && [ -x "$APP/.venv/bin/python" ]; then
  if probe_api 66 10; then
    api_ok=1
  fi
fi

can_restart=0
cooldown_needed=$RESTART_COOLDOWN_SECS
if [ -f "$RESTART_STAMP" ]; then
  last=$(cat "$RESTART_STAMP" 2>/dev/null || echo 0)
  now=$(date +%s)
  last_ok=$(cat "$RESTART_RESULT" 2>/dev/null || echo 0)
  # If the last attempt did not leave API healthy, allow a sooner retry.
  if [ "$last_ok" != "1" ]; then
    cooldown_needed=$RESTART_RETRY_SECS
  fi
  if [ $((now - last)) -ge "$cooldown_needed" ]; then
    can_restart=1
  fi
else
  can_restart=1
fi

# Unhealthy: unit up but API dead — zombie OR port-down after failed token AutoRestart.
# Full systemd restart uses saved paper username/password (not the nightly token).
restarted=0
restart_skipped_cooldown=0
if [ "$api_ok" -eq 0 ] && [ "$unit_ok" -eq 1 ]; then
  if [ "$can_restart" -eq 1 ]; then
    reason="port_down"
    if [ "$port_ok" -eq 1 ]; then
      reason="zombie_gateway"
    fi
    echo "$STAMP $reason detected; restarting ibgateway (password-path login)" | tee -a "$LOG"
    sudo systemctl stop live-worker.timer || true
    sudo systemctl restart ibgateway.service || true
    date +%s >"$RESTART_STAMP"
    echo 0 >"$RESTART_RESULT"
    restarted=1
    sleep 50
    port_ok=0
    api_ok=0
    java_ok=0
    pgrep -c java >/dev/null && java_ok=1
    ss -ltn | grep -q ':4002' && port_ok=1
    if [ "$port_ok" -eq 1 ] && [ -x "$APP/.venv/bin/python" ]; then
      if probe_api 67 15; then
        api_ok=1
        echo 1 >"$RESTART_RESULT"
        sudo systemctl start live-worker.timer || true
      fi
    fi
  else
    restart_skipped_cooldown=1
    echo "$STAMP unhealthy but restart skipped (cooldown ${cooldown_needed}s)" | tee -a "$LOG"
  fi
fi

status="FAIL"
if [ "$port_ok" -eq 1 ] && [ "$java_ok" -eq 1 ] && [ "$unit_ok" -eq 1 ] && [ "$api_ok" -eq 1 ]; then
  status="OK"
fi

twofa_hit=0
bad_login=0
if ls "$IBC_LOG_DIR"/ibc-*.txt >/dev/null 2>&1; then
  if find "$IBC_LOG_DIR" -maxdepth 1 -name 'ibc-*.txt' -mmin -180 -print0 \
    | xargs -0 -r grep -Eiq \
      'Second Factor|second factor|Awaiting .*authentication|IB Key|two.?factor|2FA|authentication code'; then
    twofa_hit=1
  fi
  # Only flag bad login from very recent logs AND when API is down (avoid stale dialogs).
  if [ "$api_ok" -eq 0 ] && find "$IBC_LOG_DIR" -maxdepth 1 -name 'ibc-*.txt' -mmin -30 -print0 \
    | xargs -0 -r grep -Eiq \
      'Unrecognized Username or Password|Login failed|Invalid username|Invalid password'; then
    bad_login=1
  fi
fi

# Pause worker when Gateway is unhealthy; resume when healthy again.
# Covers recovery outside this run (IB Key approve, later AutoRestart, manual fix).
if [ "$status" != "OK" ]; then
  if systemctl is-active --quiet live-worker.timer 2>/dev/null; then
    sudo systemctl stop live-worker.timer || true
    echo "$STAMP stopped live-worker.timer (status=$status api_ok=$api_ok bad_login=$bad_login)" | tee -a "$LOG"
  fi
elif ! systemctl is-active --quiet live-worker.timer 2>/dev/null; then
  sudo systemctl start live-worker.timer || true
  echo "$STAMP started live-worker.timer (gateway healthy)" | tee -a "$LOG"
fi

line="$STAMP status=$status port4002=$port_ok api_ok=$api_ok java=$java_ok ibgateway_unit=$unit_ok restarted=$restarted restart_skipped_cooldown=$restart_skipped_cooldown twofa_suspect=$twofa_hit bad_login=$bad_login"
echo "$line" | tee -a "$LOG"

cd "$APP"
set -a
# shellcheck disable=SC1091
source .env 2>/dev/null || true
set +a
if [ -n "${GMAIL_USER:-}" ] && [ -n "${GMAIL_APP_PASSWORD:-}" ] && [ -n "${ALERT_TO_EMAIL:-}" ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
  export HEALTH_LINE="$line"
  export HEALTH_STATUS="$status"
  export TWOFA_HIT="$twofa_hit"
  export BAD_LOGIN="$bad_login"
  export RESTARTED="$restarted"
  python - <<'PY'
import os
from app.notifier import notify_live_event, notify_weekly_2fa_required, send_signal_email

status = os.environ["HEALTH_STATUS"]
line = os.environ["HEALTH_LINE"]
twofa = os.environ.get("TWOFA_HIT") == "1"
bad_login = os.environ.get("BAD_LOGIN") == "1"
restarted = os.environ.get("RESTARTED") == "1"

if status == "OK" and restarted:
    print(
        "recovery_email_sent"
        if send_signal_email("Gateway recovered after restart", line + "\n")
        else "recovery_email_skipped"
    )
elif status != "OK" and bad_login:
    # Only ask for credential update after auto-restart already tried the password path.
    body = (
        line
        + "\n\nIBKR rejected paper login (Unrecognized Username or Password).\n"
    )
    if restarted:
        body += "Automatic ibgateway restart (password-path) was attempted and still failed.\n"
    body += (
        "Update credentials, then restart Gateway:\n"
        + "  ~/set_ib_paper_login.sh\n"
        + "  sudo systemctl restart ibgateway.service\n"
        + "  ss -ltn | grep 4002\n"
        + "  sudo systemctl start live-worker.timer\n"
    )
    print("bad_login_email_sent" if notify_live_event("disconnect", body) else "bad_login_email_skipped")
elif twofa:
    body = (
        line
        + "\n\nIBKR may be waiting for IB Key / second-factor approval.\n"
        + "Open IBKR Mobile → approve login, then wait 1–2 minutes.\n"
    )
    print("twofa_email_sent" if notify_weekly_2fa_required(body) else "twofa_email_skipped")
elif status != "OK":
    body = line + "\n\nGateway API unhealthy.\n"
    if restarted:
        body += "Attempted automatic ibgateway restart (password-path login).\n"
    body += "If still down: sudo systemctl restart ibgateway.service\n"
    print("email_sent" if notify_live_event("disconnect", body) else "email_skipped")
elif status == "OK" and not twofa and not bad_login:
    # Quiet OK checks — no daily spam; log line already written.
    print("health_ok_quiet")
PY
fi

if [ "$status" != "OK" ]; then
  exit 1
fi
