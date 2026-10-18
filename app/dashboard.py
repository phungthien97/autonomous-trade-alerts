"""Remote portfolio dashboard (Tailscale / OVH).

Shows only Live | Paper V1 | Paper V2 | Picker per investigation §13.
Lab / Streamlit-Cloud config UI was removed from this entrypoint.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.remote.ui import (  # noqa: E402
    render_live_tab,
    render_paper_tab,
    render_picker_tab,
)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container { padding-top: 1.2rem; padding-bottom: 2rem; max-width: 920px; }
        h1 { font-size: 1.6rem !important; margin-bottom: 0.25rem !important; }
        div[data-testid="stMetricValue"] { font-size: 1.15rem; }
        /* Emphasize first money metric (NAV) on Live / Paper */
        div[data-testid="stHorizontalBlock"] > div:first-child div[data-testid="stMetricValue"] {
            font-size: 1.45rem;
        }
        /* Hide dataframe chrome (search/download/fullscreen) on phone */
        div[data-testid="stElementToolbar"] { display: none !important; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main() -> None:
    st.set_page_config(
        page_title="Trade bot",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    _inject_styles()
    st.title("Trade bot")
    st.caption("OVH · Tailscale only · no IBKR login needed")

    live_tab, v1_tab, v2_tab, picker_tab = st.tabs(["Live", "Paper V1", "Paper V2", "Picker"])

    with live_tab:
        render_live_tab(st, project_root=ROOT)
    with v1_tab:
        render_paper_tab(st, "v1", project_root=ROOT)
    with v2_tab:
        render_paper_tab(st, "v2", project_root=ROOT)
    with picker_tab:
        render_picker_tab(st, project_root=ROOT)


if __name__ == "__main__":
    main()
