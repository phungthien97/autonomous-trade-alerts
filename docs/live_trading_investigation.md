# Live Trading Investigation

Working document for deciding how (and whether) to turn the current alert/simulation bots into a **real auto-trading app**.

Use this with a walkthrough: pick **one question at a time**, discuss, then fill **Answer** + **Notes**. When enough answers are locked, draft the new app blueprint.

**Status:** Investigation complete (Q0–Q7); blueprint v2 (TDD prompts) + todo rewritten  
**Related:** `docs/v2_blueprint.md`, `docs/live_trading_blueprint.md`, `docs/live_trading_todo.md`, `README.md` (alerts only today)  
**Assumed starting point:** Toronto / Canada resident; V2-style peak/trough strategy; **USD-only** universe (US equities/ETFs including **VOO** in place of former `ZSP.TO`)

---

## How to use this doc

1. Work top-to-bottom or jump by priority (marked **P0** / **P1** / **P2**).
2. For each question: discuss → write a short **Answer** → capture **Notes** / open follow-ups.
3. Do not redesign the app until **Section 0–6** have answers (or explicit “defer”).
4. Locked decisions move into the table at the bottom.

**Answer legend**


| Field      | Meaning                                                |
| ---------- | ------------------------------------------------------ |
| Answer     | Final or provisional decision                          |
| Confidence | low / medium / high                                    |
| Notes      | Why, links, numbers, constraints                       |
| Defer?     | yes → revisit later; no → treat as input to app design |


---

## 0. Goals and non-goals (P0)

### Q0.1 — What does “success” mean for live trading?

- Beat V2 paper returns? Beat buy-and-hold? Learn execution reliably? Cap downside?
- Is this personal capital only, or a product others might use later?

**Answer:** Primary success metric is **beat buy-and-hold after all fees** (commissions, FX, slippage, data if any). Benchmark = **equal-weight hold of the live symbol universe from the same start date/cash**. V1 historically looked good vs that bar; V2 exists to improve on V1 toward the same goal. Capital is **personal**, and may later include **close friends/family** (not a public product).  
**Confidence:** high  
**Notes:**

- North star: **outperform equal-weight B&H of the live universe**, after real costs — not “maximize trade count” or “learn brokerage APIs” (those are means).
- Historical narrative: V1 did well → V2 should be better at the same objective (optimizer / trade discipline).
- **B&H definition (locked):** equal-weight hold of whatever symbols are in the live universe; same start timestamp and starting cash allocation convention as the live sleeves.
- **Cost bar (locked):** live must beat that B&H **after all fees**; paper-only outperformance is not enough to justify going live.
- **Users (locked for now):** self + possible close friends/family later. Not a general commercial product yet.
- **Follow-up (do not block Q0.2):** friends/family implies multi-account or shared-signal design and touches **Q6.1** (personal use vs managing others’ money / advice rules). Revisit before any non-self funding.
- Implication for later sections: cost model (Q2), sizing (Q3), and kill-switches (Q4) judged by **B&H-relative, after-fee** performance.
**Defer?** no

### Q0.2 — Capital and time horizon

- Starting capital (total and per symbol)?
- Max drawdown you can tolerate before kill-switch?
- Run for N weeks as an experiment, or indefinite?

**Answer:** Start with about **$1,000 total** across the whole live portfolio (per-symbol **ratio still undecided**). Scale up over time as confidence grows — eventually possibly **low–mid six figures** (a couple hundred thousand). Horizon is **indefinite** (ongoing improvement, not a fixed 10-week live experiment). **No drawdown-based stop**: do not auto-halt the strategy on max DD; capital leaves only when **you need the cash** and withdraw.  
**Confidence:** high (start size, indefinite horizon, no DD kill); low–medium (allocation ratios; scale-up pace)  
**Notes:**

- **Day-1 capital:** ~$1,000 **total** (not per symbol) — **USD** book (Q1.3); decide sleeve weights later (equal-weight vs conviction).
- **Small-account implication:** at ~$1k total, IBKR **minimum commissions / FX mins** are a large % of notional (see Q2.3). Early live is as much a **pipeline/fee reality check** as an alpha test; scaling is how B&H-beating becomes economically meaningful.
- **Scale path:** confidence-gated increases toward ~$100k–$300k class size; architecture should not assume “toy account forever” (fees, ops, multi-user later).
- **No max-DD kill-switch** as a *goal preference*. Q4 can still offer **optional soft alerts** (e.g. email at −X% from peak) without auto-flatten — confirm in Q4.1 / ties to Q0.3 alert prefs.
- Contrast with paper V2’s fixed `experiment_weeks: 10`: live is **open-ended**; paper experiment can still finish on its own schedule (Q0.4).
- Implication: success tracking vs equal-weight B&H should be continuous (rolling windows + since-inception), not only a single end date.
**Defer?** ratio / scale schedule deferred; core answer locked

### Q0.3 — Human involvement

- Fully unattended, or confirm-every-trade / confirm-above-threshold?
- Who gets alerts (email/SMS) on fills, errors, kill-switch?

**Answer:** **Fully automatic** order placement (no per-trade human approval). **Alerts are configurable**: choose **channel** (email and/or SMS), **what** events notify, and **when** (immediate vs batched). Plus **summary reports** on an agreed interval (daily / weekly / custom — exact cadence TBD in config later).  
**Confidence:** high  
**Notes:**

- Execution path: unattended `live` mode once enabled; remote **disable / withdraw** remains a manual capital action (Q0.2), not trade-by-trade confirm.
- Notification product requirement: user-selectable matrix of {event × channel × timing}, plus interval summaries (PnL vs equal-weight B&H after fees is a natural summary contents candidate from Q0.1).
- Candidate event types (finalize in Q4.3): fills, rejects/errors, disconnects, optional soft DD alerts, mode changes — each optionally on/off.
- SMS implies a provider later (Twilio etc.); email can reuse existing Gmail path. Don’t block architecture on provider choice now.
**Defer?** exact event list + default summary interval deferred to Q4.3 / config; principle locked

### Q0.4 — Relationship to V1 / V2 paper bots

- Keep paper V1/V2 running in parallel as control?
- Live = V2 logic only, or a new “V3 live” with different sizing/fees?

**Answer:** Keep **historical paper versions running in parallel** (V1 and V2 as they are) for lesson-learning and to inform better future versions. **Live is a new variant** (working name: **live / V3-live**) designed to accommodate **real fees and platform limitations** (FX, mins, whole shares, sessions, buying power, etc.) — not a verbatim deploy of paper V2.  
**Confidence:** high  
**Notes:**

- Paper V1/V2 remain the scientific controls / regression baseline; do not break their behavior to “help” live.
- Live variant may share signal ideas with V2 but must differ where reality demands (cost model, sizing, order rules). Compare all three (and equal-weight B&H) in reporting when possible.
- Naming: prefer explicit `paper_v1` / `paper_v2` / `live` (or `v3_live`) in config and dashboard to avoid confusion with the 10-week V2 experiment.
- Implication for Q5.5: likely one monorepo with clear mode separation, or shared strategy lib + live executor — decide later; principle is **parallel paper + distinct live**.
**Defer?** no

---

## 1. Broker and account (P0)

### Q1.1 — Primary broker for order placement

Candidates discussed so far:


| Broker       | Unattended API orders                                         | US + TSX | Notes                 |
| ------------ | ------------------------------------------------------------- | -------- | --------------------- |
| IBKR Canada  | Yes (official)                                                | Yes      | Leading candidate     |
| Questrade    | Retail: no live trade API (partner-only); MCP = human approve | Data yes | Not true auto-trade   |
| Wealthsimple | No official API                                               | —        | Unofficial = ToS risk |
| Other        | ?                                                             | ?        |                       |


