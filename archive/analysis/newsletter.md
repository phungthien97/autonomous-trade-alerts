# I Taught a Free Bot to Trade While I Sleep. Here's What Happened

**Period covered:** May 6 to July 20, 2026 (~10 weeks)  
**Capital:** $1,000 paper cash per symbol  
**Symbols:** AAPL, AMD, GOOG, MSFT, NVDA, SMH, ZSP.TO

---

## TLDR

**How it works:** watch the peak and the trough, sell on a drop, buy on a bounce, email me when something happens.

**How it did (May to July 2026):** the equal-weight paper portfolio returned **+3.97%** vs buy-and-hold's **+0.69%**. It won more often than it lost, but not on every ticker, especially the noisy ones.

Alerts only. No brokerage orders. Treat this as a live experiment log from a hobby project, not investment advice.

---

## Why I built this

I didn't want to stare at charts all day. I wanted to know whether a dead-simple rule could run on its own, for free, and do better than just holding: sell after a drop from a recent peak, then buy after a bounce from a recent trough.

So I built a small bot as a weekend project and let it run for about ten weeks. It watches a handful of stocks, makes paper trades, and emails me whenever it decides to buy or sell.

One thing up front: this bot never touches real money. It simulates every trade on paper and only sends me alerts. Think of it as a live experiment log, not an account statement.

---

## What I built

### How the bot decides, in one sentence

While **holding**, it tracks the highest price it has seen (the peak). If price falls far enough from that peak, it **sells**. While in **cash**, it tracks the lowest price it has seen (the trough). If price rises far enough from that trough, it **buys**.

Those "far enough" amounts are just percentages. For example, sell after a 1% drop from the peak and buy after a 2% rise from the trough. Every symbol gets its own pair of settings.

### How the thresholds tune themselves

Here's the part I find most interesting: the bot doesn't keep the same thresholds forever. On a schedule, it **re-tunes** them per symbol using recent price history.

**When it runs:** at most once every `reopt_days` calendar days per symbol (default **5**). The first run always tunes; after that, it only re-tunes once enough days have passed since the last one.

**What it looks at:** the last `x_days` trading days of hourly closes (default **20**), pulled from Yahoo Finance.

**How it chooses:** it replays the peak/trough rule over that window for every combination of:

- **Buy rise:** 1.0% to 15.0% in 0.5% steps (how far price must bounce off a trough to trigger a buy)
- **Sell drop:** 1.0% to 15.0% in 0.5% steps (how far price must fall from a peak to trigger a sell)

Whichever pair *would have* produced the highest paper value on that window wins. The new settings get written to `state/config.json`, used immediately, and logged to `state/params_history.csv`.


| Setting      | Default | Role                                              |
| ------------ | ------- | ------------------------------------------------- |
| `x_days`     | 20      | Training lookback (trading days of hourly closes) |
| `reopt_days` | 5       | Minimum days between re-tunes per symbol          |


Here's an actual snapshot from the Jul 20 re-tune across the portfolio:


| Symbol | Buy rise | Sell drop | Simulated train P/L |
| ------ | -------- | --------- | ------------------- |
| AMD    | 1.0%     | 1.0%      | $1,033              |
| NVDA   | 11.5%    | 1.0%      | $999                |
| MSFT   | 1.0%     | 1.0%      | $1,055              |


Hold onto those numbers. AMD's tight 1%/1% pair is exactly why it churned so much. NVDA's lopsided 11.5%/1% pair was hard to get back in with and quick to get shaken out of, and it shows up later as a string of bad trades.

The obvious risk is that this is all backward-looking. The tuner fits *past* bars, and a setting that looked perfect over the last 20 days can be wrong for the next 20. That's not a hypothetical. I watched it happen.

### The loop that runs in the cloud

Every ~10 minutes, a scheduled job:

1. Pulls the latest hourly price bar (Yahoo Finance, including extended hours when available)
2. Re-tunes thresholds if that symbol is due, then takes one bot step (hold / buy / sell)
3. Logs portfolio value and any trade
4. Emails an alert if a signal fired
5. Commits the updated logs back into the repo under `state/`

A small Streamlit dashboard reads those same files, so I can check equity, trades, and settings without touching the worker.

