# Live Trading Blueprint (TDD Prompt Series)

**Status:** v4 — live 01–25 + picker **P01–P22** + **remote dashboard Part III (D01–D08)** (2026-10-17)  
**Decisions:** `docs/live_trading_investigation.md` (§12 picker · **§13 remote viewer**)  
**Tracking:** `docs/live_trading_todo.md`  
**Repo:** `autonomous-trade-alerts` (extend in place; keep paper V1/V2)

Not legal/tax advice.

**How to use:** Live (§5) and picker Part II are implemented. Next software layer: **Part III remote dashboard (D01–D08)** per §13. Ops in parallel: **G3** + **Phase J**. Historical prompt text may still mention the MVP trio — treat as TDD provenance, not current universe guidance.

---

## 1. What we are building

A **fee- and platform-aware live trading variant** of the existing peak/trough bot that:

- Places **fully automatic market orders** via **IBKR Canada** (IB Gateway + IBC/IBeam + Python).
- Competes with **equal-weight buy-and-hold** of the **picker active list** **after all fees**.
- Starts at ~**USD 1,000** total; universe from the **biweekly S&P 500 picker** (≤5 names), not a fixed trio.
- Runs on **one OVH Canada VPS** with paper V1/V2 + live + picker job.
- Modes: `sim` → `broker_paper` → `live_dry_run` → `live`.
- Risk: per-order never-borrow / RTH / idempotency; threshold **alert → 2h no ack → stop**.
- UX: Streamlit dashboard on OVH via **Tailscale** (health + portfolio + safe controls) + email alerts.
- Whole shares only on IBKR API (no US equity fractionals via API).

Existing code to preserve: `app/strategy.py`, `app/worker.py` (`--version v1|v2`), `app/picker/`, `state/`, `state_v2/`, `state_live/`, `app/dashboard.py`, `app/notifier.py`.

---

## 2. Architecture (target)

```
OVH VPS
├── IB Gateway + IBC (localhost API)
├── python -m app.worker --version v1|v2          # paper sim
├── python -m app.live_worker --mode …           # live variant (+ Monday picker apply)
├── python -m app.picker_rank                    # biweekly S&P rank (timer)
├── systemd: streamlit-dashboard.service         # Tailscale-only; evolve app/dashboard.py
├── state/  state_v2/  state_live/  state_picker/  logs/audit/
└── .env (secrets; not in git)
```

**Live cycle:** reconcile broker → load hourly bar → peak/trough signal → size (fractional if allowed else whole) → fee estimate → never-borrow check → RTH gate / queue → idempotent send or dry-run → audit + alerts → after-fee vs B&H metrics.

---

## 3. Chunking (round 1 → round 2 → right size)

### Round 1 — large chunks

| Chunk | Intent |
|-------|--------|
| A | Pure domain (fees, RTH, sizing, risk, audit, metrics) |
| B | Broker port + mock + reconcile + dry executor |
| C | Live worker integration (still mock broker) |
| D | Real IBKR adapter + paper orders |
| E | Notifier + dashboard controls + escalate wiring |
| F | Mode guards, reports, docs, ops templates |

### Round 2 — medium slices

A1 fees · A2 RTH/queue · A3 idempotency · A4 sizing · A5 never-borrow · A6 audit · A7 B&H metrics · A8 risk timer · A9 live config/modes  
B1 broker protocol+mock · B2 reconcile · B3 order planner · B4 dry executor  
C1 `state_live` paths · C2 `live_worker` cycle · C3 CLI mode flag  
D1 IBKR adapter · D2 market order API  
E1 notifier events · E2 risk→disable+notify · E3 dashboard live+ack  
F1 mode safety guards · F2 daily summary · F3 README/env · F4 Gateway unit templates  

### Round 3 — right-sized for TDD (each = one LLM prompt)

Each step: **tests first (or with) → minimal implementation → wire into the module graph used by the next step**. No orphan libraries. Complexity jumps only after mocks prove the seam.

---

## 4. Prompting conventions (for the implementer)

- Prefer **pytest**; do not break existing V1/V2 tests.
- New code under `app/fees/`, `app/live/`, `app/broker/`, `app/audit/`, `app/risk/` as needed.
- Live config under `state_live/` (mirror `paths.py` patterns).
- Never commit secrets; use `.env` / environment variables.
- End each step with code **imported by a higher-level module or CLI** already in the repo (or introduced in that same step).

---

## 5. Implementation prompts

Run these **in order**. Each block is a standalone prompt for a code-generation LLM.

### Prompt 01 — Fee model

```text
You are working in the Python repo autonomous-trade-alerts (peak/trough trading bot with app/strategy.py, app/worker.py, pytest tests/).

Add a pure fee-estimation module with tests. Create app/fees/__init__.py and app/fees/model.py plus tests/test_fees_model.py.

Requirements:
- Dataclass FeeSchedule with configurable fields for: per-order commission minimum (USD), commission per share, SEC fee rate on sells (fraction of notional), FINRA TAF per share on sells, CAT per share, clearing per share, optional pass-through fraction of commission, per-side slippage_bps, FX min USD and FX bps for funding conversions.
- Functions: estimate_equity_order_fees(side: "BUY"|"SELL", quantity: float, price: float, schedule: FeeSchedule) -> breakdown dict with named components and total.
- estimate_round_trip_fees(quantity, buy_price, sell_price, schedule) -> total.
- estimate_fx_conversion_fee(notional_usd, schedule) -> fee.
- Default schedule factory default_ibkr_us_stock_schedule() with documented placeholder numbers (not live scrapes).
- All pure Python; no network; no broker.

Write failing tests first for: buy hits commission minimum; sell includes SEC+TAF; round trip totals; FX min applies on small conversion. Then implement until green.

Wire: export public helpers from app/fees/__init__.py so other modules can import estimate_equity_order_fees and default_ibkr_us_stock_schedule.

Do not modify worker.py or strategy.py yet. Keep changes minimal and typed.
```

### Prompt 02 — US RTH and open queue

```text
You are working in the Python repo autonomous-trade-alerts.

Add US regular-hours trading session helpers and a pending open-queue with tests.

Create app/live/session.py and app/live/queue.py (plus app/live/__init__.py) and tests/test_live_session.py, tests/test_live_queue.py.

Requirements:
- is_us_equity_rth(now_utc: datetime) -> bool using America/New_York, Mon–Fri, 09:30–16:00 Eastern, excluding a simple holiday set (at least New Year’s Day, Independence Day, Christmas; document that the set is incomplete and configurable).
- next_rth_open(now_utc) -> datetime UTC.
- PendingIntent store backed by a JSON file path: save/load list of intents with fields symbol, side, bar_ts, created_at, reason. Methods: enqueue (idempotent by symbol+bar_ts+side), list_pending, pop_symbol, clear.
- No broker calls.

Tests: RTH true/false around boundaries; queue enqueue dedupe; persist reload.

Wire: export is_us_equity_rth, next_rth_open, PendingIntentStore from app/live/__init__.py.

Do not change the worker yet.
```

### Prompt 03 — Idempotency store

```text
You are working in the Python repo autonomous-trade-alerts.

Add an idempotency store so the live bot never double-fires the same symbol+bar.

Create app/live/idempotency.py and tests/test_live_idempotency.py.

Requirements:
- File-backed store (JSON) with key string f"{symbol}|{bar_ts_iso}|{side}".
- Methods: already_done(key) -> bool; mark_done(key, meta: dict); list_keys().
- Atomic-enough write (write temp + replace).

Tests: mark then already_done true; different bar false; reload from disk.

Wire: export IdempotencyStore from app/live/__init__.py and ensure app/live/__init__.py re-exports it alongside session/queue helpers without breaking prior exports.
```