**Answer:** **Interactive Brokers Canada (IBKR)** as primary broker — required for **fully automatic** order placement with official API support for the **USD-only US equities/ETFs** universe.  
**Confidence:** high  
**Notes:**

- Matches Q0.3 (fully auto) and Q0.4 (live variant must handle real platform limits of *this* broker).
- Questrade / Wealthsimple ruled out for unattended live orders (partner-only trade API / no official API).
- Universe amended to US-only (VOO, not TSX); IBKR still correct broker.
- Revisit only if IBKR account/API onboarding fails or product constraints block the live variant (R1).
**Defer?** no

### Q1.2 — Account type

- Cash vs margin?
- Individual vs joint?
- Taxable vs TFSA / RRSP / FHSA (and comfort with CRA “business trading” risk if very active in registered)?

**Answer:** **Individual**, **taxable** (non-registered). **Margin account open, but live bot must never borrow** — deploy only within equity / non-debit cash; no intentional leverage; avoid overnight negative cash so margin interest should not apply.  
**Confidence:** high  
**Notes:**

- Margin is for **smoother same-day reuse of proceeds / buying power**, not for gearing the $1k book.
- Live variant requirement (Q0.4 / Q3 / Q4): pre-trade check — reject or resize order if it would create a debit balance or exceed “no-borrow” cap.
- Interest reminder: charged on actual borrowed (negative cash) balances, typically overnight — policy is to never get there.
- Registered accounts deferred for this live book.
**Defer?** no

### Q1.3 — Base currency and FX policy

- Fund and hold **USD** for US names, **CAD** for TSX?
- Manual FX in chunks vs auto-convert every trade?
- Accept FX min (~USD 2) and/or ~0.03% auto-convert drag?

**Answer:** **USD-only book.** Hold **USD** cash to match all live/paper symbols (all US-listed after replacing `ZSP.TO` with **VOO**). Fund by converting CAD→USD in **chunks** when depositing; **do not** auto-convert on every stock order. No CAD trading sleeve required.  
**Confidence:** high  
**Notes:**

- Amended 2026-09-21: dropped dual-currency / TSX path in favor of VOO + USD-only (see Q1.4 / Q3.6).
- One-time (or occasional) CAD→USD conversion when funding still counts toward after-fee B&H (Q0.1) — log it; avoid per-trade FX.
- Disable IBKR auto-convert on the trading flow so the bot never silently FX-converts.
- Live variant tracks **USD cash only** (simpler than multi-currency).
**Defer?** no

### Q1.4 — Market data source for signals vs execution

- Keep **yfinance** (or other free) for strategy bars?
- Use broker quotes only for order placement / last price checks?
- Pay for IB real-time US and/or TSX data?

**Answer:** **IBKR free US market data** as the primary live signal + execution quote source: complimentary **Cboe One / IEX** real-time streaming for US stocks/ETFs (no paid subscription). **$0 paid data budget.** Paper V1/V2 may keep using yfinance until the IBKR data path is wired; target is the same US-only universe (**VOO** not `ZSP.TO`). No TSX data subscription needed.  
**Confidence:** high  
**Notes:**

- Finalized via Option **D / B+D**: USD-only universe unlocks free IBKR US real-time; replaces need for paid TSX Level I (~CAD $6/mo).
- Cboe One/IEX is **non-consolidated** (not full NBBO) but real-time and included with the account — acceptable upgrade vs yfinance for live.
- Free delayed / snapshot entitlements remain available as fallbacks.
- **R6/R9 closed 2026-10-07:** IBKR paper historical hourly TRADES bars match Yahoo (≤0.002% last close); use **RTH** bars for live signals. Live worker: IB-first, Yahoo fallback.
- Paid consolidated US tape / TSX packs deferred until scale justifies cost vs B&H.
**Defer?** no

### Q1.5 — Paper trading path at the broker

- How long on IB paper / simulated account before real money?
- What “graduation criteria” (fill quality, zero unexpected orders, fee model validated)?

**Answer:** Run the **live variant** on **IBKR paper for 2 weeks** (and until graduation criteria pass). Then run `**live_dry_run` against the real account** (compute orders, do not send) for a short confirmation window before enabling true `live` with ~$1k.  
**Confidence:** high  
**Notes:**

- **Duration:** 2 weeks on IBKR paper minimum; do not graduate early even if criteria look green on day 3.
- **Graduation criteria (all required):**
  1. No unexpected or duplicate orders
  2. Fills match intent (symbol, side, size within whole-share / sizing rules)
  3. **Never-borrow** check never violated
  4. Fees + funding FX logged; after-fee PnL vs equal-weight B&H computable
  5. Disconnect / reject handling is safe (no silent retry storms)
  6. At least one full **BUY and SELL** cycle observed on paper (or equivalent forced path test)
- **Post-paper gate:** `live_dry_run` on the **real** funded account before first live order (Q5.6 modes).
- Paper V1/V2 keep running in parallel for lessons (Q0.4); graduation applies to the **live variant**, not to replacing paper bots.
**Defer?** no

---

## 2. Fees, frictions, and performance realism (P0)

### Q2.1 — Cost model to bake into live (and maybe paper)

Include or ignore each:

- US commission (tiered min ~USD 0.35)
- CAD commission (min ~CAD 1 for TSX) — **N/A for live** after USD-only / VOO decision
- FX commission / auto-convert markup — **funding conversions only** (CAD→USD chunks), not per trade
- SEC / regulatory fees on sells
- Spread + slippage assumption
- Market data subscription monthly cost — **$0** (IBKR free US Cboe One/IEX)

**Answer:** **Include every applicable cost** — do not omit line items for simplicity. Live (and paper live-variant sims) must subtract the full stack below when comparing to equal-weight B&H **after all fees** (Q0.1). Prefer reading actual amounts from IBKR activity/Flex when live; use published schedules as model defaults.  
**Confidence:** high (principle); medium (exact schedule numbers change — refresh from IBKR pages / statements)  
**Notes:**

#### A. Per US stock/ETF order (always model)

| Cost | When | Notes (verify on IBKR site / statement) |
|------|------|----------------------------------------|
| IBKR commission | Every fill | Tiered (~USD 0.0035/sh, min ~USD 0.35) **or** Fixed (~USD 0.005/sh, min ~USD 1); pick account plan in R2 |
| Exchange fees | Usually tiered plan | Venue-dependent; pass-through / rebate |
| Clearing (NSCC/DTC) | Typically tiered | ~USD 0.00020/share class fees |
| SEC fee | **Sells** | ~USD rate × aggregate sale value (rate changes) |
| FINRA TAF | **Sells** | Per share sold (capped schedules exist) |
| FINRA CAT | Trades | Tiny per-share audit-trail fee |
| NYSE / FINRA pass-through | Often tiered | % of commissions |
| Regulatory fees under Fixed | Fixed plan | Fixed still passes some regulatory fees |

#### B. Cash / FX / account movement (model when they occur)

| Cost | When | Notes |
|------|------|--------|
| FX commission | CAD↔USD conversion | ~0.20 bp, min ~USD 2 (chunk funding); **no** per-equity auto-convert by policy |
| Auto-convert markup | If ever used | ~0.03% — treat as fee if policy violated / IB forces it |
| Withdrawal fees | After IBKR’s free withdrawals/month | Wire/EFT schedule (USD/CAD) |
| Deposit / bank-side fees | Funding | IBKR deposit often free; **your bank** wire fees still count if paid |
| GST/HST | On eligible IBKR charges | Canada may tax some fees — include if appears on statement |

#### C. Economic frictions (not always an IBKR invoice line — still include)

