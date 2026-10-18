# Live Trading + S&P Picker + Remote Viewer Checklist

**Blueprint:** `docs/live_trading_blueprint.md` (live 01–25 · picker **P01–P22** · remote **D01–D08**)  
**Spec:** `docs/live_trading_investigation.md` (§0–7 live · **§12 picker** · **§13 remote viewer**)  
**Host:** OVH `15.235.62.2` (not Oracle)

Mark `[x]` when done. Paste each blueprint ```text``` prompt standalone into the implementer LLM. Test-driven; keep V1/V2/live tests green.

---

## How to use

1. Open the matching prompt in the blueprint.  
2. Implement tests first → code → wire (no orphans).  
3. Check the box; commit when you choose.  
4. **Do not** fund real money (G4/G5) until G3 graduation is done.  
5. **Picker (Phase H)** software done; **Phase J** ops + **Phase K** remote viewer can proceed in parallel with finishing G3.

---

## Phase A–F — Live stack software (DONE)

Prompts **01–25** shipped. Do not re-litigate unless a regression appears.

| Area | Status |
|------|--------|
| Fees, RTH, sizing, never-borrow, audit, metrics, risk escalate | [x] |
| Broker port, reconcile, planner, executor, `live_worker`, modes | [x] |
| `IbkrBroker`, notifier, dashboard controls, daily report | [x] |
| Mode guards, seed `state_live`, deploy templates, memory E2E | [x] |

```bash
python -m pytest tests/ -v
python scripts/check_live_imports.py
```

---

## Phase G — Ops ladder (money / Gateway)

| Done | Step | Notes |
|------|------|--------|
| [x] | G0 | OVH VPS + Gateway 10.50 + IBC + app sync |
| [x] | G1 | Paper API **4002** (`DUR235447`); smoke OK |
| [x] | G1b | systemd xvfb/ibgateway; AutoRestart; 2FA relogin |
| [x] | G2 | Email alerts; CAD/BASE snapshot; health timers |
| [~] | G3 | `broker_paper` since **2026-10-05**; soak through **2026-10-19** RTH; checklist below |
| [ ] | G4 | Fund ~$1k USD taxable; `live_dry_run` several sessions |
| [ ] | G5 | Go-ahead; `LIVE_TRADING_CONFIRM=YES`; mode `live` |
| [ ] | G6 | Week-1 monitor; reconcile fees vs Flex |
| [ ] | G7 | R8 accountant note (only open research item) |

### G3 graduation (before G4)

Evidence from OVH review **2026-10-17** (paper `DUR235447`, mode `broker_paper`):

| Check | Status | Notes |
|-------|--------|--------|
| Services up | OK | xvfb / ibgateway / live-worker.timer / gateway-health / :4002 |
| Price path | OK | `price_source=ibkr_rth_hourly` |
| ≥2 weeks soak | [~] | Started **2026-10-05**; calendar gate **2026-10-19** (Mon) |
| No unexpected / duplicate orders | [~] | Audit empty until 2026-10-18; **no fills yet** (see blocker) |
| Fills match intent | [ ] | Needs ≥1 RTH fill |
| Never-borrow never violated | [~] | No borrow attempts observed; risk.json clean |
| Fees logged; after-fee vs B&H | [~] | Fee model + `live_daily_report` exist; need fill + report sample |
| Disconnect/reject handling | [~] | Zombie restarts work; 2026-10-17 FAIL+cooldown window then recovery |
| ≥1 BUY and ≥1 SELL | [ ] | **Blocked until Mon RTH** — see below |
| Gateway health / no alert spam | [~] | Health OK majority; FAIL count low vs OK |

**Blocker found + fixed (2026-10-17):** sleeve cash was **$333.33** (`total_cash` 1000 ÷ 3) while MSFT/AAPL/SMH are >$330, so whole-share qty was always **0** (`zero quantity`) for ~12 days — **zero fills, empty audit**. OVH patched: `total_cash=3000`, per-sleeve cash `$1000`, `allow_fractional_default=false`. Immediate cycle → **`AAPL:queued`** (outside RTH). Local planner also fixed so `buy_cash_cap` is not clamped by stale sleeve cash (deploy with next sync).

