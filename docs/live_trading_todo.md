# Live Trading Build Checklist

Work **prompt-by-prompt** from `docs/live_trading_blueprint.md` §5.  
Each software step is **test-driven**. Do not skip ahead to real IBKR orders until Prompt 25 is green and ops Phase G prerequisites are met.

Mark `[x]` when done. Update findings for research IDs in `docs/live_trading_investigation.md`.

---

## How to use

1. Open the matching **Prompt NN** block in `docs/live_trading_blueprint.md`.  
2. Paste that entire ```text``` prompt into a code-generation LLM (standalone — do not rely on chat memory).  
3. Run the listed tests; fix until green.  
4. Check the box below.  
5. Commit when you (human) are ready.

---

## Phase A — Pure domain (Prompts 01–09)

**Goal:** No broker; pure functions + file stores; all unit tested.

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | 01 | `app/fees/` fee model | `tests/test_fees_model.py` |
| [x] | 02 | RTH + open queue | `tests/test_live_session.py`, `tests/test_live_queue.py` |
| [x] | 03 | Idempotency store | `tests/test_live_idempotency.py` |
| [x] | 04 | Share sizing | `tests/test_live_sizing.py` |
| [x] | 05 | Never-borrow check | `tests/test_live_risk_limits.py` |
| [x] | 06 | Audit JSONL log | `tests/test_audit_log.py` |
| [x] | 07 | After-fee B&H metrics | `tests/test_live_metrics.py` |
| [x] | 08 | Risk alert→2h→stop | `tests/test_risk_escalate.py` |
| [x] | 09 | Live modes + `state_live` paths | `tests/test_live_config.py`, `tests/test_live_paths.py` |

**Phase A acceptance:**
- [x] `pytest` on all new tests above green  
- [x] Existing V1/V2 tests still green  

```bash
python -m pytest tests/test_fees_model.py tests/test_live_session.py tests/test_live_queue.py tests/test_live_idempotency.py tests/test_live_sizing.py tests/test_live_risk_limits.py tests/test_audit_log.py tests/test_live_metrics.py tests/test_risk_escalate.py tests/test_live_config.py tests/test_live_paths.py -v
python -m pytest tests/test_strategy_v1_regression.py tests/test_paths.py tests/test_worker_versions.py -v
```

---

## Phase B — Broker port + dry execution (Prompts 10–13)

**Goal:** Swappable `BrokerClient`; memory broker; planner + dry executor.

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | 10 | `BrokerClient` + `InMemoryBroker` | `tests/test_broker_memory.py` |
| [x] | 11 | Reconcile (broker wins) | `tests/test_live_reconcile.py` |
| [x] | 12 | Order intent planner | `tests/test_live_planner.py` |
| [x] | 13 | `execute_intent` dry/live-memory | `tests/test_live_executor.py` |

**Phase B acceptance:**
- [x] Dry-run path never mutates broker when mode says dry  
- [x] Outside RTH queues; idempotency skips duplicates  

```bash
python -m pytest tests/test_broker_memory.py tests/test_live_reconcile.py tests/test_live_planner.py tests/test_live_executor.py -v
```

---

## Phase C — Live worker integration (Prompts 14–15)

**Goal:** `python -m app.live_worker` cycle with injected memory broker; safe CLI modes.

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | 14 | `app/live_worker.py` cycle | `tests/test_live_worker_cycle.py` |
| [x] | 15 | CLI mode banners + `LIVE_TRADING_CONFIRM` | mode/CLI tests in worker tests |

**Phase C acceptance:**
- [x] Two-cycle BUY/SELL works with `InMemoryBroker`  
- [x] `live` without confirm env exits non-zero  
- [x] Paper `app.worker` v1/v2 unchanged  

```bash
python -m pytest tests/test_live_worker_cycle.py -v
python -m app.worker --version v1
```

---

## Phase D — IBKR adapter (Prompts 16–17)

**Goal:** Real adapter code with **mocked** unit tests; optional manual Gateway smoke later.

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | 16 | `IbkrBroker` + `ib_insync` dep | `tests/test_broker_ibkr.py` |
| [x] | 17 | Partial fill + cancel residual | executor/broker tests updated |

