# Live Trading Blueprint (TDD Prompt Series)

**Status:** v2 — prompt-driven build plan (2026-09-23)  
**Decisions:** `docs/live_trading_investigation.md`  
**Tracking:** `docs/live_trading_todo.md`  
**Repo:** `autonomous-trade-alerts` (extend in place; keep paper V1/V2)

Not legal/tax advice.

---

## 1. What we are building

A **fee- and platform-aware live trading variant** of the existing peak/trough bot that:

- Places **fully automatic market orders** via **IBKR Canada** (IB Gateway + IBC/IBeam + Python).
- Competes with **equal-weight buy-and-hold** of the live universe **after all fees**.
- Starts at ~**USD 1,000** total across **MSFT, AAPL, SMH**.
- Runs on **one Oracle Always Free VM** with paper V1/V2 + live in one place.
- Modes: `sim` → `broker_paper` → `live_dry_run` → `live`.
- Risk: per-order never-borrow / RTH / idempotency; threshold **alert → 2h no ack → stop**.
- UX: Streamlit dashboard (mode, disable, ack) + email alerts.

Existing code to preserve: `app/strategy.py`, `app/worker.py` (`--version v1|v2`), `state/`, `state_v2/`, `app/dashboard.py`, `app/notifier.py`.

---

## 2. Architecture (target)

```
Oracle VM
├── IB Gateway + IBC/IBeam (localhost API)
├── python -m app.worker --version v1|v2          # paper sim (unchanged behavior)
├── python -m app.live_worker --mode …           # live variant
├── streamlit run app/dashboard.py
├── state/  state_v2/  state_live/  logs/audit/
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

1. Provision Oracle Always Free VM; SSH harden.  
2. Install IB Gateway + IBC/IBeam; paper login.  
3. Run `broker_paper` two weeks; graduation checklist.  
4. `live_dry_run` on funded account.  
5. `live` with ~$1k after confirm env.  
6. Close research R1–R9 with findings in the investigation doc.

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

- `docs/live_trading_investigation.md` — locked product decisions  
- `docs/live_trading_todo.md` — checklist mapped to these prompts  
- `docs/v2_blueprint.md` — paper V2 experiment (unchanged)  
