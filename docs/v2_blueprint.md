# V2 Blueprint: Parallel Bot Experiment

This document is the source of truth for building V2 alongside V1.  
Use with `docs/v2_todo.md` for step-by-step execution and tests.

---

## Goal

Run **V1 (control)** and **V2 (improved optimizer)** in parallel for **10 weeks**, then compare results.

- V1 logic stays frozen in `state/`
- V2 logs to `state_v2/` with a smarter two-level optimizer
- No per-trade emails for either version
- Weekly summary email (Saturday morning) + conclusion email at week 10

---

## Design decisions (locked)

| Topic | Decision |
|-------|----------|
| V2 starting state | Copy `config.json`, fresh positions and empty CSV logs (Option C) |
| Code structure | One worker, `--version v1` / `--version v2` (Option A) |
| V2 optimizer | All 3 fixes on day one: constraints, trade penalty, holdout validation |
| Meta-parameters | Level 2 walk-forward every ~4 weeks; not hardcoded (Option B) |
| Meta scope | Global λ + holdout split; per-symbol vol-scaled floors (Option C) |
| Per-trade email | Off for both V1 and V2 |
| Weekly email | Saturday morning, returns + per-symbol + trades + re-opt events |
| Conclusion email | Week 10, extended weekly format with winner paragraph |
| Dashboard | Version toggle + Compare tab |
| V2 start date | Deploy day |
| Experiment length | 10 weeks |

---

## Architecture

```
                    ┌─────────────────────────────────────┐
                    │     GitHub Actions (every 10m)      │
                    └─────────────────────────────────────┘
                           │                    │
              python -m app.worker      python -m app.worker
                   --version v1              --version v2
                           │                    │
                     ┌─────▼─────┐        ┌─────▼─────┐
                     │  state/   │        │ state_v2/ │
                     │  (V1)     │        │  (V2)     │
                     └───────────┘        └───────────┘
                           │                    │
                     optimize_params      optimize_params_v2
                     (unchanged)          + meta config from
                                          config.meta / meta_history

     ┌──────────────────────────────────────────────────────────┐
     │  Saturday cron: app/weekly_report.py                     │
     │  Reads state/ + state_v2/ → one summary email            │
     └──────────────────────────────────────────────────────────┘
```

### Two-level optimization (V2 only)

| Level | Schedule | Picks | Logged to |
|-------|----------|-------|-----------|
| **L1** Threshold | ~every `reopt_days` (5) | `buy_rise_pct`, `sell_drop_pct` | `params_history.csv` |
| **L2** Meta | ~every 4 weeks | λ, holdout split, base floor/cap; vol scale per symbol | `meta_history.csv` |

**L1 rules (V2):**
1. Grid search with **constraints** (floor, cap, asymmetry from L2 + vol scale)
2. Score = `simulated_P/L − λ × round_trips`
3. **Holdout validation**: train on first ~15 days, validate on last ~5 of `x_days`; apply only if holdout beats current params; else log `rejected`

**L2 rules:**
- Walk-forward simulation on **8 weeks** of hourly data
- Grid over candidate meta configs (λ, base_floor, max_buy, train/validate split)
- Score = return − trade penalty − drawdown penalty
- Winner written to `config.json` under `meta` key until next L2 run

**Vol scaling (per symbol at L1):**
```
symbol_floor = base_floor × (symbol_vol / median_vol)
clamped to [min_floor, max_floor]
```

---

## Directory layout (new / changed)

```
app/
  worker.py              # refactor: version flag, state dir routing
  strategy.py            # add optimize_params_v2, count_round_trips, constrained grid
  meta_optimizer.py      # NEW: Level 2 walk-forward
  paths.py               # NEW: resolve state dir + file paths by version
  weekly_report.py       # NEW: Saturday summary + week-10 conclusion
  notifier.py            # optional: send_weekly_email helper
  dashboard.py           # version toggle + Compare tab

state/                   # V1 only — do not change optimizer behavior
state_v2/                # NEW: V2 logs (git tracked)
  config.json            # copy from state/config.json + meta block + experiment_start
  state.json
  trades.csv
  equity.csv
  params_history.csv     # L1 log (+ status: applied | rejected)
  meta_history.csv       # L2 log

tests/                   # NEW
  test_strategy_v1.py    # regression: V1 optimizer unchanged
  test_strategy_v2.py    # constraints, penalty, holdout
  test_meta_optimizer.py
  test_paths.py
  test_worker_versions.py
  test_weekly_report.py
  fixtures/              # synthetic price arrays, sample state files

docs/
  v2_blueprint.md        # this file
  v2_todo.md             # execution checklist

.github/workflows/
  hourly.yml             # run v1 + v2 workers; commit both state dirs
  weekly.yml             # NEW: Saturday summary email
```

