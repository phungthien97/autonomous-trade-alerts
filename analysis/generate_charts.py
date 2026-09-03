"""Generate per-symbol timeline charts for the newsletter."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
OUT = Path(__file__).resolve().parent / "charts"

SYMBOLS = ["AAPL", "AMD", "GOOG", "MSFT", "NVDA", "SMH", "ZSP.TO"]
INITIAL_CASH = 1000.0

plt.style.use("seaborn-v0_8-whitegrid")


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    eq = pd.read_csv(STATE / "equity.csv")
    tr = pd.read_csv(STATE / "trades.csv")
    cfg = json.loads((STATE / "config.json").read_text(encoding="utf-8"))
    eq["Datetime"] = pd.to_datetime(eq["Datetime"], utc=True)
    tr["Datetime"] = pd.to_datetime(tr["Datetime"], utc=True)
    tr["symbol"] = tr["symbol"].fillna("ZSP.TO")
    return eq, tr, cfg


def entry_price(trades: pd.DataFrame, symbol: str) -> float:
    row = trades[
        (trades["symbol"] == symbol)
        & trades["Reason"].astype(str).str.contains("Initial full allocation", na=False)
    ].iloc[0]
    return float(row["Price"])


def chart_symbol(
    symbol: str,
    equity: pd.DataFrame,
    trades: pd.DataFrame,
    out_dir: Path,
) -> dict:
    e = equity[equity["symbol"] == symbol].sort_values("Datetime").copy()
    t = trades[trades["symbol"] == symbol].sort_values("Datetime")
    entry = entry_price(trades, symbol)

    e["bh_value"] = INITIAL_CASH / entry * e["Close"]
    e["in_market"] = e["Shares"] > 0

    bh_ret = (e["bh_value"].iloc[-1] / INITIAL_CASH - 1) * 100
    st_ret = (e["Portfolio_Value"].iloc[-1] / INITIAL_CASH - 1) * 100
    winner = "Strategy" if st_ret > bh_ret else ("Buy & Hold" if bh_ret > st_ret else "Tie")

    fig, (ax_price, ax_eq) = plt.subplots(
        2,
        1,
        figsize=(11, 6.5),
        sharex=True,
        gridspec_kw={"height_ratios": [1.1, 1], "hspace": 0.08},
    )
    fig.patch.set_facecolor("#fafafa")

    # Shade cash periods on price panel
    in_cash = ~e["in_market"]
    if in_cash.any():
        starts: list[pd.Timestamp] = []
        ends: list[pd.Timestamp] = []
        cash_on = False
        for dt, is_cash in zip(e["Datetime"], in_cash):
            if is_cash and not cash_on:
                starts.append(dt)
                cash_on = True
            elif not is_cash and cash_on:
                ends.append(dt)
                cash_on = False
        if cash_on:
            ends.append(e["Datetime"].iloc[-1])
        for s, en in zip(starts, ends):
            ax_price.axvspan(s, en, color="#fde68a", alpha=0.35, linewidth=0)

    ax_price.plot(e["Datetime"], e["Close"], color="#64748b", linewidth=1.4, label="Close price")
    buys = t[t["Action"] == "BUY"]
    sells = t[t["Action"] == "SELL"]
    ax_price.scatter(
        buys["Datetime"],
        buys["Price"],
        marker="^",
        s=70,
        color="#16a34a",
        edgecolors="white",
        linewidths=0.6,
        zorder=5,
        label="BUY",
    )
    ax_price.scatter(
        sells["Datetime"],
        sells["Price"],
        marker="v",
        s=70,
        color="#dc2626",
        edgecolors="white",
        linewidths=0.6,
        zorder=5,
        label="SELL",
    )
    ax_price.set_ylabel("Price ($)")
    ax_price.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax_price.set_title(
        f"{symbol}  ·  Buy & Hold {bh_ret:+.1f}%  vs  Strategy {st_ret:+.1f}%  ·  {winner} wins",
        fontsize=12,
        fontweight="bold",
        loc="left",
        pad=10,
    )

    cash_patch = Patch(facecolor="#fde68a", alpha=0.5, label="In cash (not invested)")
    ax_price.legend(
        handles=[
            plt.Line2D([0], [0], color="#64748b", linewidth=1.4, label="Close price"),
            plt.Line2D([0], [0], marker="^", color="w", markerfacecolor="#16a34a", markersize=8, label="BUY"),
            plt.Line2D([0], [0], marker="v", color="w", markerfacecolor="#dc2626", markersize=8, label="SELL"),
            cash_patch,
        ],
        loc="upper left",
        fontsize=8,
        framealpha=0.9,
    )

    ax_eq.axhline(INITIAL_CASH, color="#94a3b8", linewidth=0.8, linestyle=":", alpha=0.8)
    ax_eq.plot(
        e["Datetime"],
        e["bh_value"],
        color="#2563eb",
        linewidth=1.6,
        linestyle="--",
        label=f"Buy & Hold ({bh_ret:+.1f}%)",
    )
    ax_eq.plot(
        e["Datetime"],
        e["Portfolio_Value"],
        color="#059669",
        linewidth=1.8,
        label=f"Strategy ({st_ret:+.1f}%)",
    )
    ax_eq.set_ylabel("Portfolio ($)")
    ax_eq.set_xlabel("Date (UTC)")
    ax_eq.legend(loc="upper left", fontsize=8, framealpha=0.9)
    ax_eq.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax_eq.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    fig.autofmt_xdate(rotation=30, ha="right")

    for ax in (ax_price, ax_eq):
        ax.set_facecolor("#ffffff")
        ax.grid(True, alpha=0.35)

    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"timeline_{symbol.replace('.', '_')}.png"
    path = out_dir / fname
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)

    return {
        "symbol": symbol,
        "file": fname,
        "bh_ret": bh_ret,
        "st_ret": st_ret,
        "winner": winner,
    }


def main() -> None:
    eq, tr, _ = load_data()
    meta = [chart_symbol(sym, eq, tr, OUT) for sym in SYMBOLS]
    for m in meta:
        print(f"{m['symbol']}: {m['file']} ({m['winner']})")


if __name__ == "__main__":
    main()