### Prompt 04 — Share sizing

```text
You are working in the Python repo autonomous-trade-alerts.

Add share sizing helpers for all-in/all-out sleeves with optional fractionals.

Create app/live/sizing.py and tests/test_live_sizing.py.

Requirements:
- buy_share_quantity(cash: float, price: float, allow_fractional: bool) -> float: if fractional, cash/price (finite); else math.floor(cash/price) as float.
- sell_share_quantity(shares_held: float, allow_fractional: bool) -> float: sell all held (if not fractional, floor to whole shares still allowing selling the whole position if already whole).
- residual_cash_after_buy(cash, price, qty).
- Reject non-positive price; return 0 if cannot buy at least one whole share when fractionals disallowed.

Tests: fractional AAPL-like; whole-share leftover cash; zero cash; invalid price.

Wire: export sizing functions from app/live/__init__.py.
```

### Prompt 05 — Never-borrow check

```text
You are working in the Python repo autonomous-trade-alerts.

Add a pure pre-trade never-borrow / no-debit guard.

Create app/live/risk_limits.py and tests/test_live_risk_limits.py.

Requirements:
- Dataclass AccountSnapshot with cash_usd, buying_power_usd, equity_usd (floats).
- would_create_debit(side, notional_usd, estimated_fees, snapshot) -> bool for BUY: true if cash_usd - notional - fees < -1e-6 (strict cash/equity policy: do not use buying_power to allow leverage; buying_power may be logged but leverage forbidden).
- assert_never_borrow(...) -> None or raise ValueError with clear message.
- Policy comment: margin account may exist for settlement flexibility, but this check forbids negative cash after trade.

Tests: afford buy; reject oversize buy; sell does not create debit via this check.

Wire: export from app/live/__init__.py.
```

### Prompt 06 — Audit log

```text
You are working in the Python repo autonomous-trade-alerts.

Add an append-only audit logger for live trading events.

Create app/audit/__init__.py, app/audit/log.py, tests/test_audit_log.py.

Requirements:
- AuditLog(path: Path) with append(event_type: str, payload: dict) writing one JSON object per line (JSONL) including utc timestamp.
- event_type examples: intent, order_submitted, fill, fee, alert, ack, stop, reconcile_drift.
- read_all() for tests; never deletes history in append().
- Directory created if missing.

Tests: append two events; read back; file grows.

Wire: export AuditLog from app/audit/__init__.py.
```

### Prompt 07 — After-fee B&H metrics

```text
You are working in the Python repo autonomous-trade-alerts.

Add portfolio metrics comparing live sleeves to equal-weight buy-and-hold after fees.

Create app/live/metrics.py and tests/test_live_metrics.py.

Requirements:
- Given starting_cash_total, symbols list, per-symbol series of terminal values for bot and for B&H (or start_price/end_price + fees paid), compute:
  - bot_return_pct, bh_return_pct, edge_pct
  - equal_weight_bh_value helper: allocate equal cash per symbol at start prices, hold to end prices, subtract one initial buy fee estimate per symbol using app.fees.
- Use app.fees.default_ibkr_us_stock_schedule and estimate_equity_order_fees for initial B&H buy fees.
- Pure functions; no I/O.

Tests: synthetic three-symbol case where bot beats/loses B&H; fees reduce B&H and bot.

Wire: export from app/live/__init__.py.
```

### Prompt 08 — Risk alert → 2h → stop state machine

```text
You are working in the Python repo autonomous-trade-alerts.

Implement the risk escalation state machine: alert first, auto-stop if no ack within 2 hours.

Create app/risk/__init__.py, app/risk/escalate.py, tests/test_risk_escalate.py.

Requirements:
- RiskState persisted as JSON: trading_enabled bool; open_incident optional with id, kind, alerted_at ISO, acked_at optional.
- RiskController(path):
  - trigger(kind, now) -> starts incident if none; records alerted_at; does not disable yet.
  - ack(now) -> marks acked; clears incident.
  - tick(now) -> if incident open, not acked, and now - alerted_at >= 2 hours, set trading_enabled False and mark stopped.
  - disable()/enable() explicit.
- Default escalate_after = timedelta(hours=2).

Tests: trigger then tick before 2h keeps enabled; after 2h disables; ack prevents disable; enable after stop.

Wire: export RiskController from app/risk/__init__.py.
```

### Prompt 09 — Live config and modes

```text
You are working in the Python repo autonomous-trade-alerts. It already has app/paths.py for v1/v2 state dirs.

Add live mode enum + config loading for state_live.

Create app/live/modes.py, app/live/config.py, extend app/paths.py with StatePaths for live (or LivePaths), bootstrap state_live/config.json defaults, and tests/test_live_config.py, tests/test_live_paths.py.

Requirements:
- Enum TradingMode: sim, broker_paper, live_dry_run, live.
- parse_mode(str) with clear errors.
- LiveConfig dataclass: mode, symbols default ["MSFT","AAPL","SMH"], total_cash 1000, per-symbol thresholds placeholders, trading_enabled, allow_fractional_default True, fee schedule name/defaults.
- load_live_config(path), save_live_config(path).
- Bootstrap function writing state_live/config.json, empty state.json, audit dir path helpers if missing.
- Do not delete state/ or state_v2/.

Tests: parse modes; bootstrap creates files; load roundtrip.

Wire: LivePaths usable like StatePaths; export from app/live/__init__.py.
```

### Prompt 10 — Broker protocol and in-memory broker

```text
You are working in the Python repo autonomous-trade-alerts.

Define a broker interface and an in-memory broker for tests.

Create app/broker/__init__.py, app/broker/base.py, app/broker/memory.py, tests/test_broker_memory.py.

Requirements:
- Protocol BrokerClient with: get_account_snapshot() -> AccountSnapshot (reuse or mirror fields cash_usd, buying_power_usd, equity_usd); get_positions() -> dict[str, float] shares; place_market_order(symbol, side, quantity) -> OrderResult(order_id, status, filled_qty, avg_price); cancel_order(order_id); supports_fractional(symbol) -> bool.
- InMemoryBroker: starts with cash and optional positions; place_market_order updates cash/positions immediately at provided last_prices dict; track orders list.
- No ib_insync dependency yet.

Tests: buy then sell; insufficient cash raises or returns rejected; fractional flag.

Wire: export BrokerClient, InMemoryBroker, OrderResult from app/broker/__init__.py.
```

### Prompt 11 — Reconcile (broker wins)

```text
You are working in the Python repo autonomous-trade-alerts.

Add reconciliation that treats broker positions/cash as source of truth.

Create app/live/reconcile.py and tests/test_live_reconcile.py.

Requirements:
- LocalSleeveState dict-like: cash, shares per symbol.
- reconcile(local_state, broker: BrokerClient) -> ReconcileReport with broker cash/positions, list of drifts (symbol, local_shares, broker_shares), and a corrected local_state copying broker values.
- Never invent broker data; only read via BrokerClient.

Tests: with InMemoryBroker, detect share drift and produce corrected state; no drift clean.

Wire: export reconcile from app/live/__init__.py.
```

### Prompt 12 — Order intent planner

