# IB Gateway — setup & remake guide

This host runs paper V1/V2 and the live variant together. The Gateway API must stay on **localhost** only.

**Primary host (2026-10):** OVHcloud VPS (Canada). Oracle Always Free was abandoned after repeated Ampere out-of-capacity failures.

Use this doc to **recreate** every Gateway/API step when moving from Windows paper smoke → OVH paper → live.

---

## Host choice

| Host | Status | Notes |
|------|--------|--------|
| **OVHcloud VPS Canada** | **Active** | Beauharnois. **VPS-1**, Ubuntu 24.04 |
| Oracle Always Free | Abandoned for now | Capacity blocked in Toronto |
| Windows laptop | Smoke only | Not always-on |

### OVH instance (this deployment)

| Field | Value |
|-------|--------|
| VPS name | `vps-338e3236.vps.ovh.ca` |
| IPv4 | `15.235.62.2` |
| IPv6 | `2607:5300:205:200::c94d` |
| SSH user | `ubuntu` |
| Plan | VPS-1 (2 vCore / 4 GB / 40 GB) |
| App path | `/opt/autonomous-trade-alerts` |
| IB Gateway | `/home/ubuntu/Jts/ibgateway/10.50` |
| IBC | `/opt/ibc` + config `/home/ubuntu/ibc/config.ini` |

**Installed 2026-10-05/06:** Ubuntu updated, OpenJDK 17, IB Gateway 10.50, IBC 3.24.2, repo synced, Python venv.

**Paper login helper (on VPS):** `~/set_ib_paper_login.sh` — prompts for paper username/password; writes `~/ibc/config.ini` (chmod 600).

**systemd (unattended — set 2026-10-06):**

| Unit | Role |
|------|------|
| `xvfb.service` | Virtual display `:1` |
| `ibgateway.service` | IBC + Gateway (`Restart=always`) |
| `live-worker.timer` | Worker every 5 minutes |
| `picker-rank.timer` | S&P picker ranking Sat ~00:00 ET (04:00 UTC) |
| `streamlit-dashboard.service` | Remote portfolio UI (Tailscale; §13) |

```bash
sudo systemctl status xvfb ibgateway live-worker.timer picker-rank.timer streamlit-dashboard.service
sudo journalctl -u ibgateway.service -n 80 --no-pager
ss -ltn | grep 4002
```

### Remote portfolio dashboard (Streamlit + Tailscale)

**Spec:** `docs/live_trading_investigation.md` §13. Check the book **without** logging into IBKR Client Portal / a second Gateway.

1. Install **Tailscale** (free personal) on the VPS, your phone, and your laptop; join the same tailnet.
2. On the VPS:

```bash
cd /opt/autonomous-trade-alerts
sudo cp deploy/ibgateway/streamlit-dashboard.service /etc/systemd/system/
sudo sed -i 's/\r$//' /etc/systemd/system/streamlit-dashboard.service
sudo systemctl daemon-reload
sudo systemctl enable --now streamlit-dashboard.service
```

3. Reach the UI privately (pick one):
   - **Tailscale Serve** (recommended): `sudo tailscale serve --bg 8501` then open the Serve URL from phone/laptop
   - Or SSH tunnel: `ssh -L 8501:127.0.0.1:8501 ubuntu@100.x.y.z` then `http://127.0.0.1:8501`
4. Do **not** bind Streamlit to `0.0.0.0` on the public NIC.
5. IBKR marks on the Live tab use **`DASHBOARD_IB_CLIENT_ID=9`** (worker=1, picker=7).

Tabs: **Live | Paper V1 | Paper V2 | Picker**. Safe controls only (enable/disable trading, ack risk) — no mode changes from the phone UI.

**IBC daily Auto-Restart:** `AutoRestartTime=11:45 PM` (UTC on this host) so the nightly exit **restarts with token** instead of staying down. `TWOFA_TIMEOUT_ACTION=restart` + `ReloginAfterSecondFactorAuthenticationTimeout=yes` for weekly IB Key (still approve on phone).

Manual start (prefer systemd):

```bash
sudo systemctl restart ibgateway.service
```

Re-apply harden script after OS reinstall: `bash deploy/ibgateway/harden_autorestart.sh` (from copied `/tmp` files).

**Smoke test (on VPS):**

```bash
cd /opt/autonomous-trade-alerts && . .venv/bin/activate
python -c "import asyncio; asyncio.set_event_loop(asyncio.new_event_loop()); from app.broker.ibkr import IbkrBroker; b=IbkrBroker(); print(b.ib.managedAccounts()); print(b.get_account_snapshot()); b.ib.disconnect()"
```

