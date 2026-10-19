from app.live.config import LiveConfig, SymbolParams, save_live_config
from app.live_daily_report import build_summary
from app.paths import LivePaths


def test_daily_summary_from_equity(tmp_path) -> None:
    paths = LivePaths(project_root=tmp_path)
    paths.state_dir.mkdir(parents=True)
    save_live_config(
        paths.config_path,
        LiveConfig(symbols=["MSFT", "AAPL", "SMH"], total_cash=900.0, assets=[
            SymbolParams("MSFT"), SymbolParams("AAPL"), SymbolParams("SMH")
        ]),
    )
    paths.equity_path.write_text(
        "Datetime,symbol,Price,Portfolio_Value\n"
        "2026-09-23T20:00:00Z,MSFT,1,310\n"
        "2026-09-23T20:00:00Z,AAPL,1,300\n"
        "2026-09-23T20:00:00Z,SMH,1,320\n",
        encoding="utf-8",
    )
    body = build_summary(paths)
    assert "MSFT" in body
    assert "Bot return" in body
