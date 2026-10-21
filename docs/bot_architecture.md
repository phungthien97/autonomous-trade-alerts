# How the bot works

A map of the whole system: what runs where, how a trade decision is made, and how the S&P picker feeds sleeves into live + paper.

**Audience:** you (operator), not an implementer checklist.  
**Code truth:** `app/` on OVH under `/opt/autonomous-trade-alerts`.  
**Companion docs:** investigation (decisions), blueprint (build prompts), todo (ops checklist).

---

## 1. Big picture

Three kinds of processes share one OVH host and one IB Gateway:

| Process | How often | Job |
|---------|-----------|-----|
| **Live worker** | ~every 5 min (`live-worker.timer`) | Prices → signals → (maybe) IBKR orders for the live book |
| **Paper V1 / V2 workers** | ~every 10 min (legacy / GHA or host cron) | Same peak/trough idea in **file-sim** books; alerts only, no IBKR orders |
| **Picker rank** | Biweekly Sat (`picker-rank.timer`) | Score S&P names → write `pending_selection.json` for Monday |
| **Dashboard** | Always on (`streamlit-dashboard.service`) | Tailscale viewer + safe controls (enable/disable/ack) |

```mermaid
flowchart TB
  subgraph Host["OVH host"]
    GW["IB Gateway :4002 paper / :4001 live"]
    LW["live_worker<br/>every ~5m"]
    PR["picker_rank<br/>biweekly Sat"]
    Dash["Streamlit dashboard<br/>Tailscale only"]
    W1["worker V1<br/>state/"]
    W2["worker V2<br/>state_v2/"]
  end

  PR -->|"pending_selection.json"| LW
  LW -->|"apply Mon RTH"| LiveCfg["state_live/config.json"]
  LW -->|"apply Mon RTH"| W1
  LW -->|"apply Mon RTH"| W2
  LW <-->|"prices + orders"| GW
  Dash -.->|"read status / marks client 9"| GW
  Dash -->|"read"| LiveCfg
  Dash -->|"read"| PR
  W1 -.->|"yfinance prices"| Net["Yahoo"]
  W2 -.->|"yfinance prices"| Net
```

**Mental model:** the **strategy** decides *when* to buy/sell a symbol. The **picker** decides *which* symbols get a sleeve. The **live worker** is the only path that can hit IBKR.

---

## 2. The core trading idea (peak / trough)

Every sleeve (live or paper) tracks one symbol with cash **or** shares (all-in / all-out).

```mermaid
stateDiagram-v2
  [*] --> Flat: start / after SELL
  Flat --> Long: BUY when price ≥ trough × (1 + buy_rise)
  Long --> Flat: SELL when price ≤ peak × (1 − sell_drop)

  note right of Flat
    While flat: trough = running low
  end note
  note right of Long
    While long: peak = running high
  end note
```

| Term | Meaning |
|------|---------|
| **trough** | Lowest price seen while flat (cash) |
| **buy_rise** | How far price must bounce off the trough to BUY (e.g. 2% → `0.02`) |
| **peak** | Highest price seen while long (shares) |
| **sell_drop** | How far price must fall off the peak to SELL |

Implemented in `app/strategy.py` → `step_signal()`.

On each bar the strategy only answers: **BUY**, **SELL**, or **no signal**. It does **not** size the order or talk to the broker.

---

## 3. Live decision path (one cycle)

Entry: `python -m app.live_worker` → `run_live_once()` in `app/live_worker.py`.

```mermaid
flowchart TD
  Start([Timer fires]) --> Risk{"Trading enabled?<br/>risk.json + config"}
  Risk -->|no| Stop([Skip cycle])
  Risk -->|yes| RTH{"US equity RTH?<br/>09:30–16:00 ET"}
  RTH --> Apply["maybe_apply_pending<br/>Mon open + apply_after"]
  Apply --> Recon["reconcile local sleeves<br/>vs broker positions/cash"]
  Recon --> Prices["IBKR RTH hourly closes<br/>(Yahoo fallback)"]
  Prices --> Loop["For each enabled symbol"]

  Loop --> Sig["step_signal<br/>BUY / SELL / none"]
  Sig --> Gates{"Gates"}
  Gates -->|"BUY + exit_only"| Block1["Cancel BUY<br/>keep updating trough"]
  Gates -->|"BUY + awaiting_first_buy<br/>and price ≤ SMA20"| Block2["Cancel BUY<br/>fail-closed if &lt;20 bars"]
  Gates -->|pass| Plan["plan_from_signal<br/>qty + fees + never-borrow"]
  Plan --> Cap["BUY budget =<br/>sleeve_buy_budget<br/>equal free cash"]
  Cap --> Exec["execute_intent"]

  Exec --> Idem{"Already done<br/>this symbol+bar+side?"}
  Idem -->|yes| Skip[skipped]
  Idem -->|no + outside RTH| Queue[queue.json for next RTH]
  Idem -->|no + sim / live_dry_run| Dry[audit dry_run only]
  Idem -->|no + broker_paper / live| Order["BrokerGateway → IBKR<br/>market order"]

  Order --> Risk2{"reject storm / max orders?"}
  Risk2 -->|yes| Incident["Open risk incident<br/>auto-stop in 2h if no ack"]
  Risk2 --> Persist["Update state, equity.csv,<br/>audit, last_cycle.json, email"]
```