**Working state (2026-10-05):** paper login OK, API `4002`, snapshot cash/equity ~1,000,000.

**broker_paper worker:** systemd timer every 5 minutes:

```bash
sudo systemctl status live-worker.timer
journalctl -u live-worker.service -n 50 --no-pager
```

**S&P picker ranking:** Saturday 00:00 America/New_York (`picker-rank.timer`). CLI skips if a successful run is under 13 days old unless `PICKER_FORCE=1` / `--force`. Prefer one `--dry-run` review of `state_picker/ranking_runs/` before enabling pending writes.

```bash
sudo cp deploy/ibgateway/picker-rank.service /etc/systemd/system/
sudo cp deploy/ibgateway/picker-rank.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now picker-rank.timer
cd /opt/autonomous-trade-alerts && . .venv/bin/activate
python -m app.picker_rank --dry-run --no-email --force
journalctl -u picker-rank.service -n 50 --no-pager
```

**Email alerts (phone):** on the VPS run `~/set_email_alerts.sh` and enter Gmail + App Password + recipient. Then fills/rejects/disconnects/2FA/Gateway health emails work.

**Gateway health timer:** `gateway-health.timer` at **00:15 UTC** (after Auto-Restart) and **12:15 UTC** (morning). Log: `~/ibc/logs/gateway-health.log`.

Manual one-shot:

```bash
cd /opt/autonomous-trade-alerts && . .venv/bin/activate
python -m app.live_worker --mode broker_paper --broker ibkr
```

Note: market orders only during US RTH (~9:30–16:00 ET). Outside RTH, intents are queued.

### OVH order checklist (remake)