---

## The experiment

I gave each of seven symbols **$1,000** of paper cash and let the bot run from **May 6 to July 20, 2026**. The lineup was AAPL, AMD, GOOG, MSFT, NVDA, SMH, and ZSP.TO. It is a mix I actually follow: a few big tech names, two semis (NVDA and the SMH ETF), and a Canadian index ETF (ZSP.TO) to see how a calmer instrument behaved.

To judge it fairly, I compared against plain buy-and-hold:

- Invest $1,000 at the same entry price the bot used for its first allocation
- Do nothing until the end of the logged window
- Return % = (ending value ÷ $1,000 − 1) × 100

The bot's number is just the last paper portfolio value it logged for that symbol (cash + shares after all its trades).

---

## Results

### Per symbol


| Symbol | Buy & Hold | The Bot | Edge (Bot − B&H) | Winner     |
| ------ | ---------- | ------- | ---------------- | ---------- |
| AAPL   | +11.24%    | +18.31% | +7.07%           | The Bot    |
| AMD    | +10.85%    | +8.47%  | −2.38%           | Buy & Hold |
| GOOG   | −11.20%    | −8.96%  | +2.24%           | The Bot    |
| MSFT   | −3.41%     | +10.09% | +13.50%          | The Bot    |
| NVDA   | −5.67%     | −12.40% | −6.73%           | Buy & Hold |
| SMH    | −1.31%     | +10.14% | +11.45%          | The Bot    |
| ZSP.TO | +4.30%     | +2.12%  | −2.18%           | Buy & Hold |


*(Edge = The Bot return minus Buy & Hold return)*

### Portfolio (equal $1,000 in each of the 7 names)


|                  | Buy & Hold | The Bot    |
| ---------------- | ---------- | ---------- |
| Starting capital | $7,000     | $7,000     |
| Ending value     | $7,048     | $7,278     |
| Total P/L        | +$48       | +$278      |
| Return           | **+0.69%** | **+3.97%** |


Across the whole basket, the bot finished about **+3.3%** ahead of equal-weight buy-and-hold, winning on **4 of 7** symbols.

What surprised me most wasn't the overall number. It was how *unevenly* it got there. A couple of names carried the whole thing:

- **MSFT** and **SMH** were the clearest wins: the bot turned flat-to-down buy-and-hold stretches into roughly **+10%** paper gains by stepping aside on drops and buying dips.
- **AAPL** was strong either way; the bot still added about **+7%** on top of an already good hold.
- **NVDA** was the ugly one: buy-and-hold lost ~6%, while the bot lost ~12%. Choppy sells and rebuys hurt more than sitting still.
- **AMD** traded constantly (dozens of round-trips) and still trailed a simple hold by a couple of points.

---

## What worked, and what didn't

The headline hides two very different stories. The bot doesn't win by picking *better* stocks. It wins or loses based on **how price moved** and **how often it traded**.

Four patterns kept showing up:


| Pattern                               | What happened                                                           | Who won                    |
| ------------------------------------- | ----------------------------------------------------------------------- | -------------------------- |
| **Decline or chop, bot steps aside**  | Stock ends flat/down; bot spends real time in cash during drawdowns     | The Bot (MSFT, SMH, GOOG)  |
| **Clean uptrend, swings captured**    | Stock rises; bot sells rips and rebuys dips with profitable round-trips | The Bot (AAPL)             |
| **Uptrend + tight thresholds**        | Stock grinds up; 1% sell / 1% buy triggers constant whipsaw             | Buy & Hold (AMD, ZSP.TO)   |
| **Falling stock + bad threshold mix** | High buy bar (late entries) + tight sell (quick exits) erodes capital   | Buy & Hold (NVDA)          |


A quick note on the charts below: the **top** panel shows price with BUY (▲) / SELL (▼) markers and yellow shading whenever the bot was sitting in cash. The **bottom** panel compares buy & hold (dashed blue) against the bot (solid green), both starting from $1,000.

### The wins

**MSFT (−3.4% hold → +10.1% the bot):** the textbook defensive win.

