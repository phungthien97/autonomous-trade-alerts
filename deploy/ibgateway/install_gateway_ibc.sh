#!/usr/bin/env bash
set -euo pipefail

mkdir -p "$HOME/downloads" "$HOME/ibc" "$HOME/Jts"
cd "$HOME/downloads"

echo "=== Downloading IB Gateway ==="
wget -q -O ibgateway-stable-standalone-linux-x64.sh \
  "https://download2.interactivebrokers.com/installers/ibgateway/stable-standalone/ibgateway-stable-standalone-linux-x64.sh"
chmod +x ibgateway-stable-standalone-linux-x64.sh
ls -lh ibgateway-stable-standalone-linux-x64.sh

echo "=== Installing IB Gateway (silent) ==="
if [[ ! -x "$HOME/Jts/ibgateway/ibgateway" ]] && ! find "$HOME/Jts" -name ibgateway -type f 2>/dev/null | grep -q .; then
  ./ibgateway-stable-standalone-linux-x64.sh -q -dir "$HOME/Jts/ibgateway" || ./ibgateway-stable-standalone-linux-x64.sh -q
fi

echo "Jts tree:"
find "$HOME/Jts" -maxdepth 4 \( -type d -o -name 'ibgateway' -o -name '*.vmoptions' \) 2>/dev/null | head -50

echo "=== Downloading IBC ==="
URL=$(curl -sL https://api.github.com/repos/IbcAlpha/IBC/releases/latest | python3 -c "import sys,json; r=json.load(sys.stdin); print(next(a['browser_download_url'] for a in r['assets'] if 'Linux' in a['name'] and a['name'].endswith('.zip')))")
echo "$URL"
wget -q -O ibc.zip "$URL"
rm -rf /opt/ibc/*
unzip -o ibc.zip -d /opt/ibc
chmod -R a+rX /opt/ibc
find /opt/ibc -name "*.sh" -exec chmod +x {} \;
ls -la /opt/ibc | head -30

# Seed IBC config template (credentials filled later on the host only)
mkdir -p "$HOME/ibc"
if [[ ! -f "$HOME/ibc/config.ini" ]]; then
  if [[ -f /opt/ibc/config.ini ]]; then
    cp /opt/ibc/config.ini "$HOME/ibc/config.ini"
  elif [[ -f /opt/ibc/IBC/config.ini ]]; then
    cp /opt/ibc/IBC/config.ini "$HOME/ibc/config.ini"
  else
    find /opt/ibc -name config.ini | head -1 | xargs -I{} cp {} "$HOME/ibc/config.ini"
  fi
fi

echo DONE