```text
You are working in the Python repo autonomous-trade-alerts. Strategy signals use app.strategy.step_signal (BUY/SELL/None) with StrategyState.

Add a planner that turns a signal into an OrderIntent using sizing, fees, and never-borrow checks.

Create app/live/planner.py and tests/test_live_planner.py.

Requirements:
- OrderIntent dataclass: symbol, side, quantity, limit_price=None, estimated_fees, bar_ts, reason.
- plan_from_signal(symbol, signal, strategy_state, price, allow_fractional, account_snapshot, fee_schedule, bar_ts) -> OrderIntent | None.
- On BUY: size from cash; estimate fees; if would_create_debit, return None (or intent marked rejected—prefer None + reason log string return tuple (intent|None, reason)).
- On SELL: quantity from shares held.
- Does not call broker.

Tests: BUY intent qty; reject unaffordable; SELL all shares; HOLD returns None.

Wire: export from app/live/__init__.py. Use app.fees and app.live sizing/risk_limits.
```

### Prompt 13 — Dry-run executor

```text
You are working in the Python repo autonomous-trade-alerts.

Add an executor that can dry-run or submit via BrokerClient, with idempotency and audit.

Create app/live/executor.py and tests/test_live_executor.py.

Requirements:
- execute_intent(intent, broker, idempotency: IdempotencyStore, audit: AuditLog, mode: TradingMode, rth_ok: bool, queue: PendingIntentStore) behavior:
  - If not rth_ok: enqueue and audit; return queued.
  - If idempotency already_done: return skipped.
  - If mode is live_dry_run or planning-only dry flag: audit intent as dry_run; mark idempotency; do NOT call place_market_order.
  - If mode is broker_paper or live: call place_market_order; audit submitted/fill; mark idempotency.
- Never place orders when mode is sim.

Tests: dry_run does not change InMemoryBroker positions; live mode with InMemoryBroker changes positions; outside RTH queues; duplicate skipped.

Wire: export execute_intent from app/live/__init__.py.
```

### Prompt 14 — Live worker cycle (mock broker)

```text
You are working in the Python repo autonomous-trade-alerts. Existing worker uses app.strategy.step_signal and downloads prices via app.data.

Create app/live_worker.py that runs one live-variant cycle using BrokerClient injection (default InMemoryBroker for tests).

Requirements:
- run_live_once(paths, broker, risk: RiskController, audit, now_utc, price_by_symbol: dict[str,float], bar_ts_by_symbol: dict) -> summary dict.
- Steps: risk.tick(now); if not trading_enabled skip; reconcile; for each live symbol apply step_signal using local StrategyState stored in state_live/state.json; plan_from_signal; execute_intent with mode from config; save state; append basic equity snapshot CSV under state_live/.
- Use PendingIntentStore + IdempotencyStore + Fee schedule from config.
- Do not import ib_insync.

Tests in tests/test_live_worker_cycle.py with InMemoryBroker and synthetic prices triggering BUY then SELL across two calls.

Wire: `python -m app.live_worker` argparse with --mode live_dry_run defaulting to in-memory broker unless --broker memory is passed (explicit). Document in module docstring.
```

### Prompt 15 — CLI modes and safety banner

```text
You are working in the Python repo autonomous-trade-alerts.

Harden app/live_worker.py CLI:

- Require --mode one of broker_paper|live_dry_run|live (sim remains app.worker).
- For mode live: require env LIVE_TRADING_CONFIRM=YES or refuse to start.
- For live_dry_run: print banner DRY RUN — NO ORDERS SENT; force executor dry path even if somehow misconfigured.
- Add --broker memory|ibkr (ibkr stub may raise NotImplemented until next step).
- Keep paper v1/v2 via existing app.worker unchanged.

Tests: argparse/mode validation tests; live without env raises SystemExit; dry_run never calls place_market_order (spy/mock).

Wire: entry point remains python -m app.live_worker.
```

### Prompt 16 — IBKR broker adapter (mocked unit tests)

```text
You are working in the Python repo autonomous-trade-alerts.

Implement IbkrBroker implementing BrokerClient using ib_insync, with unit tests fully mocked (no real Gateway required in CI).

Create app/broker/ibkr.py, add ib_insync to requirements.txt, tests/test_broker_ibkr.py using monkeypatch/mocks.

Requirements:
- Connect host/port/clientId from env IB_HOST IB_PORT IB_CLIENT_ID (defaults 127.0.0.1, 4002 paper).
- get_positions, get_account_snapshot mapped from account values; supports_fractional(symbol) configurable set or default True for MSFT,AAPL,SMH.
- place_market_order builds MarketOrder; returns OrderResult; on dry_run parameter never submit.
- Document that Gateway must be running for manual integration.

Wire: --broker ibkr in live_worker uses IbkrBroker; memory still default in tests.

Do not place real orders in tests.
```

### Prompt 17 — Partial fills and cancel residual

```text
You are working in the Python repo autonomous-trade-alerts.

Extend IbkrBroker/InMemoryBroker order handling for partial fills and cancel of residual quantity.

Requirements:
- OrderResult includes status filled|partial|rejected|cancelled; filled_qty; remaining_qty.
- After place, if partial, cancel remainder (InMemoryBroker can simulate partial via flag).
- Audit events for partial and cancel.
- execute_intent updates based on filled_qty only; reconcile afterward recommended in worker (call reconcile at end of run_live_once — implement if missing).

Tests: simulated partial fill cancels rest; positions reflect filled only.

Wire into execute_intent and live_worker end-of-cycle reconcile.
```

### Prompt 18 — Notifier live events

```text
You are working in the Python repo autonomous-trade-alerts. Email sending lives in app/notifier.py.

Extend notifier with live event helpers and tests that mock SMTP.

Requirements:
- send_live_event_email(subject, body) reuse existing Gmail env vars.
- Helpers for: fill, reject, disconnect, risk_alert, trading_stopped, weekly_2fa_required.
- Config flags in live config or env to enable/disable per event type (defaults: all on for critical; fills on).

Tests: mock send path called with expected subject keywords.

Wire: live_worker calls notifier on fill/reject/risk stop; failures to send must not crash the cycle (log exception).
```

### Prompt 19 — Connect RiskController to worker and notifier

```text
You are working in the Python repo autonomous-trade-alerts.

Wire RiskController into run_live_once:

- On broker disconnect / repeated reject / max orders exceeded (simple counter in state): risk.trigger(kind, now).
- Each run risk.tick(now); if newly stopped, send trading_stopped email.
- Expose ack via function ack_risk(paths, now) used by dashboard later.
- Persist risk state under state_live/risk.json.

Tests: force trigger + advance time >=2h disables trading and blocks execute_intent.

Wire end-to-end in live_worker without dashboard yet.
```

### Prompt 20 — Dashboard live tab, disable, ack

```text
You are working in the Python repo autonomous-trade-alerts. Dashboard is Streamlit in app/dashboard.py.

Add a Live tab/section:

- Show mode, trading_enabled, open risk incident, live symbols MSFT/AAPL/SMH, last actions from state_live, simple after-fee vs B&H metrics if CSV present.
- Buttons: Disable trading, Enable trading, Ack risk (call into app.risk / small app/live/control.py helpers that only touch state_live files — no secrets).
- Do not display API keys/passwords.
- Keep existing V1/V2/Compare behavior working.

Add tests for control helpers in tests/test_live_controls.py (not full Streamlit UI).

Wire: helpers used by dashboard and documented in docstring.
```

### Prompt 21 — Daily live summary report

```text
You are working in the Python repo autonomous-trade-alerts. There is app/weekly_report.py for paper.

Add app/live_daily_report.py that:

- Reads state_live equity/trades/audit summaries.
- Computes bot vs equal-weight B&H after fees for MSFT,AAPL,SMH.
- Emails daily summary using notifier (mockable).
- CLI python -m app.live_daily_report.

Tests with temp state_live fixtures.

Wire: document cron example in module docstring (after RTH). Do not remove weekly_report.
```