| Cost | Policy |
|------|--------|
| Bid–ask / slippage | **Include** — assume explicit bps or ¢/share until calibrated from paper fills (R2/R6) |
| Partial-fill adverse selection | **Include** when measuring live vs signal mid |

#### D. Must stay $0 under current policy (still detect / alert if non-zero)

| Cost | Why tracked |
|------|-------------|
| Margin / borrow interest | Never-borrow (Q1.2) — any debit interest = policy failure |
| Paid market data | Q1.4 $0 |
| Inactivity / platform / account minimum | IBKR Canada retail typically $0 — confirm |
| Options/futures/IPO/etc. fees | Out of product scope |
| CAD/TSX stock commissions | USD-only universe |

#### E. Related but not “broker fee” (track separately; don’t pretend they’re zero)

| Item | Treatment |
|------|-----------|
| US dividend withholding (taxable CDN account) | Tax, not commission — log for after-tax view; B&H of same names often similar |
| ETF MER (e.g. VOO) | Embedded in NAV — same for B&H of VOO; no extra subtract beyond NAV |
| Credit interest on cash | Optional **credit** in model if material; at $1k usually ~$0 above IBKR thresholds |

#### F. Implementation rules for the live variant

1. **Master fee checklist** in config/code mirrors tables A–D; tests fail if a known IBKR US-equity fee category is missing.
2. **Source of truth when live:** IBKR Activity / Flex — reconcile modeled vs billed monthly (R2).
3. Paper V1/V2 can stay fee-free for historical continuity; **live variant + B&H comparison** use full after-fee stack.
4. Prefer **Tiered + all pass-throughs** (or Fixed + every regulatory line that still appears) for “miss nothing” — **R2 chose Tiered** for small-account mins; Flex reconcile remains G6.

**Defer?** no for plan choice / published rates; statement reconcile → G6. Principle locked: **all applicable fees in**

### Q2.2 — Does V2’s λ (trade penalty) need retuning for live costs?

- Current meta uses `lambda_per_trip` (e.g. ~20 in config). Is that in the right units/currency vs real round-trip cost at your size?

**Answer:** **Yes** — retune λ (and any live-variant trade penalty) from the **full fee model** (Q2.1), not keep the paper ~$20 guess blindly.  
**Confidence:** high  
**Notes:**
- Paper V1/V2 may keep their existing λ for historical continuity of the experiment; the **live variant** must use a penalty grounded in estimated **round-trip all-in cost** at the intended sleeve size (commission + reg + slippage ± allocated funding FX).
- **R2 numeric (2026-10-07):** under Tiered + 5 bps slip, 1-share RT ≈ **~$0.9–$1.1** at $100–$335; use `estimate_lambda_per_trip(qty, price)` (typically **~$1–2.5** for early live whole-share sleeves). Paper V2 `lambda_per_trip=20` stays until a deliberate meta re-opt.
- Revisit when capital scales (mins matter less at larger size); reconcile modeled λ vs Flex after fills (G6).
- Units: λ should be in the **same currency/units as the optimizer’s P/L score** (USD for USD-only book).
**Defer?** no — numeric guidance set; Flex calibration remains G6

### Q2.3 — Small-account effects

- Per-symbol ~$1,000 (current sim): are minimum fees acceptable, or raise size / cut symbols?
- Prefer fewer symbols with larger notional?

**Answer:** At ~$1k total, use **fewer symbols (about 2–3)** so each sleeve is larger and IBKR minimum fees are a smaller % of notional. Expand the universe as capital/confidence grows.  
**Confidence:** high (fewer symbols); medium (exact count/list)  
**Notes:**
- Paper V1/V2 can keep the full 7-name list for learning (Q0.4); **live** (and fee-aware live sims) start concentrated.
- Equal-weight B&H (Q0.1) for live comparisons uses the **live** symbol set only (2–3 names), not the full paper universe.
- Exact tickers TBD — candidates from current list: AAPL, AMD, GOOG, MSFT, NVDA, SMH, VOO.
- Revisit when scaling toward larger capital (Q0.2).
**Defer?** exact 2–3 ticker list (pick next or with Q3.6 refinement)

### Q2.4 — Whole shares vs fractional

- Sim uses fractional `cash / price`. Live: whole shares only, IB fractionals where available, or cash buffer policy?

**Answer:** Use **IBKR fractional shares where available**; fall back to **whole shares** (leftover cash stays cash) when fractionals are not offered for that symbol.  
**Confidence:** high  
**Notes:**
- Live variant must query/know fractional eligibility per symbol (R3); never assume paper-style perfect fractionals.
- On non-fractional names: `floor(cash / price)` shares; residual cash idle until next opportunity or rebalance.
- Fee model (Q2.1): IBKR typically commissions fractionals like whole shares — still apply full fee stack.
- Paper V1/V2 may keep fractional sim math for continuity; live variant + fee-aware sims should match this policy.
**Defer?** no

### Q2.5 — Settlement and buying power

- Cash account T+1 reuse limits vs margin?
- How to handle same-day sell then buy (another symbol or same)?

**Answer:** Use **margin buying power for same-day turnover** (sell → buy without waiting for T+1 settlement). Hard cap remains **never borrow / no overnight debit** (Q1.2) — resize or reject any order that would create a debit balance.  
**Confidence:** high  
**Notes:**
- Enables fully auto sleeve rotation across 2–3 symbols without cash-account freeriding friction.
- Pre-trade check: projected cash ≥ 0 after fill (and any fees); else skip/resize.
- **R4 closed 2026-10-07:** use **AvailableFunds** as spendable; **ignore BuyingPower** (leverage). TotalCashValue kept for logging/reconcile.
**Defer?** no

---

## 3. Strategy → live execution gaps (P0)

### Q3.1 — Position sizing rule live

Today’s paper model: per symbol, all cash ↔ all shares.

Live options:

- Same all-in / all-out per sleeve
- Fixed notional per symbol
- % of total equity
- Risk-based (vol / stop)
- Max % deployed at once across portfolio

**Answer:** **Same as paper — all-in / all-out per sleeve**: when BUY fires, deploy that sleeve’s available cash into the symbol (fractionals/whole-share rules apply); when SELL fires, liquidate the sleeve’s entire position to cash.  
**Confidence:** high  
**Notes:**
- Sleeves are the ~2–3 live symbols (Q2.3); each has its own cash/shares; no cross-sleeve “% of total equity” sizing for v1 live.
- Still subject to never-borrow (Q1.2/Q2.5) and fee-aware sizing (can’t buy more than affordable after estimated fees).
- Aggressive turnover → λ retune (Q2.2) and full fee stack (Q2.1) matter more.
**Defer?** no

### Q3.2 — Order type

- Market, limit (mid / last ± X bps), marketable limit, VWAP/adaptive (IB algos)?
- Timeout / cancel-replace policy if unfilled?

**Answer:** Use **market orders** during allowed sessions for live BUY/SELL. Prefer fill certainty over minimizing slippage on this liquid US universe.  
**Confidence:** high  
**Notes:**
- Chose simplicity / full-fill priority over marketable limit (discussed 2026-09-23).
- Slippage still counted in the full fee/friction model (Q2.1); calibrate from paper fills (R2/R6).
- Unfilled edge cases (halt, closed market, reject): **do not leave working orders** — cancel if anything remains open; alert; wait for next valid signal/bar. Market orders that reject are logged and skipped (no silent retry storm).
- Extended-hours market orders: defer to Q3.3 (likely RTH-only).
**Defer?** no

### Q3.3 — Trading session

- Regular US hours only? Extended?
- TSX hours for `ZSP.TO` separately? — **N/A** (VOO / USD-only)
- What if signal fires when market closed (queue for open, skip, or GTC)?