### Per-symbol gates (live only)

| Gate | When | Effect |
|------|------|--------|
| **exit_only** | Symbol dropped by picker soft-rotate | Blocks new BUY; SELL still allowed |
| **SMA20 first buy** | Symbol newly added (`awaiting_first_buy`) | BUY only if last price **>** 20-hour SMA; fail closed if not enough bars |
| **Never-borrow** | Planning a BUY | Qty reduced / rejected if notional + fees > `AvailableFunds` (BuyingPower ignored) |
| **Whole shares** | IBKR US stocks | `allow_fractional_default=false`; qty floored to integers |
| **Idempotency** | Same symbol + bar timestamp + side | At most one live attempt |
| **RTH** | Outside regular session | Intent goes to `queue.json`, not the broker |

### Modes (`state_live/config.json` → `TradingMode`)

| Mode | Places IBKR orders? |
|------|---------------------|
| `sim` | No |
| `live_dry_run` | No (audit only) |
| `broker_paper` | Yes → paper Gateway **4002** |
| `live` | Yes → live Gateway **4001**, only if `LIVE_TRADING_CONFIRM=YES` |

Guard: `app/broker/gateway.py` (`BrokerGateway`).

---

## 4. How a BUY quantity is chosen

```mermaid
flowchart LR
  Sig[BUY signal] --> Budget["spendable = min(IBKR AvailableFunds, book total_cash)"]
  Budget --> Split["sleeve_buy_budget =<br/>spendable / remaining flat active sleeves"]
  Split --> Qty["whole-share qty = floor(budget / price)"]
  Qty --> Fees["estimate IBKR Tiered fees"]
  Fees --> Borrow{"would create debit?"}
  Borrow -->|yes| Shrink[shrink qty or abort]
  Borrow -->|no| Intent[OrderIntent]
```

There is **no forced Monday rebalance**. Existing longs stay until a SELL signal; new names buy only when their BUY fires and cash is free.

---

## 5. S&P picker — choosing sleeves

Entry: `python -m app.picker_rank` → `run_ranking()` in `app/picker/run.py`.

### Pipeline

```mermaid
flowchart TD
  Wiki["Wikipedia S&P 500<br/>+ name/sector cache"] --> Bars["IBKR hourly closes<br/>per symbol"]
  Bars --> Fail{">30% fetch fail?"}
  Fail -->|yes| Abort["ABORT email<br/>keep previous pending"]
  Fail -->|no| Win["Windows<br/>optimize = prior 1 week<br/>score = latest 1 month"]
  Win --> Opt["Per symbol:<br/>grid-search buy_rise/sell_drop<br/>on optimize window"]
  Opt --> Score["Replay those thresholds<br/>on score window<br/>after estimated fees vs B&H"]
  Score --> Select["Hybrid B select<br/>edge ≥ 0 and strategy ≥ 0<br/>rank by strategy_return<br/>top ≤ 5"]
  Select --> Pending["pending_selection.json<br/>apply_after = next Mon 09:30 ET"]
  Pending --> Mail["Picker email"]
```

| Metric | Meaning |
|--------|---------|
| **strategy_return** | After-fee peak/trough P&amp;L on the score window |
| **bh_return** | After-fee buy-and-hold on the same window |
| **edge** | `strategy_return − bh_return` (must be ≥ 0 to qualify) |

Select logic: `app/picker/rank.py` → `select_symbols()`.

### Monday apply (soft rotate)

When `live_worker` sees RTH **and** `now ≥ apply_after`:

```mermaid
flowchart TD
  P["pending symbols"] --> Diff["plan_soft_rotate vs active"]
  Diff --> Keep["Kept: normal trading"]
  Diff --> Add["Added: awaiting_first_buy<br/>SMA20 before first BUY"]
  Diff --> Drop["Dropped: exit_only<br/>no new BUY; sell when signal fires"]
  Keep --> Write["Write live + V1 + V2 configs<br/>+ active_selection.json<br/>mark pending applied"]
  Add --> Write
  Drop --> Write
```

Files: `app/picker/apply.py`, `soft_rotate.py`, `apply_live.py`, `apply_paper.py`.

---

## 6. Paper V1 vs V2 (brief)

Both use the same peak/trough `step_signal`. Differences:

| | **V1** (`state/`) | **V2** (`state_v2/`) |
|--|-------------------|----------------------|
| Optimizer | Unconstrained grid on trailing window | Constrained grid + trip penalty (`meta_optimizer` / `optimize_params_v2`) |
| Broker | None — file cash/shares only | Same |
| Picker | Soft-rotate flags honored in `worker.py` | Same |
| Purpose | Baseline paper experiment | Constrained / fee-aware paper experiment |

Live is **not** a copy of V2: it adds IBKR, fees at order time, never-borrow, RTH, idempotency, and picker gates.

---

## 7. State map (what lives where)

```mermaid
flowchart LR
  subgraph live["state_live/"]
    LC[config.json]
    LS[state.json]
    LA[audit/]
    LQ[queue.json]
    LI[idempotency.json]
    LR[risk.json]
    LL[last_cycle.json]
  end

  subgraph picker["state_picker/"]
    PC[sp500_cache.json]
    PP[pending_selection.json]
    PA[active_selection.json]
    PR[ranking_runs/*.json]
  end

  subgraph paper["state/ and state_v2/"]
    C[config.json]
    S[state.json]
    T[trades.csv]
    E[equity.csv]
  end

  PP -->|"Mon apply"| LC
  PP -->|"Mon apply"| C
  PA -->|"flags"| live
```

| Path | Role |
|------|------|
| `state_live/config.json` | Mode, symbols, buy/sell %, `total_cash`, alerts |
| `state_live/state.json` | Per-symbol cash/shares/peak/trough; orders_today; reject_streak |
| `state_live/risk.json` | `trading_enabled` + open incident |
| `state_picker/pending_selection.json` | Weekend slate waiting for Monday |
| `state_picker/active_selection.json` | Soft-rotate flags after apply |

---

## 8. Risk and alerts

```mermaid
flowchart TD
  Event["Fill / reject / disconnect /<br/>picker apply / risk"] --> Notify["app/notifier.py<br/>Gmail SMTP"]
  Reject["3 rejects in a row<br/>or &gt;6 orders/day"] --> Open["RiskController.trigger"]
  Open --> Wait["2 hours without ack"]
  Wait --> Kill["trading_enabled = false<br/>worker skips cycles"]
  Dash["Dashboard Ack risk"] --> Clear["Clear incident"]
```

Disconnect emails are cooldown-suppressed (~6h) so Gateway flaps do not spam.

---

## 9. Invariants (do not break these)

1. **Whole shares** on IBKR — no fractional API orders.  
2. **Never borrow** — buys sized to `AvailableFunds`, not BuyingPower.  
3. **All-in / all-out per sleeve** — not partial target weights.  
4. **No forced Monday rebalance** — picker soft-rotates; sells wait for signals.  
5. **Picker abort** if &gt;30% IBKR bar fetches fail — previous pending kept.  
6. **Hybrid B** — sleeve must beat B&amp;H **and** make money; ranked by strategy profit.  
7. **Live money** only after G3 graduation + explicit `LIVE_TRADING_CONFIRM=YES`.

---

## 10. Typical week (ops story)

```mermaid
sequenceDiagram
  participant Sat as Saturday
  participant Mon as Monday RTH
  participant Day as Weekdays
  participant Dash as Dashboard

  Sat->>Sat: picker_rank scores S&P
  Sat->>Sat: writes pending + email
  Note over Sat: apply_after = Mon 09:30 ET

  Mon->>Mon: live_worker first RTH cycle
  Mon->>Mon: apply pending → live + V1 + V2
  Mon->>Dash: "New sleeves applied" email
  Mon->>Mon: soft-rotate flags active

  Day->>Day: every ~5m: prices → signals → orders
  Day->>Dash: fills / rejects / health
  Note over Day: mid-biweek V1/V2 may re-opt % only<br/>does not change which symbols
```

---

## 11. Where to read next in code

| Question | Start here |
|----------|------------|
| When do we BUY/SELL? | `app/strategy.py` → `step_signal` |
| Live cycle orchestration | `app/live_worker.py` → `run_live_once` |
| Order sizing / never-borrow | `app/live/planner.py`, `app/live/risk_limits.py` |
| Submit vs dry-run | `app/live/executor.py`, `app/broker/gateway.py` |
| Which stocks? | `app/picker/run.py`, `app/picker/rank.py` |
| Soft rotate | `app/picker/soft_rotate.py`, `app/picker/apply.py` |
| First-buy SMA | `app/picker/trend_gate.py` |
| Equal cash sleeves | `app/picker/sizing.py` |
| Paper loop | `app/worker.py` |
| Remote UI | `app/dashboard.py`, `app/remote/ui.py` |

---

*Generated from the codebase as of the Hybrid B picker + money-first dashboard work. If behavior and this doc disagree, trust the code and update this file.*