### Prompt 22 — Mode guards for broker_paper vs live

```text
You are working in the Python repo autonomous-trade-alerts.

Finalize safety guards:

- broker_paper: IbkrBroker port default 4002; orders allowed.
- live_dry_run: real port configurable but executor forced dry; assert no place_market_order invocations via wrapper flag.
- live: requires LIVE_TRADING_CONFIRM=YES and trading_enabled; port 4001 typical.
- Central BrokerGateway wrapper records submit_count for tests.

Tests cover each mode’s allow/deny submit behavior with mocks.

Wire: live_worker uses wrapper exclusively for submissions.
```

### Prompt 23 — Seed state_live and README

```text
You are working in the Python repo autonomous-trade-alerts.

- Ensure state_live/ bootstrap committed with safe defaults (mode live_dry_run, symbols MSFT/AAPL/SMH, trading_enabled true, alerts flags).
- Add .env.example with IB_HOST, IB_PORT, IB_CLIENT_ID, LIVE_TRADING_CONFIRM, Gmail vars.
- Update README.md with: paper vs live; modes ladder; link to docs/live_trading_blueprint.md and docs/live_trading_todo.md; warning that live sends real orders.
- Add requirements ib_insync if missing.

Tests: bootstrap test still passes; no secrets in repo.

Wire: README is the human entrypoint; keep existing Streamlit/worker instructions.
```

### Prompt 24 — Ops templates for Gateway on Linux

```text
You are working in the Python repo autonomous-trade-alerts.

Add ops templates (not secret-bearing) under deploy/ibgateway/:

- README.md steps for Oracle Linux: install Gateway, IBC/IBeam, Auto-restart, localhost-only ports, weekly 2FA alert expectation.
- Example systemd unit files for ibgateway and live_worker timer/service (EnvironmentFile=.env).
- Example logrotate.d snippet for state_live/audit JSONL.

Add a smoke script scripts/check_live_imports.py that imports app.live, app.broker, app.fees, app.risk and exits 0.

Tests: optional test that deploy files exist.

Wire: README links to deploy/ibgateway/README.md.
```

### Prompt 25 — Integration test harness (memory broker E2E)

```text
You are working in the Python repo autonomous-trade-alerts.

Add tests/test_live_e2e_memory.py that runs a mini scenario:

- Bootstrap temp state_live.
- InMemoryBroker with 1000 USD.
- Two run_live_once calls with prices engineered to BUY then SELL using strategy thresholds from config.
- Assert audit log contains intent/fill or dry_run events; final broker cash roughly back; risk remains enabled; idempotency prevents third duplicate bar submit.

This is the regression harness for the live stack without IBKR.

Keep runtime fast (<5s). Fix any integration gaps discovered so the harness passes.
```

---

## 6. After the prompt series (human / ops — not LLM code prompts)

These remain manual and are tracked in the todo:

1. OVH VPS + Gateway + IBC (done for paper).  
2. Finish G3 `broker_paper` graduation ≥2 weeks.  
3. Phase J: picker `--dry-run` then enable timer/pending on OVH.  
4. Phase K: Tailscale + always-on Streamlit remote dashboard (Part III).  
5. `live_dry_run` on funded account → `live` with ~$1k after confirm env.  
6. Close remaining research (R8 accountant).

---

## 7. Definition of done (v1 software)

- [ ] All Prompt 01–25 implemented; pytest green including E2E memory harness  
- [ ] Existing V1/V2 tests still green  
- [ ] Dashboard can disable/ack without SSH  
- [ ] Modes enforced; live cannot start without confirm env  
- [ ] README + deploy templates present  
- [ ] Ops graduation / dry-run / live go-ahead recorded outside git if needed  

---

## 8. Related files

- `docs/live_trading_investigation.md` — locked product decisions (§12 picker · §13 remote viewer)  
- `docs/live_trading_todo.md` — checklist mapped to these prompts  
- `archive/docs/v2_blueprint.md` — paper V2 experiment (archived)  

---

# Part II — S&P 500 auto stock-picker

Spec source: `docs/live_trading_investigation.md` §12. Builds on existing `app/strategy.py`, `app/fees/`, `app/broker/ibkr.py` (`latest_hourly_closes`), `app/live_worker.py`, `app/worker.py`, `app/notifier.py`, `app/paths.py`.

---

## 9. Picker — what we are building

A **biweekly, fully automatic** universe selector that:

- Scores **all S&P 500** names on OVH using **IBKR hourly** bars.
- Optimizes buy/sell % on the **prior 1 week**, scores **after-fee edge vs per-symbol B&H** on the **latest 1 month** ($1000/symbol scoring capital).
- Keeps names with **edge ≥ 0**, takes **top ≤ 5** (or **0 → all cash**).
- Emails a summary **every** run; writes **pending**; **applies** on the first `live_worker` cycle after **Monday RTH open** into **V1 + V2 + live**.
- **Soft rotate:** drops → sell on next sell (exit-only); adds → first BUY only if **price > 20h SMA**.
- Live capital: **equal weight as cash frees** (no forced Monday rebalance).
- Mid-biweek V1/V2 re-opt **may overwrite** picker thresholds.
- Data: Wikipedia → cache + last-good; per-ticker retry→skip; **>30%** IBKR fail → error email + **keep previous list**.

Does **not** place orders itself. Does **not** change peak/trough math.

---

## 10. Picker architecture (target)

```
OVH
├── systemd: picker-rank.timer  (Sat 00:00 America/New_York, every 2 weeks)
│     └── python -m app.picker_rank [--dry-run]
│           → state_picker/sp500_cache.json
│           → state_picker/ranking_runs/…
│           → state_picker/pending_selection.json
│           → email summary / failure
├── python -m app.live_worker
│     └── first Monday RTH cycle: apply_pending → state_live + state/ + state_v2/
│           soft-rotate flags; MA gate; equal free-cash BUY sizing
├── python -m app.worker --version v1|v2   # honors applied symbols + exit_only
└── state_picker/  (host artifacts; not git)
```

---

## 11. Picker chunking (round 1 → 2 → right size)

### Round 1 — large chunks

| Chunk | Intent |
|-------|--------|
| A | Pure rank math (windows, fee sim, optimize/score, select, fail%) |
| B | Universe + bars (S&P cache, bar provider, retry/skip) |
| C | Pending / active / soft-rotate plan |
| D | Apply into live + V1 + V2 (atomic, idempotent) |
| E | Worker gates (SMA, exit-only, equal cash) wired into cycles |
| F | Rank CLI + email + Monday apply hook |
| G | IBKR provider, systemd, E2E harness, docs |

### Round 2 — medium slices

A1 paths · A2 normalize · A3 windows · A4 fee sim · A5 one-symbol rank · A6 select · A7 fail%  
B1 Wikipedia cache · B2 bar protocol+fixture · B3 fetch-all retry/skip  
C1 pending · C2 soft-rotate diff · C3 active store  
D1 apply live · D2 apply paper · D3 apply orchestrator  
E1 SMA gate · E2 equal cash · E3 live_worker · E4 paper worker  
F1 rank orchestration · F2 email · F3 CLI · F4 Monday hook  
G1 IBKR adapter · G2 timer/dry-run · G3 E2E · G4 docs  

### Round 3 — right-sized TDD prompts (P01–P22)

Each step: **tests first → minimal code → wire into the next seam**. No orphan modules. Complexity only after pure/fixture seams are green.

---

## 12. Picker prompting conventions

