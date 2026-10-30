"""Email bodies for picker ranking success / failure."""

from __future__ import annotations

from typing import Mapping, Sequence

from app.notifier import send_signal_email
from app.picker.rank import SelectedSymbol
from app.picker.sp500 import Sp500Constituent


def _pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "n/a"
    pct = value * 100.0
    if signed:
        return f"{pct:+.1f}%"
    return f"{pct:.1f}%"


def _trigger_pct(value: float) -> str:
    return f"{value * 100.0:.1f}%"


def _profile_lines(
    symbol: str, profiles: Mapping[str, Sp500Constituent] | None
) -> list[str]:
    if not profiles:
        return []
    info = profiles.get(symbol)
    if info is None:
        return []
    bits: list[str] = []
    if info.name:
        bits.append(info.name)
    if info.sector:
        bits.append(info.sector)
    if not bits:
        return []
    return [f"         {' · '.join(bits)}"]


def build_success_email_body(
    *,
    run_id: str,
    as_of: str,
    opt_window: str,
    score_window: str,
    selected: Sequence[SelectedSymbol],
    active_symbols: Sequence[str],
    skipped: Sequence[tuple[str, str]],
    failure_pct: float,
    apply_after: str,
    dry_run: bool = False,
    profiles: Mapping[str, Sp500Constituent] | None = None,
) -> str:
    selected_syms = [s.symbol for s in selected]
    added = sorted(set(selected_syms) - set(active_symbols))
    dropped = sorted(set(active_symbols) - set(selected_syms))
    kept = sorted(set(selected_syms) & set(active_symbols))

    if dry_run:
        headline = "PICKER dry run — nothing was queued"
        next_lines = [
            "  This was a dry run. Pending selection was NOT written.",
            "  Re-run without --dry-run to queue these sleeves for Monday.",
        ]
    elif not selected:
        headline = "PICKER ranking — all cash (no sleeves selected)"
        next_lines = [
            f"  Pending is queued to apply after {apply_after}.",
            "  That is the first live-worker cycle after Monday open.",
            "  No action needed unless you want to cancel before then.",
        ]
    else:
        headline = f"PICKER ranking — {len(selected)} sleeve(s) ready for Monday"
        next_lines = [
            f"  These replace live sleeves after {apply_after}",
            "  (first live-worker cycle after Monday open).",
            "  No action needed unless you want to cancel before then.",
        ]

    lines = [
        headline,
        "",
        "What happens next",
        *next_lines,
        "",
        "New sleeve list  (ranked by strategy profit; edge must be ≥ 0)",
    ]
    if not selected:
        lines.append("  (none — book goes to cash)")
    else:
        for i, row in enumerate(selected, start=1):
            bh = _pct(row.bh_return) if row.bh_return is not None else "n/a"
            lines.append(
                f"  {i}. {row.symbol:<5}  strategy {_pct(row.strategy_return)}"
                f"   beat B&H by {_pct(row.edge)}   (B&H {bh})"
            )
            lines.extend(_profile_lines(row.symbol, profiles))
            lines.append(
                f"         buy after +{_trigger_pct(row.buy_rise)} off trough"
                f"  ·  sell after −{_trigger_pct(row.sell_drop)} off peak"
            )

    lines.extend(
        [
            "",
            "Changes vs current sleeves",
            f"  Adding:   {', '.join(added) if added else '(none)'}",
            f"  Dropping: {', '.join(dropped) if dropped else '(none)'}",
            f"  Keeping:  {', '.join(kept) if kept else '(none)'}",
            "",
            "Run details",
            f"  Run id:        {run_id}",
            f"  As of:         {as_of}",
            f"  Optimize:      {opt_window}",
            f"  Score window:  {score_window}",
            f"  Data skips:    {failure_pct:.1%} ({len(skipped)} symbols) — OK under 30%",
            f"  First run:     {'yes' if not active_symbols else 'no'}",
        ]
    )
    if skipped:
        sample = ", ".join(f"{s} ({r})" for s, r in list(skipped)[:8])
        lines.append(f"  Skip sample:   {sample}")
    return "\n".join(lines) + "\n"


def build_failure_email_body(
    *,
    run_id: str,
    as_of: str,
    skipped: Sequence[tuple[str, str]],
    failure_pct: float,
    total_symbols: int,
) -> str:
    sample = ", ".join(f"{s} ({r})" for s, r in list(skipped)[:12])
    lines = [
        "PICKER ranking FAILED — previous list kept",
        "",
        "What this means",
        f"  IBKR data fetch failed for {failure_pct:.1%} of the universe "
        f"({len(skipped)}/{total_symbols}).",
        "  Threshold is 30%, so this run aborted.",
        "  pending_selection was NOT overwritten — current sleeves stay as-is.",
        "",
        "Run details",
        f"  Run id:  {run_id}",
        f"  As of:   {as_of}",
    ]
    if sample:
        lines.append(f"  Skips:   {sample}")
    lines.append("")
    lines.append("Next step: rerun ranking when IBKR data is healthy.")
    return "\n".join(lines) + "\n"


def build_success_email_subject(
    selected: Sequence[SelectedSymbol],
    *,
    dry_run: bool = False,
) -> str:
    prefix = "[PICKER][DRY RUN]" if dry_run else "[PICKER]"
    if not selected:
        return f"{prefix} all cash — no sleeves"
    names = ", ".join(s.symbol for s in selected[:5])
    return f"{prefix} Mon apply: {names}"


def build_skip_email_body(*, recent_run: str, within_days: int, next_hint: str) -> str:
    return (
        "\n".join(
            [
                "PICKER ranking SKIPPED — biweekly window",
                "",
                "What this means",
                "  The Saturday timer fired, but a successful ranking is still",
                f"  inside the every-other-Saturday skip window (≤{within_days} days).",
                "  pending_selection was NOT overwritten — current sleeves stay as-is.",
                "",
                "Details",
                f"  Recent run file: {recent_run}",
                f"  Next expected rank: {next_hint}",
                "",
                "Force a run: PICKER_FORCE=1 or python -m app.picker_rank --force",
            ]
        )
        + "\n"
    )


def send_picker_email(subject: str, body: str) -> bool:
    return send_signal_email(subject, body)