**Answer:** Trade in **US regular hours (RTH) only**. No extended-hours orders. If a signal is ready while the market is closed, **queue it for the next RTH open** (do not use GTC overnight market orders).  
**Confidence:** high  
**Notes:**
- Matches market-order choice (Q3.2): avoid thin extended-hours liquidity.
- Queued intent should be idempotent (one pending BUY/SELL per symbol) and re-validated at open (price/halt/buying power) before sending.
- Holidays / early closes: treat as non-RTH; keep queued until next valid session.
**Defer?** no

### Q3.4 — Bar / clock alignment

- Worker cadence today ~10m on hourly bars — keep that for live?
- Use broker clock vs UTC file state?
- Avoid double-firing the same signal (idempotency key per symbol+bar)?

**Answer:** Keep **hourly bars** with a **frequent poll** (about every 10 minutes). Store timestamps in **UTC**. Allow order submission only when **US RTH** is open (Q3.3). Enforce **idempotency**: at most one live order intent per `(symbol, bar_timestamp)` so retries/overlaps cannot double-fire.  
**Confidence:** high  
**Notes:**
- Poll ≠ new signal frequency; signals still come from completed hourly bars (plus queued open actions).
- At RTH open, process queued intents first, then any new bar logic — still idempotent.
- Align data bars with RTH where possible (R6) so extended-hours prints don’t create false hourly extremes.
**Defer?** no

### Q3.5 — Source of truth for positions

- Broker positions always win?
- Local `state_*` is advisory only?
- Reconcile every run; what if drift (partial fill, manual trade, corporate action)?

**Answer:** **Broker is source of truth.** Local live state is a cache/journal only. **Reconcile every run** against IBKR positions and cash; on conflict, **broker wins** and the bot realigns. **Alert on unexpected drift** (manual trade, partial fill residue, corporate action, failed cancel).  
**Confidence:** high  
**Notes:**
- Strategy peak/trough fields remain local, but **shares/cash** used for sizing must match broker after reconcile.
- Drift playbook: alert → adopt broker quantities → do not “fix” local shares with a market order unless a kill/flatten policy says so (Q4).
- Paper V1/V2 stay file-based truth (unchanged).
**Defer?** no

### Q3.6 — Universe and product constraints

- Keep current V2 assets list?
- Drop TSX, drop thin names, US-only for FX simplicity?
- ETFs vs single names; options later? (default: stocks/ETFs only)

**Answer:** **USD-only** stocks/ETFs. Paper V1/V2 keep full list with **VOO** (not `ZSP.TO`). **Live starter trio (profit / edge-focused):** **MSFT, AAPL, SMH**. Options out of scope. Expand toward the full paper list as capital grows (Q2.3).  
**Confidence:** high (USD-only / VOO); high (live trio based on multi-window analysis 2026-09-23)  
**Notes:**

#### Why these three (analysis summary)

Goal is **beat equal-weight B&H after fees** (Q0.1), not max absolute return. Ranked by **bot − B&H edge**, trade burden, and fit to peak/trough characteristics.

| Evidence | Finding |
|----------|---------|
| Longer V1 newsletter window (May–Jul style results in `analysis/newsletter.md`) | Strongest edges: **MSFT (+13.5%)**, **SMH (+11.5%)**, **AAPL (+7.1%)**. Bot won by sitting in cash on declines/chop. |
| Same write-up — what fails | **AMD** / calm index (**ZSP→VOO**) lose to B&H via whipsaw; **NVDA** hurt by bad threshold/chop mixes. |
| Current ~3-week V1/V2 experiment (`state` / `state_v2`) | Short sample; **MSFT** still among best edges on V2; don’t overweight NVDA’s brief V1 win. |
| ~120 trading days hourly backtest + rough fees (min commission + slippage) | Edge leaders: **MSFT, AAPL, SMH**. **AMD** high absolute return but **large negative edge**. **NVDA/GOOG/VOO** weak edge on that window. |
| Model fit | Peak/trough shines when price **chops or draws down** and cash periods help (MSFT/SMH story). Liquid names suit **market orders** (Q3.2). |
| Fee fit at ~$1k / 3 sleeves | Prefer names with **edge after costs**. SMH trades more than MSFT/AAPL (higher fee drag) but historically still earned edge — keep as third; revisit if live fees dominate. |

**Rejected for live v1:** AMD (absolute ≠ edge), NVDA (unstable edge), GOOG (mixed), VOO (calm ETF tends to lose to B&H under this strategy).

- Equal-weight B&H for live = equal weight of **MSFT + AAPL + SMH** only.
- Paper historical CSV may still show `ZSP.TO` pre-cutover; VOO sleeve was reset fresh.
**Defer?** no

---

## 4. Risk controls and operations (P0)

### Q4.1 — Hard kill-switches

Candidates:

- Max orders / day / week
- Max notional / order and / day
- Max portfolio drawdown from peak
- Max loss per symbol
- Disable trading flag (config + remote)
- Panic flatten all

**Answer:** Prefer **alerts first, not immediate hard kills**. On a risk-threshold breach, notify the user (email/SMS per Q0.3). If the user does **not acknowledge / respond within 2 hours**, then **auto-stop trading** (disable new orders). No drawdown-based strategy kill as a goal (Q0.2); DD can still trigger an **alert** on the same 2-hour escalate path. Panic flatten remains **manual/remote** unless separately armed.  
**Confidence:** high  
**Notes:**

#### Immediate hard blocks (not “kill-switches” — per-order policy; stay instant)

- Never-borrow / no overnight debit (Q1.2 / Q2.5)
- Outside US RTH (Q3.3) — queue instead of send
- Idempotency already-fired bar (Q3.4)

#### Alert → 2h → stop (configurable thresholds)

| Trigger | Default idea | On breach |
|---------|--------------|-----------|
| Max orders / day | ~6 | Alert → if no ack in **2 hours** → disable trading |
| Max notional / order | > sleeve equity or would borrow | Alert + block that order; escalate if repeated |
| Max notional / day | ~2× portfolio | Alert → 2h → stop |
| Portfolio DD from peak | optional soft threshold (e.g. −15%) | Alert only path → 2h → stop (not instant kill) |
| Max loss / symbol | optional | Same alert → 2h → stop |
| Broker disconnect / reject storm | ops | Alert → 2h → stop (or sooner if unrecoverable) |
| Remote disable flag | always available | Immediate stop when user sets it |
| Panic flatten | manual | User-initiated only for v1 |

#### Ack / response definition (implement later)

- User “response” = acknowledge via agreed channel (e.g. dashboard button, reply keyword, or flip `trading_enabled`).
- Timer starts at first alert for that incident; repeat alerts don’t reset unless configured.
- After auto-stop: require explicit user re-enable (no auto-resume).

**Defer?** exact numeric thresholds can be tuned in config; **alert-then-2h-stop** pattern locked

### Q4.2 — Failure modes

What should happen on:

- Broker API down / Gateway disconnected
- Partial fill
- Rejected order
- Stale price / missing bar
- Duplicate worker run
- Secrets leaked / credentials rotated

**Answer:** **Fail safe.** On unknown or unhealthy state, place **no new orders**; **alert**; **reconcile to broker** (Q3.5). Partial fills: **adopt broker quantities**. Rejects: log + alert, no silent retry storm. Stale/missing data: skip symbol this cycle. Duplicate runs: blocked by idempotency (Q3.4). Credential/API failures: alert and use **alert → 2h → auto-stop** (Q4.1) if not recovered / acknowledged.  
**Confidence:** high  
**Notes:**