- Prefer **pytest**; do not break existing V1/V2/live tests.
- New code under `app/picker/`; artifacts under `state_picker/` (gitignored).
- Reuse `app/fees/model.py`, `app/strategy.py` (`optimize_params`, `run_fixed_params`, `step_signal`), `app/notifier.py`, existing path helpers.
- Ranking never places broker orders.
- Each prompt is **standalone** (restate context; do not say “as in previous prompt”).
- End each step with exports / CLI / worker import so nothing hangs unused.

---

## 13. Picker implementation prompts

Run **in order** after the live stack pieces you depend on are available (fees, strategy, live config paths, notifier). Each block is a standalone LLM prompt.

### Picker Prompt P01 — state_picker paths

```text
You are working in the Python repo autonomous-trade-alerts (peak/trough bots with app/paths.py for state/, state_v2/, state_live/).

Add picker path helpers with tests.

Create or extend path support so picker artifacts live under state_picker/ (project-root relative, overridable like other state dirs). Need helpers for:
- state_picker directory
- sp500_cache.json
- pending_selection.json
- active_selection.json
- ranking_runs/ directory

Add tests/test_picker_paths.py that resolves paths under a temp project root.

Wire: export a PickerPaths (or equivalent) from app/paths.py or app/picker/paths.py and re-export from app/picker/__init__.py (create package if missing).

Do not fetch network data or change workers yet. Keep changes minimal and typed.
```

### Picker Prompt P02 — Ticker normalization

```text
You are working in the Python repo autonomous-trade-alerts.

Add S&P/IBKR ticker normalization with tests.

Create app/picker/tickers.py and tests/test_picker_tickers.py.

Requirements:
- normalize_wikipedia_ticker(raw: str) -> str for IBKR US stocks (e.g. BRK.B / BF.B style class shares → IBKR-friendly form used elsewhere in this repo if a mapper already exists; otherwise document BRK.B → BRK B convention you choose and use consistently).
- normalize_list(tickers) -> deduped sorted list of normalized symbols.
- Reject empties; strip whitespace; uppercase.

Tests: BRK.B and BF.B; duplicates removed; empty dropped.

Wire: export normalize_wikipedia_ticker and normalize_list from app/picker/__init__.py.
```

### Picker Prompt P03 — S&P 500 Wikipedia parse + disk cache

```text
You are working in the Python repo autonomous-trade-alerts.

Add S&P 500 constituents fetch/parse with last-good disk cache and tests.

Create app/picker/sp500.py and tests/test_picker_sp500.py plus a small HTML fixture under tests/fixtures/.

Requirements:
- parse_sp500_html(html: str) -> list[str] of tickers from the Wikipedia constituents table (fixture-based; no live network in unit tests).
- load_sp500(cache_path, fetcher) -> list[str]: call fetcher(); on success write JSON cache {tickers, fetched_at}; on fetcher failure return last-good cache; if no cache, raise a clear error.
- Use normalize_list from app/picker/tickers.py.

Tests: fixture parse yields expected tickers including a class-share example; cache hit after failed fetch; no cache + fail raises.

Wire: export load_sp500 and parse_sp500_html from app/picker/__init__.py. Use PickerPaths.sp500_cache when callers omit path defaults later.
```

### Picker Prompt P04 — Opt/score window helpers

```text
You are working in the Python repo autonomous-trade-alerts.

Add pure date-window helpers for picker ranking.

Create app/picker/windows.py and tests/test_picker_windows.py.

Requirements:
- Given an “as_of” date (date or timezone-aware datetime in America/New_York), compute:
  - score_window: latest 1 calendar month ending at as_of (start, end)
  - optimize_window: prior 1 calendar week immediately before the score window start (start, end)
- Document inclusive/exclusive bar filtering rules; keep deterministic.
- Helper filter_hourly_closes(timestamps, closes, start, end) -> aligned arrays/lists.

Tests: fixed as_of yields expected calendar bounds; filter keeps only bars inside window.

Wire: export window helpers from app/picker/__init__.py.
```

### Picker Prompt P05 — After-fee strategy vs B&H on a price series

```text
You are working in the Python repo autonomous-trade-alerts.

Add a pure scoring helper that runs peak/trough with IBKR-style fees vs buy-and-hold.

Create app/picker/score.py and tests/test_picker_score.py.

Requirements:
- Use app/strategy.py step_signal / portfolio math and app/fees/model.py (default IBKR US schedule) to simulate round-trips on a 1D close series.
- Inputs: closes sequence, buy_rise, sell_drop, initial_cash (default 1000.0).
- Outputs: strategy_final_value, bh_final_value (buy at first close, hold), strategy_return, bh_return, edge (strategy_return - bh_return), round_trips.
- Fee model: charge estimate_equity_order_fees (or round-trip helper) on each BUY/SELL fill at that bar’s price; subtract from cash/proceeds consistently and document the convention in a short docstring.
- No network.

Tests: synthetic uptrend/chop series where edge sign is known; B&H baseline correct; fees reduce strategy value vs zero-fee control.

Wire: export score_symbol_series (name flexible) from app/picker/__init__.py.
```

### Picker Prompt P06 — Optimize one week then score one month

```text
You are working in the Python repo autonomous-trade-alerts.

Add per-symbol rank step: optimize thresholds on opt-window closes, score edge on score-window closes.

Create app/picker/rank_symbol.py (or extend app/picker/rank.py) and tests/test_picker_rank_symbol.py.

Requirements:
- rank_one_symbol(opt_closes, score_closes, initial_cash=1000) -> dict with buy_rise, sell_drop, edge, strategy_return, bh_return, and any debug fields.
- Optimize buy_rise/sell_drop on opt_closes using existing app/strategy.optimize_params (or grid consistent with repo defaults).
- Score with the picker after-fee edge helper on score_closes using those thresholds.
- If opt or score series too short / empty, return a skipped/error result (no exception swallow without flag).

Tests: fixture series where better thresholds on opt week produce measurable positive edge on score month; short series → skipped.

Wire: export rank_one_symbol from app/picker/__init__.py.
```

### Picker Prompt P07 — Select top ≤5 with edge ≥ 0

```text
You are working in the Python repo autonomous-trade-alerts.

Add selection over many per-symbol rank results.

Create or extend app/picker/rank.py with select_symbols(...) and tests/test_picker_select.py.

Requirements:
- Input: list of per-symbol results with symbol, edge, strategy_return, buy_rise, sell_drop, skipped flag.
- Drop skipped and edge < 0.
- Filter: edge ≥ 0 and strategy_return ≥ 0. Sort by strategy_return descending; ties → higher edge then alphabetical symbol (Hybrid B, 2026-10-18).
- Take at most max_n=5 (configurable default 5).
- Empty list allowed (all cash).

Tests: mixed edges keep only ≥0 and cap at 5; all negative → []; tie-break deterministic.

Wire: export select_symbols from app/picker/__init__.py; selection used by later orchestration.
```

### Picker Prompt P08 — Bulk failure threshold (≥30%)

```text
You are working in the Python repo autonomous-trade-alerts.

Add a pure policy helper for IBKR fetch failure rate.

Create app/picker/failures.py and tests/test_picker_failures.py.

Requirements:
- evaluate_fetch_failures(total_symbols: int, failed_or_skipped: int, threshold: float = 0.30) -> dataclass/result with abort: bool, failure_pct: float.
- abort True when failed/skipped > 30% of total (use strict > 0.30 on the ratio; document; test 31% abort and 29% proceed; exact 30% = proceed unless you document otherwise—prefer abort when ratio > 0.30).

Tests: 0/100, 29/100, 31/100, 0 total guarded.

Wire: export evaluate_fetch_failures from app/picker/__init__.py.
```

