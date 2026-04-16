"""Build a dashboard populated with synthetic data for README screenshots.

This intentionally uses fabricated numbers only - no real IBKR data touches the
public repo. Outputs ``screenshots/_dashboard_demo.html`` which is gitignored via
the generic ``dashboard.html`` pattern? No - so we write into the screenshots/
folder which is tracked, but the demo HTML is temp-only and must be deleted after
screenshotting.
"""

from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard import build_dashboard


def synth_records() -> pd.DataFrame:
    rng = random.Random(42)
    symbols = [
        ("AAPL", "Dividends", 6, 80),
        ("MSFT", "Dividends", 5, 60),
        ("KO", "Dividends", 4, 45),
        ("JNJ", "Dividends", 4, 55),
        ("PG", "Dividends", 4, 40),
        ("XOM", "Dividends", 4, 90),
        ("T", "Dividends", 4, 70),
        ("VZ", "Dividends", 4, 65),
        ("SCHD", "Dividends", 12, 120),
        ("JEPI", "Dividends", 12, 180),
        ("QYLD", "Dividends", 12, 45),
        ("HYG", "Payment In Lieu Of Dividends", 12, 30),
    ]
    start = datetime.today() - timedelta(days=365)
    rows: list[dict] = []
    for sym, tp, per_year, avg in symbols:
        for i in range(per_year):
            offset_days = int((365 / per_year) * i) + rng.randint(-3, 3)
            d = start + timedelta(days=offset_days)
            amt = round(avg * rng.uniform(0.85, 1.2), 2)
            rows.append({"Symbol": sym, "Type": tp, "Amount": amt, "DateOnly": d.date().isoformat()})
    weeks = 52
    for w in range(weeks):
        d = start + timedelta(days=7 * w + rng.randint(0, 6))
        rows.append({
            "Symbol": None,
            "Type": "Broker Interest Received",
            "Amount": round(rng.uniform(3, 22), 2),
            "DateOnly": d.date().isoformat(),
        })
    df = pd.DataFrame(rows)
    df["DateOnly"] = pd.to_datetime(df["DateOnly"])
    return df


if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parents[1] / "screenshots"
    out_dir.mkdir(exist_ok=True)
    df = synth_records()
    out_path = build_dashboard(
        df,
        out_path=out_dir / "_dashboard_demo.html",
        top_n_default=10,
        title="IBKR Cash Inflows (demo)",
    )
    print(f"demo dashboard written to {out_path}")