| Failure | Behavior |
|---------|----------|
| API / Gateway down | No new orders; alert; retry connection with backoff; escalate to 2h stop if still down / unacked |
| Partial fill | Cancel residual if any; adopt broker position; alert if material drift |
| Order reject | Log reason; alert; do not hammer resubmit; next bar may rethink |
| Stale / missing bar | Skip that symbol; no invent-price trading |
| Duplicate worker | Idempotent `(symbol, bar)` — second run no-ops |
| Secrets leaked / rotate | Immediate disable trading + alert; require manual re-enable after rotation |
| Queued open + halt at open | Re-validate; if unsafe, cancel queue + alert |

**Defer?** no

### Q4.3 — Monitoring and alerting

- Email / Telegram / SMS on: signal, fill, reject, daily PnL, weekly summary?
- Dashboard: paper only vs live positions/fills?

**Answer:** Alerts remain **user-configurable** (Q0.3). **Defaults:** immediate alerts on fills, rejects/errors, disconnects, risk-threshold events, and trading stop/disable; **daily summary after RTH close** with live PnL vs equal-weight B&H **after fees** and open positions; **email on**, SMS optional until configured; dashboard shows **live positions/fills plus paper V1/V2**.  
**Confidence:** high  
**Notes:**
- Immediate set ties to Q4.1 ack workflow (risk alerts start the 2h timer).
- Summary cadence default = daily; user may switch to weekly/custom later.
- No Telegram required for v1 unless added later as another channel.
**Defer?** no

### Q4.4 — Audit trail

- Log every intent, order id, fill, fee, FX conversion?
- Retention / where stored (git? local DB? broker export)?

**Answer:** Log **every** trading intent, broker order id, fill, fee line item, FX conversion, alert, user ack, and stop/re-enable event. Store on the **live host** in append-only files and/or a local DB — **not in git**. Keep **IBKR Flex / Activity** exports as independent backup. Retain at least **~2 years** (adjust for tax needs).  
**Confidence:** high  
**Notes:**
- Supports Q2.1 fee reconciliation and Q0.1 after-fee vs B&H reporting.
- Paper V1/V2 may keep CSV-in-repo pattern; live audit stays off-git for volume and sensitivity.
**Defer?** no

---

## 5. Architecture and hosting (P1)

### Q5.1 — Process split

Options:


| Option | Description                                                      |
| ------ | ---------------------------------------------------------------- |
| A      | Single always-on worker: signal + execute                        |
| B      | Keep GitHub Actions for signals; separate executor places orders |
| C      | New dedicated live app; paper bots stay as today                 |
| D      | Other                                                            |


**Answer:** **One place for everything.** Run paper V1, paper V2, and the live variant together on a **single always-on deployment** (unified app/host): signals, execution, alerts, ack timer, audit, dashboard data. Do **not** keep live orders on GitHub Actions or split “paper elsewhere / live elsewhere.”  
**Confidence:** high  
**Notes:**
- User preference (2026-09-23): pull paper + live into **one** operational home.
- Still separate *modes/processes* inside that home (e.g. `paper_v1`, `paper_v2`, `live`) so Q0.4 isolation holds — but same machine/repo/ops surface.
- Migrate off GitHub Actions as the primary scheduler once the always-on host is reliable (Actions may remain backup/CI only).
- Closest classic option: **A**, extended to include paper bots—not only live execute.
**Defer?** no

### Q5.2 — Where it runs

- Home PC / mini PC (Toronto)
- Cloud VM (Azure Canada Central / AWS Canada)
- Hybrid

Uptime, power, IP stability, IB Gateway/Client Portal Gateway constraints?

**Answer:** **Single cloud host** for the unified app (Q5.1). **Start with Oracle Cloud Always Free** (home region at signup; prefer a Canada region if offered). One VM only — no multi-cloud sync/failover. If Oracle capacity/setup fails later, **migrate** to a paid Canada VPS (e.g. OVH Montreal) as a cutover, not a hot standby.  
**Confidence:** high  
**Notes:**
- Locked 2026-09-23: try Always Free first for cost; accept rare single-host downtime; alert on host/API down (Q4).
- Target ≥ enough RAM for IB Gateway + Python (Ampere free tier is usually fine if obtained).
- Disk: default boot (~50 GB) + logrotate + download logs locally when needed; total free block cap 200 GB.
- Fallback provider (OVH/DO) is a **future migration option**, not dual-running.
**Defer?** no

### Q5.3 — Broker connectivity stack

- TWS API + IB Gateway + Python (`ib_insync` or raw)
- Client Portal Web API (REST/WS)
- Who handles 2FA / daily re-login / SSO?

**Answer:** **IB Gateway (headless) + IBC or IBeam + Python `ib_insync`**. Enable IB **Auto restart** / never-lock settings for API stability. Expect brief nightly reconnect blips (bot backoff/reconnect). **Weekly re-auth / 2FA:** alert the user to complete IB Key (or equivalent); bot resumes after session is back. Prefer this over Client Portal Web API for lower unattended downtime on the Oracle host.  
**Confidence:** high  
**Notes:**
- Supervisor (systemd/Docker) restarts Gateway if it dies.
- Avoid concurrent logins on the same account (phone/TWS) that kick Gateway.
- Paper then live ports; R5 validates exact IBeam/IBC + Oracle Linux setup.
- Client Portal path deferred unless Gateway proves unusable.
**Defer?** no

### Q5.4 — Secrets and security

- Where live: env files, OS keychain, cloud secrets?
- Never commit tokens; rotate policy
- Network: VPN? IP allowlist?

**Answer:** Store IB and app secrets in **environment files and/or Docker secrets on the Oracle VM** — never in git or public dashboard config. **SSH key-only** access; optional **IP allowlist**. Firewall: expose SSH; keep Gateway API ports **localhost-only** to the bot. On suspected leak: **rotate credentials** and **immediate trading disable** (Q4.2). VPN optional, not required for v1.  
**Confidence:** high  
**Notes:**
- No secrets in Streamlit Community Cloud / GitHub Actions for live trading.
- Separate paper vs live credentials/ports where IB allows.
**Defer?** no

### Q5.5 — Codebase shape

- Extend this repo (`app/broker/`, `--mode live`)?
- New repo for live executor only?
- Shared strategy library vs copy-paste freeze?

**Answer:** **Extend this repo** into one unified codebase on the Oracle host: e.g. `app/broker/`, explicit modes (`paper_v1` / `paper_v2` / live variants), **shared strategy** with a distinct **fee/platform-aware live path** (Q0.4) — not a separate repo and not a frozen copy-paste fork.  
**Confidence:** high  
**Notes:**
- Matches Q5.1 “one place.”
- Paper V1 logic stays behavior-compatible; live adds broker, fees, risk, audit modules.
**Defer?** no

### Q5.6 — Modes

Required modes before real money:

1. `sim` (current)
2. `broker_paper`
3. `live_dry_run` (compute orders, do not send)
4. `live`

**Answer:** Lock the four modes above as the promotion ladder: **`sim`** (current V1/V2 file paper) → **`broker_paper`** (live variant on IBKR paper, 2 weeks + graduation) → **`live_dry_run`** (real account, no send) → **`live`**. No skipping ahead for first go-live.  
**Confidence:** high  
**Notes:**
- Aligns with Q1.5.
- Mode is an explicit config/flag; dashboard can show current mode; alerts on mode changes (Q4.3).
**Defer?** no

---

## 6. Legal / tax / compliance (P1)

*Not legal advice — checklist so we know what to verify.*

### Q6.1 — Personal use only?

- Confirm: trading **your own** account only, not managing others’ money / selling signals as a service?

**Answer:** **v1 = your own IBKR account only.** Not a public product. Friends/family, if ever, each trade in **their own** brokerage account later — you do **not** place orders or pool funds for others in v1.  
**Confidence:** high  
**Notes:**
- Not legal advice; lowers regulatory complexity vs managing others’ money.
- Revisit before any multi-user design (Q0.1 caveat).
**Defer?** no