**Monday 2026-10-19 RTH plan:**

1. Confirm `AAPL` BUY submits/fills (or re-plans in RTH); audit `order_submitted`/`fill`.  
2. After fill, force or wait for a SELL (tighten `sell_drop_pct` temporarily if needed).  
3. Re-run checklist; only then mark G3 `[x]`. Do **not** start G4 early.

---

## Phase H — S&P 500 auto picker (EXPAND SCOPE)

Implement blueprint **Part II** prompts **P01–P22** in order. Spec: investigation §12.

### H1 — Pure domain (P01–P08)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | P01 | `state_picker` paths | `tests/test_picker_paths.py` |
| [x] | P02 | Ticker normalize (BRK.B etc.) | `tests/test_picker_tickers.py` |
| [x] | P03 | Wikipedia S&P parse + last-good cache | `tests/test_picker_sp500.py` |
| [x] | P04 | Opt 1w / score 1m windows | `tests/test_picker_windows.py` |
| [x] | P05 | After-fee strategy vs B&H scorer | `tests/test_picker_score.py` |
| [x] | P06 | Optimize week → score month (one symbol) | `tests/test_picker_rank_symbol.py` |
| [x] | P07 | Select top ≤5, edge ≥ 0 (0 = cash) | `tests/test_picker_select.py` |
| [x] | P08 | >30% fetch-fail abort policy | `tests/test_picker_failures.py` |

**H1 acceptance:** pure functions only; no IBKR calls; pytest green on tests above.

### H2 — Bars + fetch (P09–P10)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | P09 | `HourlyBarProvider` + fixture + retries | `tests/test_picker_bars_provider.py` |
| [x] | P10 | Batch fetch + abort if >30% fail | `tests/test_picker_fetch_universe.py` |

### H3 — Pending / soft-rotate / active (P11–P13)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | P11 | `pending_selection.json` store | `tests/test_picker_pending.py` |
| [x] | P12 | Soft-rotate plan (exit_only / awaiting_first_buy) | `tests/test_picker_soft_rotate.py` |
| [x] | P13 | `active_selection.json` store | `tests/test_picker_active.py` |

### H4 — Apply into live + V1 + V2 (P14–P16)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | P14 | Apply → `state_live` config | `tests/test_picker_apply_live.py` |
| [x] | P15 | Apply → `state/` + `state_v2/` | `tests/test_picker_apply_paper.py` |
| [x] | P16 | `apply_pending_selection` (atomic, idempotent) | `tests/test_picker_apply.py` |

**H4 acceptance:** temp dirs only in tests; first run (empty active) applies; empty selection → prior names `exit_only`.

### H5 — Worker gates (P17–P20)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | P17 | 20h SMA first-buy gate | `tests/test_picker_trend_gate.py` |
| [x] | P18 | Equal free-cash sleeve budget | `tests/test_picker_sizing.py` |
| [x] | P19 | Wire gates into `live_worker` | `tests/test_live_picker_gates.py` (or extend live worker tests) |
| [x] | P20 | Wire exit_only / list into paper `worker` | `tests/test_worker_picker_flags.py` |

**H5 acceptance:** exit_only blocks BUY; SMA gate fail-closed; mid-cycle re-opt still overwrites %; no forced Monday rebalance.

### H6 — Rank job, email, CLI, IBKR, ops, E2E (P21–P22)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | P21 | `run_ranking` + ranking/failure emails | `tests/test_picker_run.py`, `tests/test_picker_notify.py` |
| [x] | P22 | CLI `app.picker_rank`, IBKR provider, Monday apply hook, timer units, E2E, gitignore, README | `tests/test_picker_e2e.py` + provider unit tests |

**H6 acceptance:**

- [x] `python -m app.picker_rank --dry-run` writes report only  
- [x] Success path writes pending + email every run  
- [x] >30% IBKR fail → keep previous list + error email  
- [x] `live_worker` applies pending on first Monday RTH cycle  
- [x] `deploy/ibgateway/picker-rank.timer` documented  
- [x] `state_picker/` gitignored; E2E <5s green  
- [x] Full `pytest tests/ -v` green (164 passed, 2026-10-17)  

