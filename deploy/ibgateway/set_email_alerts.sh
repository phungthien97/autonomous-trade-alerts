#!/bin/bash
set -euo pipefail
ENV=/opt/autonomous-trade-alerts/.env
echo
echo "Set Gmail alerts for the live/paper bot (values stay on the VPS only)."
echo "You need a Google App Password (not your normal Gmail password):"
echo "  https://myaccount.google.com/apppasswords"
echo
read -r -p "Gmail address (from): " GUSER
read -r -s -p "Gmail App Password (16 chars): " GPASS
echo
read -r -p "Alert recipient email (to): " GTO
if [ -z "$GUSER" ] || [ -z "$GPASS" ] || [ -z "$GTO" ]; then
  echo "A field was empty. Nothing saved."
  exit 1
fi
# strip spaces from app password
GPASS=$(echo "$GPASS" | tr -d ' ')

python3 - "$ENV" "$GUSER" "$GPASS" "$GTO" <<'PY'
from pathlib import Path
import sys
path, user, pw, to = Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4]
needed = {
    "GMAIL_USER": user,
    "GMAIL_APP_PASSWORD": pw,
    "ALERT_TO_EMAIL": to,
}
lines = path.read_text().splitlines() if path.exists() else []
keys = set()
out = []
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0]
        if k in needed:
            out.append(f"{k}={needed[k]}")
            keys.add(k)
        else:
            out.append(line)
    else:
        out.append(line)
for k, v in needed.items():
    if k not in keys:
        out.append(f"{k}={v}")
path.write_text("\n".join(out) + "\n")
path.chmod(0o600)
print("Saved to", path)
PY

cd /opt/autonomous-trade-alerts
set -a
# shellcheck disable=SC1091
source .env
set +a
. .venv/bin/activate
python - <<'PY'
from app.notifier import send_signal_email
ok = send_signal_email(
    "Trade bot email test",
    "If you got this, OVH paper-bot alerts are configured.\nYou will get fills, rejects, disconnects, risk stops, weekly 2FA, and Gateway health checks.",
)
print("TEST_EMAIL_SENT" if ok else "TEST_EMAIL_FAILED")
raise SystemExit(0 if ok else 1)
PY
echo
echo "Done. Check your inbox (and spam)."