### Q6.2 — Tax lot / reporting needs

- Need wash-sale-like tracking? (Canada rules differ from US)
- Export format for accountant (IB activity flex)?

**Answer:** **No full tax engine in the app for v1.** Use **IBKR Flex / Activity** statements for the accountant; app **audit logs** support reconciliation only. Defer superficial-loss / lot-method details to accountant (R8).  
**Confidence:** high  
**Notes:** Not legal/tax advice.  
**Defer?** deep tax rules yes; reporting approach locked

### Q6.3 — Registered account policy

- If TFSA/RRSP: frequency limits you’re comfortable with; dividend withholding on US names

**Answer:** Live v1 stays in a **taxable** account only (Q1.2). **TFSA/RRSP/FHSA deferred** — revisit before any registered live trading (active-trading and US withholding considerations).  
**Confidence:** high  
**Notes:** Not legal/tax advice.  
**Defer?** registered live yes

---

## 7. Product / UX of the “new app” (P2 — after 0–6)

Fill only after broker + risk + architecture answers exist.

### Q7.1 — Who is the user?

- Only you, or future multi-user?

**Answer:** **Only you for v1.**  
**Confidence:** high  
**Notes:** Aligns with Q6.1. Multi-user / friends-family deferred.  
**Defer?** no

### Q7.2 — Surfaces

- CLI only?
- Streamlit / web dashboard with live toggles?
- Mobile notifications only?

**Answer:** Keep a **web/Streamlit (or equivalent) dashboard** as the primary way to see status — positions, mode, PnL vs B&H, alerts history — plus email/SMS for events (Q0.3 / Q4.3). Not CLI-only.  
**Confidence:** high  
**Notes:** Dashboard should run against the unified Oracle host (or securely read its state); live controls (disable/ack) ideally available without SSH (Q7.3).  
**Defer?** no

### Q7.3 — Config ergonomics

- Symbols, sizing, kill-switch, mode — edited where?
- Remote disable without SSH?

**Answer:** Day-to-day controls via **auth-protected dashboard**: symbols (live trio), mode, trading disable/enable, risk-alert **ack**. **Remote disable and ack without SSH** required (supports Q4.1 2h escalate). IB passwords and API secrets stay **VM-only** (env/Docker), not editable in the dashboard.  
**Confidence:** high  
**Notes:**  
**Defer?** no

### Q7.4 — What “done” looks like for v1 of live app

Minimum viable live:

- [ ] Unified app on Oracle Always Free: paper V1/V2 + live variant
- [ ] IB Gateway + IBC/IBeam + ib_insync; weekly 2FA alert
- [ ] Modes: `sim` → `broker_paper` → `live_dry_run` → `live`
- [ ] Live universe: MSFT, AAPL, SMH; all-in/out; market; RTH; queue for open
- [ ] Full fee model + after-fee vs equal-weight B&H
- [ ] Broker-truth reconcile; never-borrow; alert→2h→stop
- [ ] Dashboard + email (SMS optional); audit logs on host
- [ ] Pass 2-week IB paper + dry-run before first live $1k

**Answer:** **MVP checklist locked** (items above). Friends/family, TFSA, multi-cloud HA are out of v1 scope.  
**Confidence:** high  
**Notes:** Next artifact: `docs/live_trading_blueprint.md`.  
**Defer?** no
---

## 8. Open research tasks (fact-finding)

Track homework that isn’t a “preference” question:


| ID  | Task                                                                                                                   | Owner | Status   | Finding |
| --- | ---------------------------------------------------------------------------------------------------------------------- | ----- | -------- | ------- |
| R1  | Confirm IBKR Canada paper account + API path for your account type                                                     |       | open     |         |
| R2  | Build full US-equity fee model from IBKR Canada schedules + sample tickets: commission plan (Fixed vs Tiered), SEC/TAF/CAT/clearing/exchange, FX funding, withdrawals, GST; calibrate slippage from paper fills; reconcile vs Activity/Flex |       | closed   | **2026-10-07:** Prefer **IBKR Pro Tiered** for ~$1k (order min USD 0.35 vs Fixed 1.00). Rates in `app/fees/model.py` from IBKR Pro US stocks page: SEC 0.0000206, TAF 0.000195/sh (holiday 0.00 Oct–Dec 2026 on site), CAT 0.000003, clearing 0.00020 (Tiered), pass-throughs NYSE+FINRA on commission, max commission 1% TV. FX: **auto** 0.03% for small CAD→USD; manual IDEALPRO min $2 above ~$6.7k. λ live ≈ RT cost via `estimate_lambda_per_trip` (~$1–2.5 at 1 share + 5 bps slip). Venue exchange fees/rebates still approximate; reconcile vs Flex in G6 when fills exist. Withdrawals/GST monitored on statements (usually $0 early). |
| R3  | Fractional share availability for each universe symbol at IBKR (incl. VOO)                                             |       | closed   | 2026-10-07 paper: MSFT/AAPL/SMH/VOO have `sizeIncrement=0.0001` (desktop fractionals) but API returns **Error 10243** — cannot place fractional equities via API. Live bot uses **whole shares** only (`IbkrBroker.supports_fractional` default empty). |
| R4  | Cash vs margin buying-power behavior for same-day turnover                                                             |       | closed   | **2026-10-07 paper:** TotalCashValue / AvailableFunds / BuyingPower all exposed (CAD on DUR235447). BuyingPower ≈ 3.33× cash (margin leverage) — **never use for sizing**. Spendable = **AvailableFunds** (same-day unsettled credit); never-borrow checks `spendable_usd`. Wired in `AccountSnapshot` + planner/risk_limits. |
| R5  | Validate IB Gateway + IBC/IBeam on Oracle Always Free Linux: auto-restart, weekly 2FA alert path, disconnect/reconnect |       | closed   | **Done on OVH** (Oracle abandoned). systemd xvfb/ibgateway/live-worker/gateway-health; AutoRestartTime; ReloginAfterSecondFactor=yes; TWOFA_TIMEOUT_ACTION=restart; email alerts; health script flags IB Key wait → `weekly_2fa` email. Phone approve still human. |
| R6  | Whether IBKR free US (Cboe One/IEX) hourly bars align with strategy needs vs yfinance                                  |       | closed   | **2026-10-07 OVH paper:** `reqHistoricalData` 1h TRADES works for MSFT/AAPL/SMH/VOO. Last RTH close vs Yahoo abs diff ≤0.002%. `useRTH=True` → ~7 bars/session (good for peak/trough); `useRTH=False`/Yahoo prepost add many ext-hour bars — prefer RTH for live. Wired: `IbkrBroker.latest_hourly_closes` + live_worker IB-first/Yahoo fallback. Probe: `deploy/ibgateway/probe_us_bars.py`. |
| R7  | Questrade partner API — irrelevant unless pursuing partnership                                                         |       | deferred |         |
| R8  | Tax / accountant note for expected trade frequency                                                                     |       | open     |         |
| R9  | Confirm IBKR complimentary US streaming + historical API for live symbol list; yfinance fallback for paper until wired |       | closed   | Confirmed with R6 on paper account. Complimentary historical hourly sufficient for signal path; Yahoo remains fallback if IB empty/errors. |


---

## 9. Walkthrough log

Record each session so we don’t re-litigate.