```bash
python -m pytest tests/test_picker_*.py tests/test_live_picker_gates.py tests/test_worker_picker_flags.py -v
python -m pytest tests/ -v
```

---

## Phase I — Cleanup (REMOVE UNNECESSARY)

Goal: one clean bot — **picker-driven universe**, **IBKR-first data**, **OVH-only ops**. Delete or retire dead weight; do not leave parallel “old universe” paths.

### I1 — Code & config

- [x] Stop treating **MSFT/AAPL/SMH** as the permanent live universe; defaults become “last applied picker list” (bootstrap empty / `active_selection` until first apply)  
- [x] Remove / stop maintaining **static full paper lists** as the long-term source of truth once picker apply owns V1/V2 symbols  
- [x] Live bars: **IBKR RTH hourly primary**; Yahoo only as explicit fallback (or remove if unused after soak)  
- [x] Delete or archive root one-offs that are not part of the app (e.g. `walkforward_optimize.py` → `archive/one_offs/`)  
- [x] Strip dashboard copy that still teaches **`ZSP.TO` / TSX** as current universe  
- [x] Remove **fractional-by-default** live assumptions; whole shares only on IBKR API (R3)  
- [x] Ensure no dual sizing paths that ignore `sleeve_buy_budget` / soft-rotate flags  
- [x] Drop unused imports, dead helpers, and commented-out Oracle/Always-Free deploy scraps in active scripts  

### I2 — Deploy / ops clutter

- [x] Keep: `gateway-health`, `status`/`check_bot`, login helpers, picker timer, live-worker timer  
- [x] Review one-off probes (`probe_*.py`, `diagnose_*`, `fix_health_*`): keep in `deploy/ibgateway/` only if still used; else move to `archive/` or delete  
- [x] README / deploy docs: **OVH only** — no “provision Oracle Always Free” as current path  
- [x] Confirm `.gitignore` covers `state_picker/`, audit logs, `.env`  

### I3 — Docs hygiene

- [x] Todo/blueprint “next action” points at picker + G3 — not Oracle MVP prose  
- [x] Investigation historical Q3.6 trio stays as history; active ops follow §12  
- [x] No duplicate conflicting universe instructions across README / todo / dashboard  

**I acceptance:** grep shows no active guidance to trade `ZSP.TO`; live defaults not hard-locked to the trio after first picker apply; pytest still green (**164 passed, 2026-10-17**).

---

## Phase J — Picker ops on OVH (after H6)

| Done | Step | Notes |
|------|------|--------|
| [x] | J1 | Timer installed; forced dry-run **ok** (`run_id=20261018_002339`, selected FICO/COHR/GEN/AKAM/MOS, `pending_written=False`) |
| [~] | J2 | Unit live (no `--dry-run` / no `--no-email`); force verify run in progress 2026-10-18 — mark `[x]` when pending + email confirmed |
| [ ] | J3 | Monday apply via `live_worker` (paper paths first if staging) |
| [ ] | J4 | Confirm soft-rotate + SMA gate in RTH; equal cash as frees |
| [ ] | J5 | Confirm mid-biweek V1/V2 re-opt still overwrites buy/sell % |
| [ ] | J6 | Only then rely on picker for live sleeves (still behind G4/G5 money ladder) |

---

## Phase K — Remote portfolio viewer (EXPAND SCOPE)

Implement blueprint **Part III** prompts **D01–D08**. Spec: investigation §13.  
**Access:** Tailscale → always-on Streamlit on OVH. **Do not** use IBKR Client Portal / second Gateway to check the book.

### K1 — Software (D01–D08)