### Picker Prompt P09 — Bar provider protocol + fixture provider

```text
You are working in the Python repo autonomous-trade-alerts.

Add an abstract hourly-bar provider for picker ranking (no live IBKR required in unit tests).

Create app/picker/bars.py and tests/test_picker_bars_provider.py.

Requirements:
- Protocol/ABC HourlyBarProvider with get_hourly_closes(symbol: str, start, end) -> list/tuple of (timestamp, close) or raises transient error.
- FixtureBarProvider mapping symbol → series for tests.
- fetch_symbol_with_retries(provider, symbol, start, end, attempts=3) -> series or SkipSymbol error after retries.

Tests: fixture returns data; failing provider retries then skip.

Wire: export HourlyBarProvider, FixtureBarProvider, fetch_symbol_with_retries from app/picker/__init__.py.
```

### Picker Prompt P10 — Fetch universe bars + abort if >30% fail

```text
You are working in the Python repo autonomous-trade-alerts.

Add batch bar fetch for the S&P list using the bar provider and failure policy.

Extend app/picker/bars.py (or app/picker/fetch.py) and tests/test_picker_fetch_universe.py.

Requirements:
- fetch_universe_bars(symbols, provider, opt_window, score_window) -> result with:
  - ok: dict symbol -> {opt_closes, score_closes}
  - skipped: list[(symbol, reason)]
  - abort: bool from evaluate_fetch_failures
- On abort, still return skip stats; caller must not write a new pending selection.

Tests: 10 symbols with 4 forced skips → abort True; 2 skips → abort False and ok contains the rest.

Wire: export fetch_universe_bars from app/picker/__init__.py.
```

### Picker Prompt P11 — Pending selection store

```text
You are working in the Python repo autonomous-trade-alerts.

Add JSON pending_selection store with atomic writes.

Create app/picker/pending.py and tests/test_picker_pending.py.

Requirements:
- Dataclass/fields: run_id, computed_at, apply_after (ISO), symbols: list of {symbol, buy_rise, sell_drop, edge, strategy_return, bh_return}, status: pending|applied|aborted, notes.
- save_pending(path, data), load_pending(path), mark_applied(path), clear or status transition.
- Atomic write (temp + replace). Missing file → None/empty.

Tests: round-trip; mark_applied; missing file.

Wire: export pending helpers from app/picker/__init__.py; default path via PickerPaths.
```

### Picker Prompt P12 — Soft-rotate plan (diff flags)

```text
You are working in the Python repo autonomous-trade-alerts.

Add pure soft-rotate planning from active vs pending symbol sets.

Create app/picker/soft_rotate.py and tests/test_picker_soft_rotate.py.

Requirements:
- plan_soft_rotate(active_symbols: list[str], pending_symbols: list[str]) -> structure with:
  - kept, added, dropped
  - per-symbol flags for apply: exit_only for dropped, awaiting_first_buy for added, clear flags for kept
- Pure; no file IO.

Tests: {A,B,C} vs {B,C,D} → drop A exit_only, add D awaiting_first_buy, keep B/C; empty pending → all prior exit_only.

Wire: export plan_soft_rotate from app/picker/__init__.py.
```

### Picker Prompt P13 — Active selection store

```text
You are working in the Python repo autonomous-trade-alerts.

Add active_selection.json store holding last applied list + soft-rotate metadata.

Create app/picker/active.py and tests/test_picker_active.py.

Requirements:
- Schema: applied_at, run_id, symbols: list of {symbol, buy_rise, sell_drop, exit_only: bool, awaiting_first_buy: bool, joined_at?}.
- load/save atomic; helpers to set exit_only cleared when flat (function clear_exit_only_if_flat(symbol, shares)) and clear awaiting_first_buy after first buy.

Tests: round-trip; flag updates.

Wire: export active store helpers from app/picker/__init__.py.
```

### Picker Prompt P14 — Apply selection into state_live config

```text
You are working in the Python repo autonomous-trade-alerts.

Apply a pending picker selection into the live config schema under a temp state_live dir.

Create app/picker/apply_live.py and tests/test_picker_apply_live.py.

Requirements:
- Read/write using existing live config patterns (app/live/config.py SymbolParams: buy_rise_pct / sell_drop_pct, symbols list).
- Update symbols + per-asset thresholds from pending (convert fractions ↔ percent to match live schema).
- Preserve unrelated live config fields (mode, trading_enabled, etc.).
- Atomic config write.

Tests: temp state_live gets new symbols/thresholds; unrelated fields preserved.

Wire: export apply_to_live_config from app/picker/__init__.py.
```

### Picker Prompt P15 — Apply selection into paper V1 and V2

```text
You are working in the Python repo autonomous-trade-alerts.

Apply pending picker selection into paper V1 (state/) and V2 (state_v2/) configs/state using existing field names.

Create app/picker/apply_paper.py and tests/test_picker_apply_paper.py.

Requirements:
- Inspect current state/config.json and state_v2/config.json schemas in-repo; update asset lists and buy/sell parameters to match how app/worker.py reads them (do not invent parallel keys).
- Initialize missing per-asset state rows safely without wiping unrelated experiment metadata.
- Works against temp directories in tests (do not mutate committed state fixtures unexpectedly).

Tests: temp V1 and V2 dirs updated; worker-readable keys present.

Wire: export apply_to_paper_v1 and apply_to_paper_v2 from app/picker/__init__.py.
```

### Picker Prompt P16 — Apply orchestrator (atomic multi-target, idempotent)

```text
You are working in the Python repo autonomous-trade-alerts.

Orchestrate Monday apply: pending → soft-rotate plan → live + V1 + V2 + active store; idempotent.

Create app/picker/apply.py and tests/test_picker_apply.py.

Requirements:
- apply_pending_selection(picker_paths, live_paths, v1_paths, v2_paths, now=...) -> result {applied: bool, reason}.
- No-op if no pending, already applied, or status aborted.
- On success: write all targets; update active_selection with flags from plan_soft_rotate; mark pending applied.
- If any target write fails, do not mark applied; surface error (best-effort: prefer validate then write; document).
- First run (no active): treat active as empty; still apply.

Tests: happy path; second call no-op; missing pending no-op; empty pending list applies all-cash (prior symbols exit_only).

Wire: export apply_pending_selection from app/picker/__init__.py.
```

### Picker Prompt P17 — SMA20 gate helper

```text
You are working in the Python repo autonomous-trade-alerts.

Add first-entry trend gate: price must be above 20-hour SMA.

Create app/picker/trend_gate.py and tests/test_picker_trend_gate.py.

Requirements:
- sma(closes, window=20) -> float | None (None if insufficient bars).
- allow_first_buy(closes, price=None) -> bool: True iff last price (or provided price) > SMA20.
- Document: used only while awaiting_first_buy is true.

Tests: below SMA false; above true; <20 bars → false (fail closed).

Wire: export allow_first_buy from app/picker/__init__.py.
```

### Picker Prompt P18 — Equal free-cash sleeve sizing

```text
You are working in the Python repo autonomous-trade-alerts.

Add helper for equal-weight entry using only freed/available cash (no forced rebalance).

Create app/picker/sizing.py and tests/test_picker_sizing.py.

Requirements:
- sleeve_buy_budget(spendable_usd, n_active_non_exit_only, n_already_long) -> float budget for the next BUY among remaining flat actives: spendable / max(1, n_active - n_already_long).
- Integrate cleanly with whole-share sizing already used by live (call existing share sizing if present; otherwise return cash budget only).

Tests: N=3 K=1 → half of spendable; N=1 K=0 → all spendable; zero spendable → 0.

Wire: export sleeve_buy_budget from app/picker/__init__.py.
```