| Date       | Question(s)    | Outcome                                                                                                                                                       | Next                    |
| ---------- | -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- |
| 2026-09-21 | Q0.1           | Success = beat equal-weight B&H of live universe **after all fees**; users = self + possible friends/family (not public product); V1→V2 same objective        | Q0.2                    |
| 2026-09-21 | Q0.2           | **Amended:** ~$1,000 **total** start (ratios TBD); scale with confidence toward ~hundreds of k; indefinite horizon; no DD kill — withdraw only if cash needed | Q0.3                    |
| 2026-09-21 | Q0.3           | Fully auto execution; alerts configurable (email/SMS × what × when) + interval summaries                                                                      | Q0.4                    |
| 2026-09-21 | Q0.4           | Keep paper V1+V2 running for lessons; live = **new fee/platform-aware variant** (not raw V2)                                                                  | Q1.1                    |
| 2026-09-21 | Q1.1           | **IBKR Canada** — only practical official path for fully auto US+TSX                                                                                          | Q1.2                    |
| 2026-09-21 | Q1.2 (partial) | **Individual + taxable**; cash vs margin explained, awaiting choice                                                                                           | Finish Q1.2 cash/margin |
| 2026-09-21 | Q1.2           | Individual, taxable, **margin open but never borrow**                                                                                                         | Q1.3                    |
| 2026-09-21 | Q1.3           | **Amended:** USD-only; fund via chunk CAD→USD; no CAD trading sleeve (`ZSP.TO`→VOO)                                                                           | Q1.4                    |
| 2026-09-21 | Q1.4           | **Finalized:** IBKR free US Cboe One/IEX for live; $0 paid data; no TSX data needed                                                                           | Q1.5                    |
| 2026-09-21 | Q1.5           | IBKR paper **2 weeks** + graduation checklist; then **real-account dry-run** before live                                                                      | Q2.1                    |
| 2026-09-21 | Q2.1           | **Include all applicable fees** (full A–E checklist); monitor policy-$0 items; verify vs IB statements (R2)                                                   | Q2.2                    |
| 2026-09-23 | Q2.2           | **Yes** — retune λ / live trade penalty from full fee model (numeric after R2)                                                                                | Q2.3                    |
| 2026-09-23 | Q2.3           | Live starts with **~2–3 symbols**; locked trio = **MSFT, AAPL, SMH** (Q3.6)                                                    | Q2.4                    |
| 2026-09-23 | Q2.4           | **IBKR fractionals when available**, else whole shares + leftover cash                                                        | Q2.5                    |
| 2026-09-23 | Q2.5           | Margin **buying power** for same-day turnover; still **never borrow** / no overnight debit                                    | Q3.1                    |
| 2026-09-23 | Q3.1           | Live sizing = **all-in / all-out per sleeve** (paper style)                                                                   | Q3.2                    |
| 2026-09-23 | Q3.2           | **Market orders**; cancel leftovers / no retry storms on reject; slippage in fee model                                        | Q3.3                    |
| 2026-09-23 | Q3.3           | **US RTH only**; if closed, **queue for next open** (no overnight GTC market)                                                 | Q3.4                    |
| 2026-09-23 | Q3.4           | Hourly bars + ~10m poll; UTC timestamps; RTH gate; **idempotent per symbol+bar**                                              | Q3.5                    |
| 2026-09-23 | Q3.5           | **Broker wins**; reconcile every run; alert on drift                                                                          | Q3.6                    |
| 2026-09-23 | Q3.6           | Live trio by edge analysis: **MSFT, AAPL, SMH**; paper keeps full USD list + VOO                                              | Q4.1                    |
| 2026-09-23 | Q4.1           | Risk events: **alert first**; if no user ack in **2h** → auto-stop; per-order policy still instant; flatten manual            | Q4.2                    |
| 2026-09-23 | Q4.2           | **Fail safe**: no orders on unknown state; alert; reconcile; partials=broker; escalate via 2h stop                            | Q4.3                    |
| 2026-09-23 | Q4.3           | Defaults: immediate fill/error/risk/stop alerts; **daily after-fee vs B&H** summary; email on; live+paper dashboard            | Q4.4                    |
| 2026-09-23 | Q4.4           | Full audit log on live host (not git); IBKR Flex backup; retain ≥~2 years                                                     | Q5.1                    |
| 2026-09-23 | Q5.1           | **One place**: paper V1+V2 + live on single always-on deployment (not GHA/live split)                                          | Q5.2                    |
| 2026-09-23 | Q5.2           | **Single host: Oracle Always Free** for now; migrate later if needed (not dual-cloud)                                         | Q5.3                    |
| 2026-09-23 | Q5.3           | **IB Gateway + IBC/IBeam + ib_insync**; auto-restart; weekly 2FA = user alert                                                  | Q5.4                    |
| 2026-09-23 | Q5.4           | Secrets on VM (env/Docker); SSH key-only; Gateway localhost-only; rotate + disable on leak                                    | Q5.5                    |
| 2026-09-23 | Q5.5           | **Extend this repo** (broker module + modes); shared strategy; fee-aware live path                                            | Q5.6                    |
| 2026-09-23 | Q5.6           | Modes ladder: `sim` → `broker_paper` → `live_dry_run` → `live`                                                                | Q6.1                    |
| 2026-09-23 | Q6.1           | **Own IBKR account only** for v1; friends/family later = their own accounts                                                   | Q6.2                    |
| 2026-09-23 | Q6.2           | No in-app tax engine; **IBKR Flex/Activity** + audit for accountant; deep tax → R8                                            | Q6.3                    |
| 2026-09-23 | Q6.3           | Live v1 **taxable only**; registered accounts deferred                                                                        | Q7.1                    |
| 2026-09-23 | Q7.1           | **Only you** for v1                                                                                                           | Q7.2                    |
| 2026-09-23 | Q7.2           | Keep **dashboard (Streamlit/web)** + email/SMS; not CLI-only                                                                  | Q7.3                    |
| 2026-09-23 | Q7.3           | Dashboard for mode/symbols/disable/ack (no SSH); secrets stay on VM                                                           | Q7.4                    |
| 2026-09-23 | Q7.4           | **MVP checklist locked**; investigation complete → blueprint                                                                  | blueprint               |
| 2026-09-21 | Q3.6           | Universe USD-only; **VOO replaces ZSP.TO** in V1, V2, and future live                                                                                         | (applied in configs)    |


---

## 10. Locked decisions (promote when ready)


