"""S&P 500 auto stock-picker (biweekly rank + soft rotate)."""

from app.paths import PickerPaths
from app.picker.active import (
    ActiveSelection,
    ActiveSymbol,
    clear_awaiting_first_buy,
    clear_exit_only_if_flat,
    load_active,
    prune_exit_only_if_flat,
    reconcile_awaiting_first_buy,
    save_active,
)
from app.picker.apply import ApplyResult, apply_pending_selection, maybe_apply_pending
from app.picker.apply_live import apply_to_live_config
from app.picker.apply_paper import apply_to_paper_v1, apply_to_paper_v2
from app.picker.bars import (
    FixtureBarProvider,
    HourlyBarProvider,
    SkipSymbol,
    SymbolWindowCloses,
    UniverseBarsResult,
    fetch_symbol_with_retries,
    fetch_universe_bars,
)
from app.picker.ibkr_bars import IbkrHourlyBarProvider
from app.picker.run import RankingRunResult, run_ranking
from app.picker.failures import FetchFailureEvaluation, evaluate_fetch_failures
from app.picker.pending import (
    PendingSelection,
    PendingSymbol,
    load_pending,
    mark_aborted,
    mark_applied,
    save_pending,
)
from app.picker.rank import SelectedSymbol, select_symbols
from app.picker.rank_symbol import SymbolRankResult, rank_one_symbol
from app.picker.score import SymbolScore, score_symbol_series
from app.picker.sizing import (
    allocate_priority_sleeves,
    resolve_equal_buy_cash_cap,
    sleeve_buy_budget,
)
from app.picker.soft_rotate import SoftRotateFlags, SoftRotatePlan, plan_soft_rotate
from app.picker.sp500 import (
    Sp500Constituent,
    Sp500LoadError,
    load_sp500,
    load_sp500_constituents,
    load_sp500_profiles,
    parse_sp500_constituents,
    parse_sp500_html,
    profiles_by_symbol,
)
from app.picker.tickers import normalize_list, normalize_wikipedia_ticker
from app.picker.trend_gate import allow_first_buy, sma
from app.picker.windows import (
    DateWindow,
    RankingWindows,
    filter_hourly_closes,
    ranking_windows,
)

__all__ = [
    "ActiveSelection",
    "ActiveSymbol",
    "ApplyResult",
    "DateWindow",
    "FetchFailureEvaluation",
    "FixtureBarProvider",
    "HourlyBarProvider",
    "IbkrHourlyBarProvider",
    "PendingSelection",
    "PendingSymbol",
    "PickerPaths",
    "RankingRunResult",
    "RankingWindows",
    "SelectedSymbol",
    "SkipSymbol",
    "SoftRotateFlags",
    "SoftRotatePlan",
    "Sp500Constituent",
    "Sp500LoadError",
    "SymbolRankResult",
    "SymbolScore",
    "SymbolWindowCloses",
    "UniverseBarsResult",
    "allow_first_buy",
    "apply_pending_selection",
    "apply_to_live_config",
    "apply_to_paper_v1",
    "apply_to_paper_v2",
    "clear_awaiting_first_buy",
    "clear_exit_only_if_flat",
    "prune_exit_only_if_flat",
    "reconcile_awaiting_first_buy",
    "evaluate_fetch_failures",
    "fetch_symbol_with_retries",
    "fetch_universe_bars",
    "filter_hourly_closes",
    "load_active",
    "load_pending",
    "load_sp500",
    "load_sp500_constituents",
    "load_sp500_profiles",
    "mark_aborted",
    "mark_applied",
    "maybe_apply_pending",
    "normalize_list",
    "normalize_wikipedia_ticker",
    "parse_sp500_constituents",
    "parse_sp500_html",
    "plan_soft_rotate",
    "profiles_by_symbol",
    "rank_one_symbol",
    "ranking_windows",
    "run_ranking",
    "save_active",
    "save_pending",
    "score_symbol_series",
    "select_symbols",
    "allocate_priority_sleeves",
    "resolve_equal_buy_cash_cap",
    "sleeve_buy_budget",
    "sma",
]