### Picker Prompt P19 — Wire soft-rotate + MA gate + sleeve budget into live_worker

```text
You are working in the Python repo autonomous-trade-alerts.

Integrate picker flags into the live trading cycle without placing orders outside existing planner/risk gates.

Modify app/live_worker.py (and planner if needed) plus tests (extend tests/test_live_worker*.py or add tests/test_live_picker_gates.py).

Requirements:
- Load active_selection (or embedded live state flags) each cycle.
- If symbol exit_only: suppress BUY; allow SELL; when shares hit 0 clear exit_only in store.
- If awaiting_first_buy: require allow_first_buy(hourly closes) before BUY; after successful BUY clear flag.
- On BUY sizing, use sleeve_buy_budget with AvailableFunds/spendable already used by live risk checks.
- Do not remove RTH, idempotency, never-borrow, or dry-run guards.

Tests: exit_only blocks buy; MA gate blocks buy below SMA; budget splits cash; flags clear on fill/flat (use mock broker / existing harness patterns).

Wire: live_worker imports app.picker helpers; no orphan flags.
```

### Picker Prompt P20 — Wire applied symbols + exit_only into paper V1/V2 workers

```text
You are working in the Python repo autonomous-trade-alerts.

Honor picker-applied universes and exit_only in paper workers for consistency with live.

Modify app/worker.py (v1/v2 paths) with tests/test_worker_picker_flags.py (or extend existing worker tests).

Requirements:
- Paper bots trade the applied symbol list from their configs after picker apply.
- If per-asset exit_only (store in state asset row or parallel picker active file readable by worker): suppress BUY, allow SELL, clear when flat.
- awaiting_first_buy + SMA gate should apply to paper too for consistency (reuse allow_first_buy).
- Mid-cycle optimize_params / V2 reopt remains free to overwrite buy/sell % (do not freeze).

Tests: exit_only suppresses buy signal side effects; reopt still changes thresholds on kept names.

Wire: worker reads flags written by apply_to_paper_*; no duplicate conflicting universe sources.
```

### Picker Prompt P21 — Rank orchestration + report artifact + email bodies

```text
You are working in the Python repo autonomous-trade-alerts.

Implement the weekend ranking pipeline (provider-injected) and notification bodies.

Create app/picker/run.py and app/picker/notify.py with tests/test_picker_run.py and tests/test_picker_notify.py.

Requirements:
- run_ranking(as_of, sp500_loader, bar_provider, picker_paths, active_symbols, send_email=False, dry_run=False) -> result:
  1) load S&P list (cache/last-good semantics)
  2) compute windows
  3) fetch_universe_bars
  4) if abort: do NOT overwrite pending; write ranking_runs report; build failure email body; optionally send via app.notifier
  5) else rank_one_symbol each ok name; select_symbols; write pending_selection; write ranking_runs JSON; build success email (selected, edges, adds/drops vs active, skip%, apply reminder); optionally send
- Every successful run writes pending even if selection equals previous (email every run).
- dry_run: write report under ranking_runs but skip pending overwrite if you document a --dry-run that still emails; prefer: dry_run writes report only, no pending change, email subject marks DRY RUN.

Tests: fixture provider tiny universe → pending selected; forced >30% skips → pending unchanged + failure body; email body contains tickers (mock send).

Wire: export run_ranking from app/picker/__init__.py; notify helpers call send_signal_email or existing notifier API.
```

### Picker Prompt P22 — CLI, Monday apply hook, IBKR provider, ops, E2E

```text
You are working in the Python repo autonomous-trade-alerts.

Finish integration: CLI entrypoint, live_worker Monday apply, IBKR bar provider, deploy timer, E2E harness, docs/gitignore.

Implement all of the following with tests where noted; keep each concern in clear modules.

1) CLI: python -m app.picker_rank with flags --dry-run, --as-of (optional), --no-email. Wires run_ranking with IbkrHourlyBarProvider when gateway available; Fixture/env escape hatch for CI.

2) IbkrHourlyBarProvider in app/picker/ibkr_bars.py implementing HourlyBarProvider using existing IbkrBroker.latest_hourly_closes (or ib_insync) with useRTH=True. Unit-test with a mock broker returning bars; no live network required in CI.

3) live_worker: at start of a cycle, if US RTH and pending status is pending and now is on/after apply_after Monday open, call apply_pending_selection once; alert if pending age > 3 days. Tests with temp dirs + frozen time.

4) deploy/ibgateway/picker-rank.service + picker-rank.timer: Saturday 00:00 America/New_York, biweekly (document OnCalendar expression), EnvironmentFile=.env, WorkingDirectory repo. Update deploy/ibgateway/README.md.

5) .gitignore state_picker/ artifacts (keep directory placeholder if useful). Brief README section linking investigation §12 and this blueprint Part II.

6) tests/test_picker_e2e.py: tiny fixture universe → run_ranking → apply_pending_selection on temp state_live/state/state_v2 → assert symbols/thresholds/flags → simulate live gate blocking BUY when below SMA. Runtime fast (<5s).

Do not commit secrets. Leave pytest green including prior live/picker unit tests.
```

---

## 14. After picker prompts (human / ops)

1. Deploy timer on OVH; run one `--dry-run` Saturday (or forced as_of) and review `state_picker/ranking_runs/`.  
2. Enable pending writes; confirm weekend email.  
3. Let Monday `live_worker` apply on **paper** paths first if you stage flags; then live.  
4. Confirm mid-biweek V2 re-opt still overwrites thresholds.  
5. Only then trust live capital soft-rotate with real AvailableFunds.

---

## 15. Definition of done (picker software)

- [ ] Picker Prompts P01–P22 implemented; picker unit + E2E tests green  
- [ ] Existing V1/V2/live tests still green  
- [ ] Weekend rank never places orders; apply only mutates config/state  
- [ ] Soft-rotate + SMA gate + equal free-cash honored in live_worker  
- [ ] Paper V1/V2 receive same universe on apply; exit_only honored  
- [ ] >30% IBKR fail keeps previous list + error email  
- [ ] systemd timer templates + README notes present  
- [ ] `state_picker/` not committing run artifacts  

---

## 16. Prompt map (picker)

| Prompt | Delivers | Wires into |
|--------|----------|------------|
| P01 | PickerPaths | package init |
| P02 | ticker normalize | sp500 loader |
| P03 | Wikipedia + cache | run_ranking |
| P04 | opt/score windows | fetch + rank |
| P05 | after-fee vs B&H | rank_one_symbol |
| P06 | one-symbol optimize+score | select |
| P07 | top ≤5 edge≥0 | run_ranking |
| P08 | >30% abort policy | fetch_universe |
| P09 | bar provider + retries | fetch_universe |
| P10 | batch fetch | run_ranking |
| P11 | pending store | apply + run |
| P12 | soft-rotate plan | apply |
| P13 | active store | workers + apply |
| P14 | apply live config | apply orchestrator |
| P15 | apply V1/V2 | apply orchestrator |
| P16 | apply_pending_selection | live_worker Monday |
| P17 | SMA20 gate | live + paper workers |
| P18 | equal free-cash budget | live_worker BUY |
| P19 | live_worker gates | live cycle |
| P20 | paper worker flags | V1/V2 cycles |
| P21 | run_ranking + email | CLI |
| P22 | CLI, IBKR provider, timer, E2E, docs | production seam |

---

# Part III — Remote portfolio viewer (Streamlit + Tailscale)

