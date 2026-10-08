from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.live.modes import TradingMode, parse_mode


@dataclass
class SymbolParams:
    symbol: str
    buy_rise_pct: float = 2.0
    sell_drop_pct: float = 4.0
    enabled: bool = True


@dataclass
class LiveConfig:
    mode: TradingMode = TradingMode.live_dry_run
    symbols: list[str] = field(default_factory=lambda: ["MSFT", "AAPL", "SMH"])
    total_cash: float = 1000.0
    assets: list[SymbolParams] = field(default_factory=list)
    trading_enabled: bool = True
    allow_fractional_default: bool = True
    fee_schedule_name: str = "default_ibkr_us_stock"
    alerts: dict = field(default_factory=lambda: {
        "fill": True,
        "reject": True,
        "disconnect": True,
        "risk_alert": True,
        "trading_stopped": True,
        "weekly_2fa": True,
    })

    def __post_init__(self) -> None:
        if not self.assets:
            self.assets = [SymbolParams(symbol=symbol) for symbol in self.symbols]


def _default_payload() -> dict:
    cfg = LiveConfig()
    return {
        "mode": cfg.mode.value,
        "symbols": cfg.symbols,
        "total_cash": cfg.total_cash,
        "assets": [asdict(asset) for asset in cfg.assets],
        "trading_enabled": cfg.trading_enabled,
        "allow_fractional_default": cfg.allow_fractional_default,
        "fee_schedule_name": cfg.fee_schedule_name,
        "alerts": dict(cfg.alerts),
    }


def save_live_config(path: Path, config: LiveConfig | None = None) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = config or LiveConfig()
    payload = {
        "mode": cfg.mode.value if isinstance(cfg.mode, TradingMode) else str(cfg.mode),
        "symbols": list(cfg.symbols),
        "total_cash": cfg.total_cash,
        "assets": [asdict(asset) for asset in cfg.assets],
        "trading_enabled": cfg.trading_enabled,
        "allow_fractional_default": cfg.allow_fractional_default,
        "fee_schedule_name": cfg.fee_schedule_name,
        "alerts": dict(cfg.alerts),
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_live_config(path: Path) -> LiveConfig:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    assets = [SymbolParams(**row) for row in raw.get("assets", [])]
    symbols = list(raw.get("symbols") or [asset.symbol for asset in assets] or ["MSFT", "AAPL", "SMH"])
    return LiveConfig(
        mode=parse_mode(raw.get("mode", TradingMode.live_dry_run.value)),
        symbols=symbols,
        total_cash=float(raw.get("total_cash", 1000.0)),
        assets=assets,
        trading_enabled=bool(raw.get("trading_enabled", True)),
        allow_fractional_default=bool(raw.get("allow_fractional_default", True)),
        fee_schedule_name=str(raw.get("fee_schedule_name", "default_ibkr_us_stock")),
        alerts=dict(raw.get("alerts") or LiveConfig().alerts),
    )


def bootstrap_live_state(state_dir: Path) -> None:
    """Create default live files if missing. Does not touch state/ or state_v2/."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    config_path = state_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(json.dumps(_default_payload(), indent=2), encoding="utf-8")
    state_path = state_dir / "state.json"
    if not state_path.exists():
        state_path.write_text(json.dumps({"assets": {}, "cash_usd": 1000.0}, indent=2), encoding="utf-8")
    audit_dir = state_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
