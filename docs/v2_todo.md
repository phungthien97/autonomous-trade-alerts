# V2 Build Checklist

Work top to bottom. **Do not start the next phase until all tests pass.**

Mark items `[x]` as completed. Update this file during the build.

---

## Phase 0: Test infrastructure

**Goal:** pytest in place; V1 baseline locked before any production code changes.

| # | Task | Files |
|---|------|-------|
| 0.1 | Add `pytest` to `requirements.txt` (or `requirements-dev.txt`) | `requirements.txt` |
| 0.2 | Create `tests/` and `tests/fixtures/` | new dirs |
| 0.3 | Add `tests/fixtures/prices_flat.py` — synthetic arrays (uptrend, downtrend, chop) | fixture |
| 0.4 | Add `tests/test_strategy_v1_regression.py` — snapshot V1 `optimize_params` + `step_signal` on fixtures | test |
| 0.5 | Add `tests/test_paths.py` stub (will implement in Phase 1) | test |

**Tests:**
```bash
python -m pytest tests/test_strategy_v1_regression.py -v
```
**Acceptance:**
- [x] All V1 regression tests pass
- [x] Documented expected outputs for 3 fixture price series (buy/sell counts, best params)

---

## Phase 1: Paths + worker versioning (no V2 logic yet)

**Goal:** `python -m app.worker --version v1` behaves exactly as today; `--version v2` writes to `state_v2/`.

| # | Task | Files |
|---|------|-------|
| 1.1 | Create `app/paths.py` — `get_state_dir(version)`, paths for config/state/csvs | new |
| 1.2 | Refactor `worker.py` to use `paths.py`; add `--version` argparse (`v1` default) | `worker.py` |
| 1.3 | Bootstrap `state_v2/`: copy `config.json`, empty CSV headers, minimal `state.json` | `state_v2/*` |
| 1.4 | Add `experiment_start` to `state_v2/config.json`; set `alerts_enabled: false` in both configs | config |
| 1.5 | Disable per-trade email in worker (remove or gate `send_signal_email` behind flag default false) | `worker.py` |

**Tests:**
```bash
python -m pytest tests/test_paths.py tests/test_worker_versions.py -v
```

**Acceptance:**
- [x] `python -m app.worker --version v1` identical behavior to pre-refactor
- [x] `python -m app.worker --version v2` creates files only under `state_v2/`
- [x] No per-trade emails sent when `alerts_enabled: false`
- [x] V1 regression tests still pass

---

## Phase 2: V2 strategy core (optimize_params_v2)

**Goal:** L1 optimizer with constraints, trade penalty, holdout validation — **unit tested, not wired to worker yet**.

| # | Task | Files |
|---|------|-------|
| 2.1 | Add `count_round_trips(prices, buy, sell)` to `strategy.py` | `strategy.py` |
| 2.2 | Add `build_constrained_grid(meta, symbol_vol, median_vol)` | `strategy.py` |
| 2.3 | Add `optimize_params_v2(train, validate, current, meta, initial_cash)` → buy, sell, score, accepted, reason | `strategy.py` |
| 2.4 | Constraints: floor, cap, sell ≥ buy/2 | `strategy.py` |
| 2.5 | Score: `P/L − λ × round_trips` | `strategy.py` |
| 2.6 | Holdout: reject if validate score ≤ current params validate score | `strategy.py` |

**Tests:** `tests/test_strategy_v2.py`

**Acceptance:**
- [x] All V2 strategy tests pass
- [x] V1 regression tests still pass (no changes to `optimize_params`)

---

## Phase 3: Wire V2 optimizer into worker

**Goal:** V2 worker uses `optimize_params_v2`; logs applied/rejected to `params_history.csv`.

| # | Task | Files |
|---|------|-------|
| 3.1 | Split `_reoptimize_if_due` → `_reoptimize_v1` / `_reoptimize_v2` or pass version flag | `worker.py` |
| 3.2 | V2: split `x_days` into train/validate per meta config | `worker.py` |
| 3.3 | V2: compute symbol vol + median vol from train window | `worker.py` |
| 3.4 | Extend `params_history.csv` schema for V2 (status, reject_reason) | `worker.py` |
| 3.5 | Wire `version=v2` branch in `run_once()` | `worker.py` |

**Tests:** `tests/test_worker_v2_reopt.py`

**Acceptance:**
- [x] Local: `python -m app.worker --version v2` completes without error
- [x] `state_v2/params_history.csv` has rows with status column
- [x] V1 regression + all prior tests pass

---

## Phase 4: Meta optimizer (Level 2)

**Goal:** Every ~4 weeks, walk-forward simulation picks global meta params.

