#!/bin/bash
set -e
CFG=/home/ubuntu/ibc/config.ini
echo
echo "This will set your IBKR PAPER login for the bot."
echo "Do NOT use your live money account here."
echo
read -r -p "Paper username: " USER
read -r -s -p "Paper password: " PASS
echo
if [ -z "$USER" ] || [ -z "$PASS" ]; then
  echo "Username or password was empty. Nothing saved."
  exit 1
fi
python3 - "$CFG" "$USER" "$PASS" <<'PY'
from pathlib import Path
import sys
path, user, pw = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = []
for line in path.read_text().splitlines():
    if line.startswith("IbLoginId="):
        lines.append("IbLoginId=" + user)
    elif line.startswith("IbPassword="):
        lines.append("IbPassword=" + pw)
    else:
        lines.append(line)
path.write_text("\n".join(lines) + "\n")
path.chmod(0o600)
print("Saved.")
for key in ("IbLoginId", "IbPassword"):
    for line in path.read_text().splitlines():
        if line.startswith(key + "="):
            val = line.split("=", 1)[1]
            print(f"{key}: OK (length {len(val)})")
            break
PY
echo
echo "Done. You can close this window (type: exit)."
