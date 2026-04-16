"""Build the consolidated IBKR Cash Inflows dashboard as a single static HTML file.

The Python side simply emits a compact records payload (short keys ``d``, ``t``, ``s``, ``a``)
and injects it into ``templates/dashboard.html``. All grouping, windowing and cumulative
logic happens in the browser via Plotly.js so users can toggle Week/Month, switch views,
and adjust the window without rerunning Python.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd


TEMPLATE_PATH = Path(__file__).parent / "templates" / "dashboard.html"
DEFAULT_TITLE = "IBKR Cash Inflows"


def _records_from_df(df: pd.DataFrame) -> list[dict]:
    """Reduce the filtered DataFrame to the minimal payload consumed by the UI.

    Keys are intentionally short to keep the embedded JSON compact:
    ``d`` ISO date, ``t`` Type, ``s`` Symbol (with Type fallback), ``a`` Amount.
    """
    if df.empty:
        return []

    if "DateOnly" not in df.columns:
        raise ValueError("DataFrame is missing required 'DateOnly' column")
    if "Amount" not in df.columns or "Type" not in df.columns:
        raise ValueError("DataFrame is missing required 'Amount' or 'Type' column")

    work = df.copy()
    work["DateOnly"] = pd.to_datetime(work["DateOnly"], errors="coerce")
    work = work[work["DateOnly"].notna()]
    work = work[work["Amount"].notna()]
    if work.empty:
        return []

    symbol_source = work["Symbol"] if "Symbol" in work.columns else pd.Series([None] * len(work), index=work.index)
    symbol_type = symbol_source.where(symbol_source.notna() & (symbol_source.astype(str).str.strip() != ""), work["Type"])

    records = pd.DataFrame({
        "d": work["DateOnly"].dt.strftime("%Y-%m-%d"),
        "t": work["Type"].astype(str),
        "s": symbol_type.astype(str),
        "a": work["Amount"].astype(float).round(4),
    })
    records = records.sort_values("d").reset_index(drop=True)
    return records.to_dict(orient="records")


def _safe_json(payload: dict) -> str:
    """Serialize payload for safe embedding inside a ``<script type="application/json">`` tag."""
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return text.replace("</", "<\\/")


def build_dashboard(
    df: pd.DataFrame,
    out_path: str | Path = "dashboard.html",
    top_n_default: int = 12,
    title: str = DEFAULT_TITLE,
    template_path: str | Path | None = None,
) -> Path:
    """Render the consolidated dashboard HTML to ``out_path``.

    Parameters
    ----------
    df:
        Filtered cash-inflow DataFrame containing at minimum ``DateOnly``, ``Type``, and
        ``Amount`` columns. ``Symbol`` is used when present.
    out_path:
        Destination HTML file.
    top_n_default:
        Default value for the Top N symbols input in the UI.
    title:
        Page/window title.
    template_path:
        Override the template location (mostly for tests).
    """
    template_file = Path(template_path) if template_path else TEMPLATE_PATH
    template = template_file.read_text(encoding="utf-8")

    records = _records_from_df(df)
    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "records": records,
    }
    payload_json = _safe_json(payload)

    html = (
        template
        .replace("__DASHBOARD_TITLE__", title)
        .replace("__GENERATED_AT__", payload["generated_at"])
        .replace("__TOP_N_DEFAULT__", str(int(top_n_default)))
        .replace("__PAYLOAD_JSON__", payload_json)
    )

    out = Path(out_path)
    out.write_text(html, encoding="utf-8")
    return out