| # | Task | Files |
|---|------|-------|
| 4.1 | Create `app/meta_optimizer.py` | new |
| 4.2 | `run_meta_if_due(config, state_dir, now)` — check `meta.last_meta_at` vs `meta_reopt_days` | `meta_optimizer.py` |
| 4.3 | Walk-forward grid over λ, base_floor, max_buy, train/validate split | `meta_optimizer.py` |
| 4.4 | Score: return − trip penalty − drawdown penalty | `meta_optimizer.py` |
| 4.5 | Write winner to `config.meta`; log `meta_history.csv` | `meta_optimizer.py` |
| 4.6 | Call from V2 worker at start of `run_once()` | `worker.py` |

**Tests:** `tests/test_meta_optimizer.py`

**Acceptance:**
- [x] Meta re-opt runs when `last_meta_at` is null or stale
- [x] `state_v2/meta_history.csv` populated
- [x] L1 uses updated meta on subsequent re-opts

---

## Phase 5: GitHub Actions (dual workers)

**Goal:** CI runs V1 + V2 every 10 minutes; commits both state dirs.

| # | Task | Files |
|---|------|-------|
| 5.1 | Update `hourly.yml`: run v1 then v2 | `.github/workflows/hourly.yml` |
| 5.2 | `git add state/* state_v2/*` | workflow |
| 5.3 | Fail job if either worker exits non-zero | workflow |
| 5.4 | `workflow_dispatch` for manual test | workflow |

**Acceptance:**
- [ ] Manual dispatch on branch succeeds (verify after merge)
- [ ] Both `state/` and `state_v2/` committed after run
- [ ] V1 logs show no regression in format

---

## Phase 6: Weekly + conclusion email

**Goal:** Saturday summary; week 10 sends conclusion variant.

| # | Task | Files |
|---|------|-------|
| 6.1 | Create `app/weekly_report.py` — build report from both state dirs | new |
| 6.2 | Sections: period, portfolio, per-symbol, trades, re-opt, since-start | `weekly_report.py` |
| 6.3 | `build_conclusion_report()` for week 10 | `weekly_report.py` |
| 6.4 | Create `.github/workflows/weekly.yml` — cron Saturday AM (UTC tuned to your TZ) | workflow |
| 6.5 | Week detection: `weeks_since(experiment_start)` → conclusion if ≥ 10 | `weekly_report.py` |

**Tests:** `tests/test_weekly_report.py`

**Acceptance:**
- [x] Manual run: `python -m app.weekly_report --dry-run` prints report
- [ ] One test email received (optional manual check)

---

## Phase 7: Dashboard Compare tab

**Goal:** Toggle v1/v2; Compare tab with side-by-side returns.

| # | Task | Files |
|---|------|-------|
| 7.1 | Use `paths.get_state_dir(version)` in dashboard | `dashboard.py` |
| 7.2 | Sidebar version selectbox | `dashboard.py` |
| 7.3 | Compare tab: load both equity.csv, compute since-start returns | `dashboard.py` |
| 7.4 | Per-symbol comparison table | `dashboard.py` |

**Acceptance:**
- [x] Streamlit code updated for v1/v2 toggle + Compare tab
- [ ] Deployed Streamlit shows Compare tab (verify after deploy)
- [ ] Numbers match `weekly_report` for same data

---

## Phase 8: Deploy + 10-week monitoring

**Goal:** Flip V2 live on deploy day; monitor until conclusion email.

| # | Task | When |
|---|------|------|
| 8.1 | Set `experiment_start` in `state_v2/config.json` to deploy UTC timestamp | deploy |
| 8.2 | Merge to main; verify first dual-worker run | deploy |
| 8.3 | Check Saturday weekly email | week 1 |
| 8.4 | Midpoint review (week 5): spot-check AMD/NVDA re-opt rejections | week 5 |
| 8.5 | Conclusion email fires automatically | week 10 |
| 8.6 | Write `analysis/v2_newsletter.md` comparison report | week 10 |

**Acceptance:**
- [x] `experiment_start` set in `state_v2/config.json`
- [x] `analysis/v2_newsletter.md` draft template created
- [ ] 10 weekly emails received
- [ ] 1 conclusion email received
- [ ] `analysis/v2_newsletter.md` published

---

## Quick reference: commands

```bash
# Run all tests
python -m pytest tests/ -v

# Run workers locally
python -m app.worker --version v1
python -m app.worker --version v2

# Dry-run weekly report
python -m app.weekly_report --dry-run

# Regenerate comparison charts (later)
python analysis/compare_v1_v2.py
```

---

## Progress tracker

| Phase | Status | Completed |
|-------|--------|-----------|
| 0 Test infrastructure | ✅ | 2026-09-02 |
| 1 Paths + worker versioning | ✅ | 2026-09-02 |
| 2 V2 strategy core | ✅ | 2026-09-03 |
| 3 Wire V2 into worker | ✅ | 2026-09-03 |
| 4 Meta optimizer | ✅ | 2026-09-03 |
| 5 GitHub Actions | ✅ | 2026-09-03 |
| 6 Weekly email | ✅ | 2026-09-03 |
| 7 Dashboard | ✅ | 2026-09-03 |
| 8 Deploy + monitor | 🟡 | Code ready; monitoring starts on merge |
