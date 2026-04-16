import argparse
import os
import time
import webbrowser
from datetime import datetime
from io import StringIO
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from dashboard import build_dashboard

load_dotenv()
TOKEN = os.getenv("IBKR_TOKEN")

FLEX_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t="
QUERY_ID_CASH_TRANSACTIONS = os.getenv("FLEX_QUERY_ID_CASH_TRANSACTIONS")


def request_flex_report(token, query_id):
    url = f"{FLEX_URL}{token}&q={query_id}&v=3"
    response = requests.get(url)
    response.raise_for_status()
    reference_code = response.text.split("<ReferenceCode>")[1].split("</ReferenceCode>")[0]
    return reference_code


def retrieve_flex_report(token, reference_code, quiet: bool = False, max_attempts: int = 10, wait_seconds: int = 2):
    url = f"https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement?q={reference_code}&t={token}&v=3"
    last_text = ""
    for attempt in range(1, max_attempts + 1):
        response = requests.get(url)
        response.raise_for_status()
        text = response.text
        last_text = text
        is_xml = text.lstrip().startswith("<")
        if is_xml:
            if ("<Status>Warn</Status>" in text) or ("ErrorCode>1019<" in text) or ("generation in progress" in text.lower()):
                if not quiet:
                    print(f"Statement not ready (attempt {attempt}/{max_attempts}). Retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            raise RuntimeError(f"Flex service returned an error: {text}")
        os.makedirs("raw", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        raw_file = f"raw/cash_flex_report_{timestamp}.csv"
        with open(raw_file, "w", encoding="utf-8") as f:
            f.write(text)
        if not quiet:
            print(f"\nRaw CSV data saved to: {raw_file}")
        return text
    raise TimeoutError(f"Timed out waiting for Flex statement to be ready. Last response: {last_text}")


def parse_report(report_content, quiet: bool = False):
    data = StringIO(report_content)
    df = pd.read_csv(data)
    if not quiet:
        print("\nDataFrame info:")
        print(df.info())
        if "Type" in df.columns:
            print("\nUnique Types:")
            print(df["Type"].unique())
        else:
            print("\nNo Type column found.")
    return df


def filter_cash_inflows(df):
    """Filter for all cash inflow types: Dividends, Payment In Lieu Of Dividends, Broker Interest Received."""
    if "Type" not in df.columns:
        print("Warning: Type column not found in the data; skipping cash inflow filtering")
        return df.iloc[0:0].copy()

    cash_inflow_types = [
        "Dividends",
        "Payment In Lieu Of Dividends",
        "Broker Interest Received",
    ]
    return df[df["Type"].isin(cash_inflow_types)].copy()


def ensure_date_columns(df: pd.DataFrame, log) -> pd.DataFrame:
    """Add DateOnly / MonthPeriod / WeekPeriod columns; drop rows with unparsable dates."""
    if df.empty or "DateOnly" in df.columns:
        return df
    candidate_date_cols = ["Date/Time", "Date", "SettleDate", "ReportDate", "TradeDate"]
    source_date_col = next((c for c in candidate_date_cols if c in df.columns), None)
    if source_date_col is None:
        log("Warning: No recognized date column found; charts will be skipped.")
        return df
    series = df[source_date_col]
    if series.dtype == object and source_date_col == "Date/Time":
        series = series.astype(str).str.split(";").str[0]
    df = df.copy()
    df["DateOnly"] = pd.to_datetime(series, errors="coerce")
    df = df[df["DateOnly"].notna()].copy()
    if not df.empty:
        df["MonthPeriod"] = df["DateOnly"].dt.to_period("M")
        df["WeekPeriod"] = df["DateOnly"].dt.to_period("W")
    return df


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="IBKR Cash Flow Tracker - Fetch and visualize cash inflow data from Interactive Brokers",
    )
    parser.add_argument("--no-cache", action="store_true", help="Force fetch fresh data from IBKR, ignoring any cached files from today")
    parser.add_argument("--quiet", action="store_true", help="Reduce console output for faster, cleaner runs")
    parser.add_argument("--no-show", action="store_true", help="Do not open the dashboard in the browser; only save HTML file")
    parser.add_argument("--dashboard-file", type=str, default="dashboard.html", help="Output HTML file for the consolidated dashboard")
    parser.add_argument("--refresh", action="store_true", help="Refresh today's parsed cache even if it exists (fetch latest data)")
    parser.add_argument("--top-symbols", type=int, default=12, help="Default value for the Top N symbols input in the dashboard UI (default: 12)")
    args = parser.parse_args()

    def log(message: str):
        if not args.quiet:
            print(message)

    today = datetime.now().strftime("%Y%m%d")
    raw_dir = "raw"
    os.makedirs(raw_dir, exist_ok=True)
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    parquet_cache_path = os.path.join(cache_dir, f"filtered_cash_inflows_{today}.parquet")

    use_cache = not args.no_cache
    filtered_cash_inflows = pd.DataFrame()
    cash_transactions_df = pd.DataFrame()
    need_refresh = False

    if use_cache and os.path.exists(parquet_cache_path) and not args.refresh:
        try:
            log(f"Loading parsed cache from: {parquet_cache_path}")
            filtered_cash_inflows = pd.read_parquet(parquet_cache_path)
        except Exception as e:
            log(f"Warning: Could not read parsed cache, will rebuild: {e}")
            filtered_cash_inflows = pd.DataFrame()

        if not filtered_cash_inflows.empty:
            latest_dt = None
            for col in ["DateOnly", "Date/Time", "Date", "SettleDate", "ReportDate", "TradeDate"]:
                if col in filtered_cash_inflows.columns:
                    try:
                        series = filtered_cash_inflows[col]
                        if series.dtype == object and col == "Date/Time":
                            series = series.astype(str).str.split(";").str[0]
                        parsed = pd.to_datetime(series, errors="coerce")
                        candidate = parsed.max()
                        if pd.notna(candidate):
                            latest_dt = candidate if latest_dt is None else max(latest_dt, candidate)
                    except Exception:
                        pass
            if latest_dt is None:
                need_refresh = True
                log("Could not determine latest date from cache; refreshing data...")
            elif latest_dt.normalize() < pd.Timestamp.today().normalize():
                need_refresh = True
                log("Parsed cache appears stale compared to today; refreshing data...")
    elif args.refresh:
        log("Refresh flag set; rebuilding today's parsed cache.")

    if filtered_cash_inflows.empty or need_refresh or args.refresh:
        cash_files = [
            f
            for f in os.listdir(raw_dir)
            if f.endswith(".csv") and (f.startswith("cash_flex_report_") or f.startswith("flex_report_"))
        ]
        latest_cash_file = None
        if cash_files and use_cache and not args.refresh:
            latest_cash_file = max(cash_files, key=lambda x: os.path.getctime(os.path.join(raw_dir, x)))
            if today not in latest_cash_file:
                latest_cash_file = None

        if latest_cash_file:
            log(f"Loading latest cash transactions from: {latest_cash_file}")
            cash_transactions_df = pd.read_csv(os.path.join(raw_dir, latest_cash_file))
            with open(os.path.join(raw_dir, latest_cash_file), "r", encoding="utf-8") as f:
                head = f.read(128)
            if head.lstrip().startswith("<"):
                log("Latest file is not CSV (looks like XML warn). Fetching new data...")
                reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
                log(f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report...")
                report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash, quiet=args.quiet)
                cash_transactions_df = parse_report(report_content_cash, quiet=args.quiet)
        else:
            if args.no_cache:
                log("Cache override requested. Fetching fresh data from IBKR...")
            elif args.refresh:
                log("Refreshing data from IBKR...")
            else:
                log("No cash transactions file found for today. Requesting new data...")
            reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
            log(f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report...")
            report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash, quiet=args.quiet)
            cash_transactions_df = parse_report(report_content_cash, quiet=args.quiet)

        filtered_cash_inflows = filter_cash_inflows(cash_transactions_df)

    filtered_cash_inflows = ensure_date_columns(filtered_cash_inflows, log)

    if not filtered_cash_inflows.empty:
        try:
            filtered_cash_inflows.to_parquet(parquet_cache_path, index=False)
            log(f"Saved parsed cache to: {parquet_cache_path}")
        except Exception as e:
            log(f"Warning: Could not save parsed cache: {e}")

    if not filtered_cash_inflows.empty:
        type_summary = (
            filtered_cash_inflows.groupby("Type")
            .agg(Total_Amount=("Amount", "sum"), Count=("Amount", "size"))
            .sort_values("Total_Amount", ascending=False)
        )
        log("\nSummary by Type:")
        log(str(type_summary[["Count", "Total_Amount"]]))

        filtered_cash_inflows.to_csv("filtered_cash_inflows.csv", index=False)
        log("\nFiltered cash inflows saved to filtered_cash_inflows.csv")

        out_path = build_dashboard(
            filtered_cash_inflows,
            out_path=args.dashboard_file,
            top_n_default=args.top_symbols,
        )
        log(f"Dashboard saved to {out_path}")

        if not args.no_show:
            try:
                webbrowser.open(Path(out_path).resolve().as_uri())
                log("Dashboard opened in browser.")
            except Exception as e:
                log(f"Could not open dashboard in browser: {e}")
    else:
        log("No cash inflow data available. Dashboard not generated.")