| Done | Prompt | Deliverable | Primary tests |
|------|--------|-------------|----------------|
| [x] | D01 | Live/paper/picker status loaders | `tests/test_remote_status.py` |
| [x] | D02 | Health strip helpers | `tests/test_remote_health.py` |
| [x] | D03 | Live tab UI (health → positions) | `app/remote/ui.py` + dashboard tabs |
| [x] | D04 | Paper V1 / V2 tabs | dashboard + loaders |
| [x] | D05 | Picker tab | dashboard + ranking meta |
| [x] | D06 | Safe controls only (no mode change) | `tests/test_remote_controls_scope.py` |
| [x] | D07 | IBKR marks via client id **9** | `tests/test_remote_marks.py` |
| [x] | D08 | systemd unit + Tailscale deploy docs | `streamlit-dashboard.service` + README |

**K1 acceptance:** tabs Live | Paper V1 | Paper V2 | Picker; health first; manual refresh; safe controls only; pytest green.

### K2 — OVH ops

- [x] Install Tailscale on VPS + phone + laptop (free personal)
- [x] Enable `streamlit-dashboard.service` on OVH (`127.0.0.1:8501`, HTTP 200)
- [x] Open via Tailscale Serve: `https://vps-338e3236.tail03235c.ts.net/` (tailnet only)
- [x] Confirm marks path uses client id 9 (no clash with worker=1 / picker=7) — `DASHBOARD_IB_CLIENT_ID=9`; Refresh shows `marks=ibkr` + IBKR equity
- [x] Confirm enable/disable + ack work from phone without SSH — Disable→OFF, Enable→ON, Ack cleared seeded incident (2026-10-18)

**K acceptance:** can view live/paper/picker and use safe controls from phone over Tailscale without logging into IBKR. **DONE.**

---

## Research tracker

| ID | Status | One-line finding |
|----|--------|------------------|
| R1 | closed | Paper API 4002 on OVH |
| R2 | closed | IBKR Pro Tiered; model in `app/fees/model.py`; G6 reconciles Flex |
| R3 | closed | API fractionals fail (10243) → **whole shares only** |
| R4 | closed | Spendable = **AvailableFunds**; ignore BuyingPower |
| R5 | closed | Gateway+IBC unattended on OVH; weekly 2FA alert |
| R6 | closed | IBKR RTH hourly OK; prefer over Yahoo prepost |
| R8 | **open** | Accountant note on trade frequency (human) |
| R9 | closed | Complimentary historical hourly sufficient |
| R10 | closed | Portfolio view = Streamlit on OVH + Tailscale; never second IBKR login (§13) |

---

## Progress log

| Date | Notes |
|------|--------|
| 2026-10-05 | OVH + paper Gateway; G3 `broker_paper` timer started |
| 2026-10-06 | Autorestart hardened; health + email monitoring |
| 2026-10-07 | R2–R6/R9 closed; Tiered fees; whole shares; IB bars; AvailableFunds |
| 2026-10-12…13 | Gateway zombie / health CRLF / disconnect cooldown ops fixes |
| 2026-10-17 | Picker spec §12 + blueprint Part II locked; todo expanded (H/I/J); cleanup phase added |
| 2026-10-17 | Phase H P01–P22 + Phase I cleanup done (picker-driven defaults, archive probes/one-offs, OVH docs) |
| 2026-10-17 | G3 review: no fills (sleeve $333 &lt; share price); OVH sleeves → $1000; AAPL BUY queued for Mon RTH |
| 2026-10-17 | Deployed app+picker to OVH; wiki UA fix; picker-rank.timer on; full S&P dry-run in progress (client 7) |
| 2026-10-17 | Remote viewer §13 + blueprint Part III (D01–D08) + todo Phase K locked |
| 2026-10-17 | J1 dry-run ok (FICO/COHR/GEN/AKAM/MOS); Phase K software D01–D08 landed |
| 2026-10-18 | K2 done: marks client id 9 (`marks=ibkr`); Disable/Enable/Ack verified over Tailscale; trading left ON |

---

## Next action

1. **G3 Mon 2026-10-19 RTH** — confirm AAPL fill + one SELL; do **not** start G4/G5 early.
2. Finish **J2** verify (pending file + summary email from force run), then wait for **J3** Monday apply.
3. After J + G3: only then consider G4.