| Topic                 | Decision                                                                                     | Date       | Confidence |
| --------------------- | -------------------------------------------------------------------------------------------- | ---------- | ---------- |
| Success metric        | Beat **equal-weight buy-and-hold of the live universe** from the same start                  | 2026-09-21 | high       |
| Cost bar              | Must beat that B&H **after all fees** (commissions, FX, slippage, etc.)                      | 2026-09-21 | high       |
| Intended users        | Personal capital first; may extend to close friends/family later — not a public product      | 2026-09-21 | high       |
| Friends/family caveat | Before non-self money: revisit Q6.1 (advice / multi-account)                                 | 2026-09-21 | n/a        |
| Starting capital      | ~$1,000 **total** portfolio; per-symbol ratio undecided                                      | 2026-09-21 | high       |
| Scale path            | Add capital as confidence grows; eventual size possibly a couple hundred thousand            | 2026-09-21 | medium     |
| Live horizon          | Indefinite; continuous improvement                                                           | 2026-09-21 | high       |
| Drawdown stop         | No strategy kill on max DD; exit capital only via personal withdrawal need                   | 2026-09-21 | high       |
| Execution             | Fully automatic (no per-trade approval)                                                      | 2026-09-21 | high       |
| Alerts                | Configurable channel (email/SMS), event types, timing; plus summaries on agreed interval     | 2026-09-21 | high       |
| Paper bots            | Keep V1 and V2 paper running in parallel for learning / comparison                           | 2026-09-21 | high       |
| Live logic            | New live variant (not verbatim V2) — accounts for fees and platform limits                   | 2026-09-21 | high       |
| Primary broker        | Interactive Brokers Canada (IBKR) for fully auto API trading                                 | 2026-09-21 | high       |
| Account holder        | Individual                                                                                   | 2026-09-21 | high       |
| Account tax wrapper   | Taxable (non-registered) for first live book                                                 | 2026-09-21 | high       |
| Margin policy         | Margin account allowed; live bot must never borrow / no overnight debit                      | 2026-09-21 | high       |
| FX policy             | **USD-only** book; convert CAD→USD in chunks when funding; no per-trade FX                   | 2026-09-21 | high       |
| Market data           | IBKR complimentary **US Cboe One/IEX** real-time; **$0** paid subscriptions                  | 2026-09-21 | high       |
| Universe              | US-only paper: AAPL, AMD, GOOG, MSFT, NVDA, SMH, VOO; **live start: MSFT, AAPL, SMH**         | 2026-09-23 | high       |
| Paper + live symbols  | V1/V2 paper use full list with **VOO**; live concentrates on MSFT/AAPL/SMH                     | 2026-09-23 | high       |
| Position truth        | **IBKR broker wins**; reconcile every run; alert on unexpected drift                                     | 2026-09-23 | high       |
| Paper trading path    | IBKR paper **2 weeks** + graduation criteria; then real-account `live_dry_run` before `live` | 2026-09-21 | high       |
| Cost model            | **All applicable fees in** (commission, exchange/clearing/reg, FX, withdrawals, GST if any, slippage); policy $0 items still monitored | 2026-09-21 | high       |
| Trade penalty λ       | **Retune** for live from fee model (~$1–2.5 RT at 1-share + slip); paper V2 λ=20 kept for continuity     | 2026-10-07 | high       |
| Live universe size    | Start with **~2–3 symbols** at $1k; expand as capital grows; paper may keep full list                    | 2026-09-23 | high       |
| Share sizing          | IBKR **fractionals when available**; otherwise whole shares (residual cash idle)                         | 2026-09-23 | high       |
| Buying power          | Use margin BP for same-day sell→buy; hard ban on debit / overnight borrow                                | 2026-09-23 | high       |
| Live sizing           | **All-in / all-out per sleeve** (match paper)                                                            | 2026-09-23 | high       |
| Order type            | **Market** orders; cancel any residual; no silent retry storms                                           | 2026-09-23 | high       |
| Trading session       | **US RTH only**; queue signals for next open; no extended-hours trading                                  | 2026-09-23 | high       |
| Clock / bars          | Hourly bars, ~10m poll, UTC storage, RTH gate, idempotent per symbol+bar                                 | 2026-09-23 | high       |
| Risk controls         | Alert on thresholds; **auto-stop if no ack within 2 hours**; instant blocks only for per-order policy; panic flatten manual | 2026-09-23 | high       |
| Failure modes         | Fail safe; broker reconcile; no retry storms; alert→2h stop for persistent faults                              | 2026-09-23 | high       |
| Monitoring defaults   | Immediate: fills/errors/disconnects/risk/stop; daily after-fee vs B&H summary; email on; live+paper UI          | 2026-09-23 | high       |
| Audit trail           | Log all intents/fills/fees/FX/alerts/acks; live host storage (not git); IBKR Flex backup; ≥~2y retention        | 2026-09-23 | high       |
| Process split         | **Unified always-on home** for paper V1/V2 + live; not split across Actions vs separate live app               | 2026-09-23 | high       |
| Hosting               | **Single Oracle Always Free VM** for now; optional later migrate to paid Canada VPS if needed                  | 2026-09-23 | high       |
| Broker connectivity   | **IB Gateway + IBC/IBeam + ib_insync**; auto-restart; weekly 2FA via user alert                                 | 2026-09-23 | high       |
| Secrets / security    | VM env/Docker secrets; SSH keys; Gateway localhost-only; rotate + disable on leak                              | 2026-09-23 | high       |
| Codebase              | **Extend this repo**; shared strategy; dedicated live/broker modules                                           | 2026-09-23 | high       |
| Modes                 | `sim` → `broker_paper` → `live_dry_run` → `live` (no skip on first go-live)                                     | 2026-09-23 | high       |
| Users (v1)            | **Own account only**; no managing others’ money in v1                                                          | 2026-09-23 | high       |
| Tax reporting         | IBKR Flex/Activity + app audit; no full tax engine in v1                                                       | 2026-09-23 | high       |
| Account wrapper       | Live v1 **taxable only**; TFSA/RRSP deferred                                                                   | 2026-09-23 | high       |
| UX user               | Single user (you) for v1                                                                                       | 2026-09-23 | high       |
| UX surfaces           | Keep web/Streamlit dashboard + email/SMS alerts                                                                | 2026-09-23 | high       |
| UX controls           | Dashboard: mode/symbols/disable/ack without SSH; secrets VM-only                                               | 2026-09-23 | high       |
| v1 MVP                | Checklist in Q7.4 locked; ready for blueprint                                                                  | 2026-09-23 | high       |


---

## 11. After this doc: next artifact

1. ~~Blueprint~~ → `docs/live_trading_blueprint.md` (TDD prompt series)  
2. ~~Todo~~ → `docs/live_trading_todo.md`  
3. Implement starting at **Prompt 01**

Start next with: **“Implement Prompt 01”** (or paste Prompt 01 from the blueprint).
## Appendix A — Current system snapshot (context)

- **Today:** alerts + simulation; **does not** place broker orders (`README.md`).
- **Worker:** `python -m app.worker --version v1|v2`
- **Scheduler:** GitHub Actions (~10 minutes)
- **Data:** yfinance hourly today; live target = IBKR free US (Cboe One/IEX)
- **Universe:** AAPL, AMD, GOOG, MSFT, NVDA, SMH, **VOO** (replaced `ZSP.TO` 2026-09-21)
- **Strategy:** peak/trough thresholds; full sleeve cash ↔ shares; V2 adds constraints, trade penalty λ, holdout validation, meta reopt

## Appendix B — Cost / limit reminders (Canada / IBKR — verify before locking)

- US tiered commission ~USD 0.0035/share, min ~USD 0.35
- CAD / TSX commissions — **out of scope** for current USD-only universe
- FX: funding CAD→USD only (~0.20 bp, min ~USD 2) — not per equity trade
- No IBKR Canada inactivity fee / $0 account min (retail Gateway/API)
- **Free** IBKR US streaming via Cboe One/IEX (non-consolidated); paid packs optional later
- Simulation fractional shares ≠ guaranteed live fractionals
- Cash T+1 vs margin buying power differs
- Official pages to re-check when answering R2–R5:
  - [https://www.interactivebrokers.ca/en/pricing/commissions-stocks.php](https://www.interactivebrokers.ca/en/pricing/commissions-stocks.php)
  - [https://www.interactivebrokers.ca/en/pricing/market-data-pricing.php](https://www.interactivebrokers.ca/en/pricing/market-data-pricing.php)
  - [https://www.interactivebrokers.ca/en/accounts/required-minimums.php](https://www.interactivebrokers.ca/en/accounts/required-minimums.php)

## Appendix C — Suggested walkthrough order

1. **Q0.1–Q0.4** — goals
2. **Q1.1–Q1.5** — broker/account
3. **Q2.1–Q2.5** — fees/friction
4. **Q3.1–Q3.6** — execution gaps
5. **Q4.1–Q4.4** — risk/ops
6. **Q5.1–Q5.6** — architecture
7. **Q6.*** — compliance comfort
8. Then **Q7.*** + blueprint

Start next chat/session with: **“Draft the live trading todo”** or begin Phase 0