**Phase D acceptance:**
- [x] CI/unit tests never need a live Gateway  
- [x] `--broker ibkr` wired (manual smoke optional)  

```bash
python -m pytest tests/test_broker_ibkr.py tests/test_live_executor.py -v
```

---

## Phase E — Alerts, risk wiring, dashboard (Prompts 18–20)

**Goal:** Email events; risk tick stops trading; dashboard disable/ack without SSH.

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | 18 | Notifier live events | notifier tests (SMTP mocked) |
| [x] | 19 | RiskController wired into worker | escalate + worker tests |
| [x] | 20 | Dashboard live controls | `tests/test_live_controls.py` |

**Phase E acceptance:**
- [x] 2h escalate disables trading in automated test  
- [x] Dashboard helpers disable/ack/enable touch only `state_live`  
- [x] V1/V2 dashboard paths still work  

```bash
python -m pytest tests/test_risk_escalate.py tests/test_live_controls.py -v
```

---

## Phase F — Reports, guards, docs, E2E harness (Prompts 21–25)

**Goal:** Daily summary; hard mode guards; README; deploy templates; memory E2E regression.

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | 21 | `app/live_daily_report.py` | report tests |
| [x] | 22 | Mode submit guards / wrapper | guard tests |
| [x] | 23 | `state_live` seed + `.env.example` + README | bootstrap tests |
| [x] | 24 | `deploy/ibgateway/` templates + import smoke | file existence / import script |
| [x] | 25 | Memory E2E harness | `tests/test_live_e2e_memory.py` |

**Phase F acceptance:**
- [x] `pytest tests/test_live_e2e_memory.py -v` green  
- [x] Full suite green including legacy V1/V2 tests  
- [x] README links blueprint + this todo  

```bash
python -m pytest tests/ -v
python scripts/check_live_imports.py
```

---

## Phase G — Human ops (not LLM prompts)

**Goal:** Real Gateway and money ladder. Start only after Phase F acceptance.

| Done | Step | Notes |
|------|------|--------|
| [x] | G0 | **OVHcloud VPS Canada** `15.235.62.2` — Ubuntu, Java, Gateway 10.50, IBC, app synced |
| [x] | G1 | Gateway+IBC paper logged in (acct `DUR235447`); API **4002**; smoke OK (cash 1M) |
| [x] | G1b | Unattended: `xvfb` + `ibgateway` systemd, IBC `AutoRestartTime=11:45 PM` UTC, 2FA relogin=yes (2026-10-06) |
| [x] | G2 | Local + OVH smoke; CAD/BASE snapshot fix; email alerts configured (2026-10-07) |
| [~] | G3 | `broker_paper` via `live-worker.timer` (5m). Clock from **2026-10-05**; need ≥2 weeks + graduation |
| [ ] | G4 | Fund taxable live ~$1k USD; `live_dry_run` several sessions |
| [ ] | G5 | Explicit go-ahead; `LIVE_TRADING_CONFIRM=YES`; mode `live` |
| [ ] | G6 | Week-1 monitoring; reconcile fees vs Flex (R2) |
| [~] | G7 | Research closed except R8 (accountant); doc findings updated 2026-10-07 |

### Graduation checklist (before leaving broker_paper)

- [ ] No unexpected / duplicate orders  
- [ ] Fills match intent (symbol, side, size rules)  
- [ ] Never-borrow never violated  
- [ ] Fees logged; after-fee vs B&H computable  
- [ ] Disconnect/reject handling safe  
- [ ] ≥1 BUY and ≥1 SELL observed (or forced path test)  

---

## Research tracker

