"""Fail if the live packages cannot be imported."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.broker import IbkrBroker, InMemoryBroker
from app.fees import default_ibkr_us_stock_schedule
from app.live import TradingMode
from app.risk import RiskController

assert TradingMode.live_dry_run.value == "live_dry_run"
assert default_ibkr_us_stock_schedule().commission_min_usd > 0
assert InMemoryBroker and IbkrBroker and RiskController
print("live imports ok")
