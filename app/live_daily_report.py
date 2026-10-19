"""Daily after-RTH summary for the live book.

Cron example (America/New_York, after the cash close):
    30 16 * * 1-5 cd /opt/autonomous-trade-alerts && .venv/bin/python -m app.live_daily_report
"""

from __future__ import annotations

import csv
from pathlib import Path

from app.live.config import load_live_config
from app.live.metrics import returns_from_values
from app.notifier import send_live_event_email
from app.paths import LivePaths


def _last_equity(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    latest: dict[str, float] = {}
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            latest[row["symbol"]] = float(row["Portfolio_Value"])
    return latest


def build_summary(paths: LivePaths | None = None) -> str:
    chosen = paths or LivePaths()
    config = load_live_config(chosen.config_path) if chosen.config_path.exists() else None
    symbols = list(config.symbols) if config else []
    start = config.total_cash if config else 1000.0
    values = _last_equity(chosen.equity_path)
    bot_end = sum(values.get(symbol, start / max(len(symbols), 1)) for symbol in symbols)
    metrics = returns_from_values(start, bot_end, bot_end)
    lines = [
        "Live daily summary",
        "",
        "Book",
        f"  Sleeves:  {', '.join(symbols) if symbols else '(none)'}",
        f"  Start $:  {start:,.0f}",
        f"  End $:    {bot_end:,.2f}",
        "",
        "Performance",
        f"  Bot return:     {metrics['bot_return_pct']:+.2f}%",
        f"  Equal-weight B&H (proxy): {metrics['bh_return_pct']:+.2f}%",
        f"  Edge vs B&H:    {metrics['edge_pct']:+.2f}%",
    ]
    return "\n".join(lines)


def main() -> int:
    body = build_summary()
    send_live_event_email("Live daily summary", body)
    print(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