| ID | Task | Status | Finding |
|----|------|--------|---------|
| R1 | IBKR Canada paper + API path | closed | OVH: IB API, paper 4002, acct DUR235447, CAD paper cash readable. Remake in `deploy/ibgateway/README.md` |
| R2 | Full fee model numbers; Fixed vs Tiered; λ $ | closed | **Choose IBKR Pro Tiered** (min $0.35 vs Fixed $1). Model in `app/fees/model.py` (2026-10-07 IBKR Pro US rates). λ for ~1-share live sleeves ≈ **$1–2.5** (`estimate_lambda_per_trip`); paper V2 λ=20 stays for continuity. FX funding: **auto** (0.03%) below ~$6.7k. G6 still reconciles vs Flex after fills. |
| R3 | Fractionals MSFT/AAPL/SMH | closed | 2026-10-07 paper probe: contract `sizeIncrement=0.0001` (desktop OK) but API **Error 10243** — fractional equities **cannot** be placed via API. Bot must use **whole shares** on IBKR path. VOO same. |
| R4 | Buying-power fields for never-borrow | closed | Paper `DUR235447`: TotalCashValue CAD 1M; **AvailableFunds** ≈ 1,000,043; **BuyingPower** ≈ 3.33M (leverage — ignore). Bot spendable = AvailableFunds; never-borrow ignores BuyingPower. Probe: `deploy/ibgateway/probe_buying_power.py`. |
| R5 | Gateway+IBC unattended; weekly 2FA | closed | **OVH** (Oracle abandoned): xvfb+ibgateway+timers active; `AutoRestartTime=11:45 PM`; `ReloginAfterSecondFactor…=yes`; **`TWOFA_TIMEOUT_ACTION=restart`** (fixed 2026-10-07); email alerts on; `gateway-health.sh` emails weekly_2fa when IBC logs look like IB Key wait. Phone approve still required when IB asks. |
| R6 | IBKR free US bars quality | closed | 2026-10-07 OVH probe: IBKR paper hourly **TRADES** bars OK for MSFT/AAPL/SMH/VOO. RTH ~35 bars/5d; last close matches Yahoo within **≤0.002%**. Prefer `useRTH=True` (Yahoo/`prepost` adds ~45 ext-hour bars). Worker now uses IB RTH hourly when `--broker ibkr`, Yahoo fallback. Probe: `deploy/ibgateway/probe_us_bars.py`. |
| R8 | Accountant note on frequency | open | Human |
| R9 | Complimentary US streaming/historical API | closed | Historical API confirmed with R6 on paper (`DUR235447`). Streaming quotes not required for peak/trough hourly signals; live worker uses IB historical hourly closes. |

---

## Progress log

| Date | Completed through | Notes |
|------|-------------------|-------|
| 2026-10-05 | OVH VPS delivered | `vps-338e3236.vps.ovh.ca` / `15.235.62.2` / Ubuntu `ubuntu`. Awaiting first SSH + Gateway install. |
| 2026-10-05 | G1 paper Gateway on OVH | Paper login OK (`DUR235447`); port 4002; `IbkrBroker` snapshot OK. Next: keep Gateway up + broker_paper. |
| 2026-10-05 | G3 broker_paper started | `live-worker.timer` every 5m; mode `broker_paper`; first cycles seed troughs (no fills yet). Markets closed evenings — orders only in RTH. |
| 2026-10-06 | Gateway daily exit | Quit ~23:45 UTC (Auto Logoff); no autorestart file → stayed down. |
| 2026-10-06 | Harden autorestart | systemd xvfb+ibgateway; AutoRestartTime 11:45 PM UTC; smoke OK again. |
| 2026-10-06 | Monitoring | gateway-health.timer 00:15+12:15 UTC; email helper `set_email_alerts.sh`; worker emails on IB connect fail. |
| 2026-10-07 | Email alerts live | Gmail app password working; test mail received. |
| 2026-10-07 | R3 fractionals | API Error 10243 for MSFT/AAPL/SMH/VOO; bot forced to whole shares on IBKR path. |
| 2026-10-07 | R2 fees / λ | Tiered chosen; fee model + Fixed schedule + FX auto/manual + `estimate_lambda_per_trip`. |
| 2026-10-07 | R6/R9 IB bars | Paper hourly TRADES ≈ Yahoo; worker prefers IB RTH hourly + Yahoo fallback. |
| 2026-10-07 | R5 unattended/2FA | TWOFA_TIMEOUT_ACTION=restart; health script weekly_2fa detect; R5 closed. |
| 2026-10-07 | R4 buying power | AvailableFunds=spendable; BuyingPower ignored; R4 closed. |

---

## Next action

**Wait out G3** (≥2 weeks `broker_paper` from 2026-10-05; target ~2026-10-19). Do **not** start G4/G5 (real money) early.