1. Go to [OVHcloud VPS Canada](https://www.ovhcloud.com/en-ca/vps/) (or [Ubuntu VPS](https://www.ovhcloud.com/en-ca/vps/os/vps-ubuntu/))
2. Choose **VPS-1** (2 vCores / **4 GB RAM** / 40 GB NVMe) — enough to start; upgrade to VPS-2 (8 GB) if Gateway feels tight
3. Datacenter: **Canada** (Beauharnois / BHS)
4. OS: **Ubuntu 22.04** or **24.04** (no Windows needed)
5. Skip paid extras for now (cPanel, extra backup) unless you want them
6. Billing: monthly is fine
7. After delivery email: note **IPv4**, username **`ubuntu`**, and temporary password link
8. First SSH (password), then install your SSH public key (recommended)

```powershell
# First login (password from OVH email)
ssh ubuntu@PUBLIC_IP

# Optional: reuse the Oracle key as your OVH login key (after first password login)
type $env:USERPROFILE\.ssh\ssh-key-2026-10-01.key.pub
# On the VPS:
#   mkdir -p ~/.ssh && chmod 700 ~/.ssh
#   echo "PASTE_PUBLIC_KEY_HERE" >> ~/.ssh/authorized_keys
#   chmod 600 ~/.ssh/authorized_keys
```

Later SSH:

```powershell
ssh -i $env:USERPROFILE\.ssh\ssh-key-2026-10-01.key ubuntu@PUBLIC_IP
```

Do not commit the private key or put OVH passwords in git.

### OVH automated backup (this account — promo)

Ordered with **VPS-1 2027**; OVH email confirmed **Automated Backup** activated.

| Item | Value |
|------|--------|
| VPS name | `vps-338e3236.vps.ovh.ca` |
| Feature | Automated Backup Standard (promo; normally ~$0.60/mo) |
| Manage UI | OVH Manager → Bare Metal Cloud → VPS → Backup |
| Status API | `GET https://ca.api.ovh.com/1.0/vps/vps-338e3236.vps.ovh.ca/automatedBackup` |
| Restore points | `GET .../automatedBackup/restorePoints` |
| Restore | `POST .../automatedBackup/restore` |

**Use for:** whole-disk recovery if the OS is bricked.  
**Not a substitute for:** trading audit JSONL / `.env` awareness — those live on the VPS disk and are only as safe as the snapshots.  
**Later:** when promo ends, check billing and keep or disable backup deliberately.

---

## SSH keys (local, not in git)

Key pair created 2026-10-01 for Oracle; **reuse for OVH** (or generate a new one). Files stay in the Windows SSH folder, not in this repository.

| File | Path |
|------|------|
| Private key | `C:\Users\phung\.ssh\ssh-key-2026-10-01.key` |
| Public key | `C:\Users\phung\.ssh\ssh-key-2026-10-01.key.pub` |

---

## Remake checklist (do this again on every new host)

Copy/paste and check off when deploying paper on OVH, then again for live.

### A. IBKR account (Client Portal)

- [ ] IBKR **Canada** individual (taxable) account approved
- [ ] **Paper Trading Account** requested under Settings → Paper Trading Account (separate username/password)
- [ ] Paper login written down offline (not in git / not in this README)
- [ ] Trading permissions include **US stocks/ETFs**
- [ ] For **live** funding later: convert CAD→USD in chunks; hold **USD cash** for picker-selected US names (no per-trade auto-FX)

### B. Install Gateway

- [ ] Install **IB Gateway** (stable) + Java if prompted
- [ ] On login screen choose **IB API** (not FIX CTCI)
- [ ] Choose **Paper Trading** for paper; **Live** only after graduation + explicit go-ahead
- [ ] Install [IBC](https://github.com/IbcAlpha/IBC) or IBeam on the always-on host so daily restart can re-login

### C. Gateway API settings (Configure → Settings → API → Settings)

| Setting | Paper | Live (later) |
|---------|-------|--------------|
| Enable ActiveX and Socket Clients | ON | ON |
| Socket port | **4002** | **4001** |
| Trusted IPs | `127.0.0.1` | `127.0.0.1` |
| **Read-Only API** | **OFF** (orders need write) | **OFF** only when intentionally live |
| Auto restart | ON | ON |
| Lock and Exit | OFF while bot runs | OFF while bot runs |

Also:

- Do **not** run a second TWS/Gateway session on the same account
- Keep API bound to localhost; never expose 4001/4002 publicly

### D. Env on the host (`.env`, not git)

```bash
IB_HOST=127.0.0.1
IB_PORT=4002          # paper; use 4001 only for live
IB_CLIENT_ID=1
LIVE_TRADING_CONFIRM= # must be YES only for true live
```

### E. Smoke test (after Gateway shows green)

Connection Status should show:

- Interactive Brokers API Server → **connected**
- Market Data Farm → ON (e.g. `usfarm`)
- Historical Data Farm → ON (e.g. `ushmds`)

From the repo (PowerShell; create an event loop first on Python 3.10+ / 3.14):

```powershell
$env:IB_HOST="127.0.0.1"
$env:IB_PORT="4002"
$env:IB_CLIENT_ID="1"
python -c @"
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())
from ib_insync import IB, LimitOrder, Stock
ib = IB()
ib.connect('127.0.0.1', 4002, clientId=1)
print('accounts:', ib.managedAccounts())
ib.sleep(2)
for v in ib.accountValues():
    if v.tag in ('TotalCashValue','NetLiquidation','BuyingPower') and v.currency in ('CAD','USD','BASE',''):
        print(v.tag, v.currency, v.value)
# Write-path check (safe: will not fill)
c = Stock('AAPL','SMART','USD'); ib.qualifyContracts(c)
o = LimitOrder('BUY', 1, 1.0); o.tif='GTC'; o.outsideRth=True
t = ib.placeOrder(c, o); ib.sleep(2)
print('order status:', t.orderStatus.status)
ib.cancelOrder(t.order); ib.sleep(1); ib.disconnect()
"@
```

Pass criteria:

- [ ] `managedAccounts()` returns an account id
- [ ] Cash / NLV visible (see currency note below)
- [ ] No Error **321** Read-Only
- [ ] Limit GTC order reaches **Submitted** / **PreSubmitted**, then cancel cleanup

---

## Local Windows paper smoke (2026-10-03) — record for remake

Done on the developer PC while Oracle Ampere capacity was unavailable. **Repeat the same checks on the VM.**

| Item | Observed |
|------|----------|
| Login API type | **IB API** (not FIX CTCI) |
| Mode | Paper Trading |
| Port listening | `0.0.0.0:4002` |
| Paper account id | `DUR235447` |
| Simulated cash | **CAD 1,000,000** (Canada paper base is CAD) |
| Buying power | CAD ~3,333,333 (margin paper) |
| Positions | Empty |
| Read-Only on first try | ON → Error 321 on open/completed orders; account read still worked after `reqAccountUpdates` |
| Read-Only after fix | OFF → order submit works |
| Market BUY 1 AAPL (Sat) | Cancelled — Error **10349** (DAY TIF / outside session) |
| GTC limit BUY 1 @ $1 | **Submitted** → cancelled for cleanup |
| Python note | Python 3.14 needs `asyncio.set_event_loop(asyncio.new_event_loop())` before importing/using `ib_insync` |

### Code follow-ups discovered

1. **`IbkrBroker` CAD/BASE snapshot** — **fixed 2026-10-03.** Prefers USD; falls back to BASE/CAD (Canada paper); converts via `ExchangeRate(USD)` when present. Live should still fund a **USD cash sleeve** so USD tags win.
2. Worker market orders with default **DAY** TIF will not fill outside RTH; RTH gate + queue already planned — do not expect weekend fills.
3. For live remake: same Gateway steps, port **4001**, paper credentials replaced by live, Read-Only off only after `live_dry_run` graduation + `LIVE_TRADING_CONFIRM=YES`.

---

## Probes (research)

Kept in-tree for occasional re-checks. One-shot diagnose/fractional scripts live under `archive/ibgateway_probes/`.

```bash
cd /opt/autonomous-trade-alerts && . .venv/bin/activate
# R4 — TotalCashValue / AvailableFunds / BuyingPower (never size on BuyingPower)
IB_CLIENT_ID=95 python deploy/ibgateway/probe_buying_power.py
# R6 — IBKR free hourly TRADES vs Yahoo (prefer useRTH)
IB_CLIENT_ID=91 python deploy/ibgateway/probe_us_bars.py
# R3 — fractionals (archived; API rejects → whole shares only)
# python archive/ibgateway_probes/probe_fractionals.py
```

**R4 finding (2026-10-07):** AvailableFunds ≈ cash (same-day spendable); BuyingPower ≈ 3.33× on paper margin — ignored for never-borrow.

**R5:** `TWOFA_TIMEOUT_ACTION=restart` in `/opt/ibc/gatewaystart.sh`; `gateway-health.sh` emails `weekly_2fa` when recent IBC logs look like an IB Key wait.

**Outage lesson (2026-10-12):** Gateway can leave port **4002 listening** while the IB session is dead (“zombie”) — worker then times out on account/positions. Cause that day: mid-session re-login showed `Unrecognized Username or Password` at 04:14 UTC after a healthy AutoRestart at 23:45. Health checks had been broken since Oct 9 because `gateway-health.sh` was saved with **Windows CRLF** (`status=203/EXEC`). Fix: always `sed -i 's/\r$//'` after SCP; health script now **probes the API** (not just the port), **restarts zombie Gateway**, and runs **hourly**.

**Worker resume (2026-10-17):** Health used to **stop** `live-worker.timer` on Gateway failure but only restart it in the same run as a successful Gateway restart. If Gateway recovered later (IB Key, AutoRestart, etc.), the timer stayed inactive forever. Health now **starts** `live-worker.timer` whenever status is OK and the timer is inactive.

**Zombie + cooldown (2026-10-17):** Port 4002 can stay LISTEN while the IB session is dead. Health stops the worker (correct). A 6h restart cooldown after *any* restart attempt used to block retries even when the first restart failed — timer stayed off for hours. Now: **6h cooldown only after a successful recovery**; failed restart retries after **30 minutes**.

**R6 finding (2026-10-07):** paper historical 1h bars match Yahoo last close (≤0.002%); live worker uses IB RTH hourly when `--broker ibkr`, Yahoo fallback. Minimal hosts need `tzdata` in the venv (in `requirements.txt`).

---

## Install (OVH / Linux host)

1. Use the OVH Ubuntu VPS (VPS-1 or larger).
2. Install IB Gateway (stable) and Java if the installer asks for it.
3. Install IBC or IBeam for unattended daily login.
4. Apply **Remake checklist** sections B–E above.
5. Paper port `4002`. Live port `4001`.

## Run

Copy `.env.example` to `.env` on the VM. Do not commit `.env`.

```bash
sudo cp deploy/ibgateway/ibgateway.service /etc/systemd/system/
sudo cp deploy/ibgateway/live-worker.service /etc/systemd/system/
sudo cp deploy/ibgateway/live-worker.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ibgateway live-worker.timer
```

Expect a short reconnect each night. About once a week IBKR asks for IB Key. The bot emails `Live weekly 2FA required` when that happens. Approve it, then trading resumes.

## Logs

```bash
sudo cp deploy/ibgateway/live-audit.logrotate /etc/logrotate.d/live-audit
```

Audit JSONL stays on the VM, not in git.