- The stock drifted down overall, but with sharp interim drops (buy-and-hold's max drawdown hit **−24%**).
- The bot was invested only **~51%** of the time. Its own max drawdown: **−8%**.
- Fifteen round-trips, more losers than winners (6W / 9L), and it didn't matter. **Being in cash during the worst slides** beat trade accuracy.
- It ended **still holding shares**, so it caught the late bounce too.

MSFT timeline

Price drifts down but the bot steps aside during the steepest drops (yellow bands). The green line stays flat-to-up while blue bleeds.

**SMH (−1.3% hold → +10.1% the bot):** same playbook on a semiconductor ETF.

- Similar story: choppy path, **63%** time in market, drawdown cut from **−18%** to **−14%**.
- Eighteen round-trips with a **6W / 12L** record. Again, defense beat offense.
- Ended in **cash at $1,101** vs $987 if held. That last leg of the hold was worth missing.

SMH timeline

Same defensive pattern as MSFT: cash during drawdowns, re-enter on bounces. Ends in cash above the buy-and-hold line.

**GOOG (−11.2% hold → −9.0% the bot):** losing less is still winning.

- A straight decline. The bot was invested only **41%** of the time.
- Round-trips were mostly losers (1W / 5L, avg **−1.5%** per trip), yet it still beat hold by **+2.2%**. **Sitting out most of a −11% slide** beat trying to trade it.

GOOG timeline

A falling stock. The bot spends most of the slide in cash (wide yellow bands). Both lines lose, but green loses less.

**AAPL (+11.2% hold → +18.3% the bot):** the rare offensive win.

- The stock rose, and the bot actually traded it well: 4 round-trips, **4 wins, 0 losses**, avg **+4.4%** per trip.
- Sold near **$326** on Jul 20 after buying dips at **$284** and **$319**.
- Drawdown halved (**−4.6%** vs **−12.6%**). This is the dream case: uptrend plus clean swing capture.

AAPL timeline

Clean uptrend with profitable swing trades; the green line pulls ahead after each well-timed sell-and-rebuy.

### The losses

**AMD (+10.8% hold → +8.5% the bot):** death by a thousand whipsaws.

- AMD trended up, but the bot ran **26 round-trips** on **1% buy / 1% sell** thresholds. Those were the tightest settings in the portfolio.
- Record: **9W / 17L**. Average trip just **+0.4%**, but it kept selling small dips and rebuying slightly higher in a grinding rally.
- Ended **in cash**, missing about **$24** of the final close. That is small next to the **~$100+** lost to overtrading along the way.
- The lesson: tight symmetric thresholds on a steadily rising, noisy stock is the bot's worst enemy.

AMD timeline

Steady uptrend with dense BUY/SELL markers (26 round-trips). Whipsaw trades keep the green line below the simple hold.

**NVDA (−5.7% hold → −12.4% the bot):** the wrong threshold shape for a choppy decline.

- Only **33%** time in market (usually a good thing in a decline), but round-trips were **1W / 6L**, avg **−1.8%** each.
- Its thresholds at the time: **+11.5% to buy, −1% to sell** (set by the Jul 20 re-tune; see *How the thresholds tune themselves*). It is a lopsided combo: wait for a big bounce to re-enter, then dump on the first 1% pullback.
- One painful example: bought **$209** on Jul 10 and sold **$201** on Jul 17. It bought near a local top, then sold the dip.
- Its max drawdown was actually **worse** than buy-and-hold (−21% vs −20%). Sitting out didn't help, because the trades it *did* make were bad ones.

NVDA timeline

Choppy decline with late, high buys and quick sells. The green line drops further than blue despite time in cash.

**ZSP.TO (+4.3% hold → +2.1% the bot):** a calm ETF with nothing to defend against.

- Only **5 round-trips**, mostly winners (4W / 1L). The trades weren't the problem.
- Max drawdown was identical to buy-and-hold (**−4%**). The ETF barely moved, so there was no downside to dodge.
- Ended **in cash** on Jul 17 at **$114.39**, missing the drift to **$114.65**. A small edge given up just by being out of a slow, steady climb.
- The lesson: on a calm, low-volatility uptrend, the cost of exiting and re-entering outweighs any protection.

ZSP.TO timeline

Low-volatility grind higher. There were few trades and little drawdown to defend, so exiting cost more than it saved.

---

## What I learned

Stepping back, five things drove nearly every outcome:

1. **Time out of the market during drawdowns** was the single biggest win driver (MSFT, SMH, GOOG).
2. **Profitable swing trades in an uptrend** were a bonus when they happened (AAPL).
3. **Threshold tightness:** 1%/1% on AMD forced 26 trips, and the whipsaw tax ate the gains.
4. **Threshold asymmetry:** NVDA's +11.5% buy / −1% sell literally buys high and sells low.
5. **Ending position:** six of seven symbols ended **in cash**. That helped on the losers (GOOG, SMH) but hurt on the steady climbers (AMD, ZSP.TO). MSFT was the only one still invested at the close.

My rough rule of thumb after all this: the peak/trough bot helps when price **falls hard or chops sideways**, and it hurts when price **grinds up smoothly** or when the thresholds force **too many round-trips**.

---

## What's next (v2)

Almost all of the underperformance traces back to one piece: **the threshold tuner**. The core peak/trough logic worked fine on MSFT, SMH, and AAPL. The tuner is what occasionally picked settings that looked great on the last 20 days and then traded badly live (AMD 1%/1%, NVDA 11.5%/1%).

For the next version, I want to fix the tuner in three ways. All of them are in the optimization step, without touching the buy/sell logic itself.

### 1. Constrained parameter search

**Problem:** the grid search can pick extreme pairs, like NVDA's **+11.5% buy / −1% sell** (hard to re-enter, quick to exit).

**Fix:** add guardrails to the search:


| Rule                     | Example                                           |
| ------------------------ | ------------------------------------------------- |
| Floor on both thresholds | buy rise and sell drop each **≥ 1.5% to 2%**      |
| Cap on buy rise          | buy rise **≤ ~8%** (no waiting for a huge bounce) |
| Limit asymmetry          | sell drop **≥ half of buy rise**                  |


**Expected impact:** blocks the worst NVDA-style combos and keeps re-tunes in a sensible band for everything.

### 2. Penalize overtrading

**Problem:** AMD landed on **1% / 1%** with **26 round-trips**. The tuner maximized in-sample P/L by trading too much in a grinding rally.

**Fix:** score each candidate pair as:

`score = simulated P/L − λ × number of round-trips`

instead of raw P/L alone.

**Expected impact:** prefers wider, calmer thresholds when extra trades don't earn their keep. Aimed straight at AMD-style whipsaw.

### 3. Holdout validation before applying new thresholds

**Problem:** the Jul 20 NVDA re-tune "won" on training data (~$999 simulated) but then **lost more live** than buy-and-hold. That is textbook overfit.

**Fix:** split the `x_days` window:

1. **Train** (~15 days) → pick the best constrained, penalized params
2. **Validate** (~5 days) → only apply if the new params beat the current ones on that holdout slice
3. If it fails → **keep the existing thresholds** and log "re-opt rejected"

**Expected impact:** stops bad re-tunes from ever going live, and cuts down needless churn on symbols that are already working (MSFT, SMH, AAPL).

### What "better" would look like


| Metric                            | Today          | Target                      |
| --------------------------------- | -------------- | --------------------------- |
| Extreme pairs (e.g. 11.5% / 1%)   | Possible       | Blocked                     |
| High trip count on uptrends (AMD) | 26 round-trips | Fewer, wider bands          |
| Re-opt always applied             | Yes            | Rejected when holdout fails |


There's a longer list of ideas too: slower re-tuning, a passive mode for calm ETFs like ZSP.TO, and regular-hours-only bars. Those can wait. These three go after the root cause I actually saw in this run.

---

## Reading this honestly

A few things I want to be upfront about, because this is an experiment and not a track record:

- The results use logged model prices, not real fills, spreads, fees, or taxes.
- Extended-hours bars can move both the bot and the "end" price used for buy-and-hold.
- The threshold tuner only fits recent history. See *How the thresholds tune themselves* for the mechanism and the overfitting risk.
- Seven symbols over ~10 weeks is a sample, not a career.

What it *does* show is that, for this window and these names, a fully automated peak/trough alerter **beat passive holding on paper**. It did that mostly by cutting losses on a few stocks and locking in gains on others, while underperforming where price chopped hard (NVDA, AMD).