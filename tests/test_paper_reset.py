import json
from datetime import datetime, timezone
from pathlib import Path

from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live.paper_reset import (
    apply_state_reset,
    build_flat_assets,
    longs_to_sell,
    plan_reset,
    redistribute_sleeve_cash,
    wait_until_rth,
)
from app.paths import LivePaths


def test_longs_to_sell_filters_book_symbols() -> None:
    assert longs_to_sell({"P": 11.0, "FICO": 1.0, "MSFT": 5.0, "VLO": 0.0}, ["P", "FICO", "VLO"]) == {
        "P": 11.0,
        "FICO": 1.0,
    }


def test_redistribute_equal_when_prices_missing() -> None:
    cash = redistribute_sleeve_cash(["A", "B"], {}, 1000.0)
    assert cash == {"A": 500.0, "B": 500.0}


def test_redistribute_equal_across_five() -> None:
    syms = ["P", "FICO", "HUM", "AMGN", "VLO"]
    prices = {"P": 130.0, "FICO": 800.0, "HUM": 425.0, "AMGN": 440.0, "VLO": 430.0}
    cash = redistribute_sleeve_cash(syms, prices, 1_000_000.0)
    assert set(cash) == set(syms)
    assert abs(sum(cash.values()) - 1_000_000.0) < 0.02
    assert all(abs(v - 200_000.0) < 0.01 for v in cash.values())


def test_build_flat_assets_clears_peaks() -> None:
    assets = build_flat_assets(
        ["P", "VLO"],
        {"P": 100.0, "VLO": 200.0},
        existing={"P": {"shares": 11.0, "peak": 130.0, "trough": 120.0, "last_price": 131.0}},
    )
    assert assets["P"]["shares"] == 0.0
    assert assets["P"]["peak"] is None
    assert assets["P"]["trough"] is None
    assert assets["P"]["cash"] == 100.0
    assert assets["P"]["last_price"] == 131.0


def test_apply_state_reset_writes_files(tmp_path: Path) -> None:
    root = tmp_path
    paths = LivePaths(project_root=root)
    paths.state_dir.mkdir(parents=True)
    cfg = LiveConfig(
        symbols=["P", "VLO"],
        total_cash=3000.0,
        use_account_cash=True,
        assets=[SymbolParams(symbol="P"), SymbolParams(symbol="VLO")],
    )
    save_live_config(paths.config_path, cfg)
    paths.state_path.write_text(
        json.dumps(
            {
                "cash_usd": 3000.0,
                "assets": {
                    "P": {"cash": 0.0, "shares": 11.0, "peak": 130.0, "trough": None},
                    "VLO": {"cash": 999000.0, "shares": 0.0, "peak": None, "trough": 400.0},
                },
            }
        ),
        encoding="utf-8",
    )
    paths.queue_path.write_text(
        json.dumps({"intents": [{"symbol": "VLO", "side": "BUY", "bar_ts": "x", "created_at": "y", "reason": "z"}]}),
        encoding="utf-8",
    )

    apply_state_reset(
        paths,
        symbols=["P", "VLO"],
        total_cash=1_000_500.0,
        sleeve_cash={"P": 500_250.0, "VLO": 500_250.0},
        use_account_cash=True,
    )

    raw = json.loads(paths.state_path.read_text(encoding="utf-8"))
    assert raw["cash_usd"] == 1_000_500.0
    assert raw["assets"]["P"]["shares"] == 0.0
    assert raw["assets"]["P"]["peak"] is None
    assert raw["assets"]["P"]["cash"] == 500_250.0
    assert raw["assets"]["VLO"]["cash"] == 500_250.0
    queue = json.loads(paths.queue_path.read_text(encoding="utf-8"))
    assert queue["intents"] == []
    cfg2 = json.loads(paths.config_path.read_text(encoding="utf-8"))
    assert cfg2["total_cash"] == 1_000_500.0
    assert cfg2["use_account_cash"] is True


def test_plan_reset_lists_sells() -> None:
    plan = plan_reset(
        symbols=["P", "FICO", "VLO"],
        positions={"P": 11.0, "FICO": 1.0, "EXTRA": 3.0},
        prices={"P": 130.0, "FICO": 800.0, "VLO": 430.0},
        equity=1_000_500.0,
        available_funds=995_000.0,
    )
    # flatten_all=True sells every broker long, not only book symbols.
    assert plan.positions_to_sell == {"P": 11.0, "FICO": 1.0, "EXTRA": 3.0}
    assert abs(sum(plan.sleeve_cash.values()) - 1_000_500.0) < 0.02
    assert all(abs(v - 333_500.0) < 0.01 for v in plan.sleeve_cash.values())


def test_plan_reset_book_only_when_flatten_all_false() -> None:
    plan = plan_reset(
        symbols=["P", "FICO", "VLO"],
        positions={"P": 11.0, "FICO": 1.0, "EXTRA": 3.0},
        prices={"P": 130.0, "FICO": 800.0, "VLO": 430.0},
        equity=1_000_500.0,
        available_funds=995_000.0,
        flatten_all=False,
    )
    assert plan.positions_to_sell == {"P": 11.0, "FICO": 1.0}


def test_wait_until_rth_returns_when_open() -> None:
    # Wednesday 2026-10-22 14:00 UTC = 10:00 ET — inside RTH.
    open_ts = datetime(2026, 10, 22, 14, 0, tzinfo=timezone.utc)
    sleeps: list[float] = []

    def now_fn() -> datetime:
        return open_ts

    def sleep_fn(sec: float) -> None:
        sleeps.append(sec)

    got = wait_until_rth(now_fn=now_fn, sleep_fn=sleep_fn)
    assert got == open_ts
    assert sleeps == []