Spec source: `docs/live_trading_investigation.md` §13. Evolve `app/dashboard.py`; deploy always-on on OVH; access only via Tailscale. No second IBKR Gateway/Client Portal login.

---

## 17. Remote viewer — what we are building

A **phone/laptop portfolio + health UI** that:

- Runs **always-on** Streamlit on the **OVH** host (`systemd`).
- Is reachable only over **Tailscale** (bind not on the public NIC).
- Shows **tabs**: Live | Paper V1 | Paper V2 | Picker.
- Leads with a **health strip**, then money/positions.
- **Manual refresh** only (no auto-poll).
- Marks from **state files + IBKR API** using a **dedicated client id** (default 9).
- Allows **safe controls only**: trading enable/disable + risk ack — **not** mode changes.
- Evolves existing `app/dashboard.py` (not a second app).

---

## 18. Remote viewer architecture (target)

```
Tailscale devices → OVH Tailscale IP :8501
  └── streamlit-dashboard.service
        └── streamlit run app/dashboard.py
              ├── state_live / state / state_v2 / state_picker
              ├── IbkrBroker(client_id=9) for optional marks/snapshot
              └── live control helpers (trading_enabled, risk ack)
```

---

## 19. Remote viewer chunking

### Round 1
1. Read models for live/paper/picker status (pure)  
2. Health strip + Live tab layout  
3. Paper + picker tabs  
4. Safe controls + IBKR marks client  
5. systemd + Tailscale bind docs  

### Round 2 → right size
→ Prompts **D01–D08** below.

---

## 20. Remote viewer prompting conventions

- Spec §13 is source of truth; do not re-open hosting (OVH+Tailscale) or control scope.
- Prefer extracting small helpers under `app/dashboard_*.py` or `app/remote/` if `dashboard.py` is already huge — but **one Streamlit entrypoint**.
- Tests first; no IBKR required for pure read/render helpers (fake snapshots).
- Never instruct logging into Client Portal / second Gateway.

---

## 21. Remote viewer implementation prompts

### Dashboard Prompt D01 — status snapshot models

```text
You are working in the Python repo autonomous-trade-alerts.

Add pure helpers (new module OK, e.g. app/remote/status.py) that build dashboard snapshots from on-disk state without Streamlit:

- load_live_status(state_live_dir) → mode, trading_enabled, cash, positions, last_cycle summary, risk incident
- load_paper_status(state_dir) → cash, positions, basic last prices if present
- load_picker_status(state_picker_dir) → active symbols/flags, pending present?, latest ranking_runs meta (run_id, aborted, selected symbols if easy)

Add tests/test_remote_status.py using temp dirs + fixture JSON. No IBKR. Keep <2s.
```

### Dashboard Prompt D02 — health strip helpers

```text
You are working in the Python repo autonomous-trade-alerts.

Add helpers that produce a health strip dict for the remote dashboard:

- Inputs: live last_cycle.json (age), optional gateway-health log tail or a small status JSON if already written by ops scripts, trading_enabled, open risk incident, mode
- Outputs: booleans/labels suitable for UI: worker_fresh, rth_ok, mode, trading_on, risk_open, price_source, stale_minutes

Fail soft if optional health files missing. Tests with fixtures in tests/test_remote_health.py.
```

### Dashboard Prompt D03 — Live tab UI (evolve dashboard)

```text
You are working in the Python repo autonomous-trade-alerts.

Evolve app/dashboard.py toward the §13 remote viewer Live tab:

- Top: health strip (D02)
- Then: cash, positions table (symbol, shares, mark, peak/trough or flags)
- Then: last cycle decisions
- Manual refresh only (Streamlit rerun / refresh button — no timers)
- Mobile-friendly: single column; avoid dense multi-column chrome

Keep existing paper/lab features from breaking; prefer tabs structure starting here. Add/adjust tests if any dashboard pure helpers are extracted. Do not add mode selectors on this tab.
```

### Dashboard Prompt D04 — Paper V1 / V2 tabs

```text
You are working in the Python repo autonomous-trade-alerts.

In app/dashboard.py add/complete tabs for Paper V1 (state/) and Paper V2 (state_v2/) using D01 loaders:

- Cash, positions, last price if available
- Short note that these are file-sim paper, not IBKR paper account

Preserve any existing paper charts behind expanders if already present. Tests for loaders only unless UI is unit-testable.
```

### Dashboard Prompt D05 — Picker tab

```text
You are working in the Python repo autonomous-trade-alerts.

Add Picker tab to app/dashboard.py:

- Active selection (symbols, exit_only, awaiting_first_buy, buy/sell %)
- Pending present? apply_after if available
- Latest ranking run summary from state_picker/ranking_runs/ (run_id, aborted, selected list)

Read-only. Tests for ranking_runs meta parsing in tests/test_remote_status.py or test_remote_picker_tab.py.
```

### Dashboard Prompt D06 — Safe controls only

```text
You are working in the Python repo autonomous-trade-alerts.

Wire Live-tab safe controls only (investigation §13 / Q7.3):

- Enable / disable trading (existing live control helpers)
- Ack open risk incident
- Do NOT expose mode changes (broker_paper / live_dry_run / live) on the remote UI

Add tests that control helpers still work; if UI test harness lacks Streamlit, test the underlying control functions. Document in a short comment that mode changes remain SSH/ops.
```

### Dashboard Prompt D07 — IBKR marks via dedicated client id

```text
You are working in the Python repo autonomous-trade-alerts.

Add optional mark refresh for the Live tab:

- Use IbkrBroker with client id from env DASHBOARD_IB_CLIENT_ID default 9 (must not default to 1 or 7)
- On manual refresh, if IBKR reachable, overlay last prices / account snapshot cash; if not, keep file marks and show “marks=files”
- Never call Client Portal; never start Gateway

Unit-test client id default and fallback-to-files path with fakes (no real IBKR).
```

### Dashboard Prompt D08 — systemd + Tailscale deploy docs

```text
You are working in the Python repo autonomous-trade-alerts.

Add deploy artifacts and docs for always-on remote dashboard:

- deploy/ibgateway/streamlit-dashboard.service (or deploy/streamlit/) — User=ubuntu, WorkingDirectory=/opt/autonomous-trade-alerts, venv streamlit, bind address via env (Tailscale IP or 127.0.0.1 — document both; do not recommend 0.0.0.0 on public NIC)
- Update deploy/ibgateway/README.md: install Tailscale on VPS + phone/laptop; enable streamlit-dashboard.service; open http://<tailscale-ip>:8501; client id 9 note
- Update docs/live_trading_todo.md Phase K boxes as appropriate when done
- Brief README.md note under Important notes

No secrets in git. Keep instructions free (Tailscale personal).
```

---

## 22. Remote viewer definition of done

- [ ] D01–D08 implemented; pytest green for new remote helpers  
- [ ] Dashboard tabs: Live / Paper V1 / Paper V2 / Picker  
- [ ] Health strip first; manual refresh; safe controls only  
- [ ] IBKR marks use client id ≠ worker/picker defaults  
- [ ] systemd unit + Tailscale docs present; not bound to public WAN by default  
- [ ] No guidance to log into IBKR to “check portfolio”  

---

## 23. Prompt map (remote viewer)

| Prompt | Delivers | Wires into |
|--------|----------|------------|
| D01 | Status loaders | all tabs |
| D02 | Health strip model | Live tab top |
| D03 | Live tab UI | dashboard.py |
| D04 | Paper tabs | dashboard.py |
| D05 | Picker tab | dashboard.py |
| D06 | Safe controls | Live tab |
| D07 | IBKR marks client 9 | Live refresh |
| D08 | systemd + Tailscale docs | OVH ops |
