from datetime import datetime, timezone
from pathlib import Path

from app.remote.health import build_health_strip


def test_build_health_strip_fresh_worker(tmp_path: Path) -> None:
    log = tmp_path / "gateway-health.log"
    log.write_text(
        "2026-10-17 08:00:17 PM EDT status=OK port4002=1 api_ok=1 java=1\n",
        encoding="utf-8",
    )
    now = datetime(2026, 10, 17, 20, 5, tzinfo=timezone.utc)
    strip = build_health_strip(
        live_status={
            "mode": "broker_paper",
            "trading_enabled": True,
            "incident": None,
            "last_cycle": {
                "at_utc": "2026-10-17T20:00:00+00:00",
                "rth_ok": False,
                "price_source": "ibkr_rth_hourly",
            },
        },
        gateway_health_log=log,
        now=now,
    )
    assert strip["worker_fresh"] is True
    assert strip["stale_minutes"] == 5.0
    assert strip["trading_on"] is True
    assert strip["risk_open"] is False
    assert strip["gateway_ok"] is True
    assert strip["api_ok"] is True
    assert strip["price_source"] == "ibkr_rth_hourly"


def test_build_health_strip_missing_optional_files() -> None:
    strip = build_health_strip(
        live_status={"mode": "live_dry_run", "trading_enabled": False, "incident": {"reason": "x"}},
        gateway_health_log=None,
    )
    assert strip["worker_fresh"] is False
    assert strip["gateway_ok"] is None
    assert strip["risk_open"] is True
    assert strip["trading_on"] is False