---

## Config schema additions (V2)

`state_v2/config.json` extends V1 config:

```json
{
  "initial_cash": 1000.0,
  "alerts_enabled": false,
  "experiment_start": "2026-09-03T00:00:00Z",
  "experiment_weeks": 10,
  "meta": {
    "last_meta_at": null,
    "meta_reopt_days": 28,
    "lambda_per_trip": 10.0,
    "base_floor_pct": 2.0,
    "max_buy_pct": 8.0,
    "train_days": 15,
    "validate_days": 5,
    "simulation_weeks": 8
  },
  "assets": [ ... same as V1 ... ]
}
```

`params_history.csv` V2 columns (add):
- `status` (`applied` | `rejected`)
- `reject_reason` (optional string)
- `validate_final_value`

`meta_history.csv` columns:
- `Datetime`, `lambda_per_trip`, `base_floor_pct`, `max_buy_pct`, `train_days`, `validate_days`, `simulation_score`

---

## V1 isolation rules (critical)

1. **Never import V2 optimizer from V1 code path** — `version=v1` must call `optimize_params` only
2. **Never write to `state/` from V2 worker**
3. **Add regression tests** that snapshot V1 `optimize_params` output on fixed price arrays before any refactor
4. **Feature flag**: `config.alerts_enabled = false` in both configs when disabling per-trade email
5. **GitHub Actions**: V1 step runs first; if V1 fails, do not run V2 (or run both but fail the job — pick: fail fast on V1)

---

## Email behavior

| Event | V1 | V2 |
|-------|----|----|
| Per-trade BUY/SELL | Off | Off |
| Weekly summary (Sat AM) | Included | Included |
| Week 10 conclusion | Included | Included |

Weekly email sections (Option B):
- Period (last 7 days)
- Portfolio return: V1 vs V2 vs buy-and-hold
- Per-symbol table
- Trades this week (count per symbol)
- Re-opt events (applied/rejected for V2)
- Since experiment start: who is ahead

Conclusion email (Option A):
- Full 10-week totals
- Same tables as weekly, whole window
- One paragraph: winner + margin

---

## Dashboard (phase 7)

- Sidebar: **Version** selectbox (`v1` | `v2`)
- Load paths from `app/paths.py` based on selection
- New **Compare** tab:
  - Side-by-side portfolio return since `experiment_start`
  - Per-symbol return table (V1 vs V2 vs B&H)
  - Optional: overlay equity curves for selected symbol

---

## Testing strategy

**Principle:** every phase ships with tests before moving on. No network in unit tests (mock `download_hourly`).

| Layer | Tool | What |
|-------|------|------|
| Unit | `pytest` | strategy, meta optimizer, paths, report formatting |
| Integration | `pytest` + temp dirs | worker writes correct files per version |
| Regression | fixed numpy fixtures | V1 optimizer output unchanged |
| Manual | `workflow_dispatch` | one GitHub Actions run on branch before merge |

Add to `requirements.txt` (dev):
```
pytest
```

Run before each phase merge:
```bash
python -m pytest tests/ -v
```

---

## Rollback plan

| Problem | Action |
|---------|--------|
| V2 worker breaks | Disable V2 step in `hourly.yml`; V1 unaffected |
| Bad V2 state | Delete `state_v2/`, re-bootstrap from `state/config.json` |
| Email spam / bugs | Disable `weekly.yml` workflow |
| Meta optimizer overfits | Widen holdout, reduce meta grid, extend `meta_reopt_days` |

---

## Success criteria (week 10)

- [ ] 10 weeks of clean logs in both `state/` and `state_v2/`
- [ ] V2 rejected at least one bad re-opt (logged in `params_history.csv`)
- [ ] No V1 behavior regression (return path within noise vs pre-deploy baseline optional)
- [ ] Comparison report: portfolio + per-symbol, same format as V1 newsletter
- [ ] Conclusion email sent automatically

---

## Out of scope for V2.0

- Real brokerage orders
- Per-symbol meta optimizer (7 separate L2 grids)
- Intraday re-opt faster than 5 days
- HTML email with embedded charts (plain text first)

---

## References

- V1 analysis: `analysis/newsletter.md`
- V1 optimizer: `app/strategy.py` → `optimize_params`
- V1 worker: `app/worker.py` → `_reoptimize_if_due`
- Walk-forward research: `walkforward_optimize.py`, `select_best_x_days`
