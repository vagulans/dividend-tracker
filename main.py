import os
import requests
import pandas as pd
import argparse
from dotenv import load_dotenv
from io import StringIO
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

# Load the .env file to get your token
load_dotenv()
TOKEN = os.getenv("IBKR_TOKEN")

# IBKR Flex Web Service endpoint
FLEX_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t="
QUERY_ID_CASH_TRANSACTIONS = os.getenv("FLEX_QUERY_ID_CASH_TRANSACTIONS")


def request_flex_report(token, query_id):
    url = f"{FLEX_URL}{token}&q={query_id}&v=3"
    response = requests.get(url)
    response.raise_for_status()
    print("Response content:", response.text)
    reference_code = response.text.split("<ReferenceCode>")[1].split(
        "</ReferenceCode>"
    )[0]
    return reference_code


def retrieve_flex_report(token, reference_code):
    url = f"https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement?q={reference_code}&t={token}&v=3"
    response = requests.get(url)
    response.raise_for_status()

    # Save raw CSV response
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_file = f"raw/flex_report_{timestamp}.csv"
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(response.text)
    print(f"\nRaw CSV data saved to: {raw_file}")

    return response.text


def parse_report(report_content):
    data = StringIO(report_content)
    df = pd.read_csv(data)
    print("\nDataFrame info:")
    print(df.info())
    if "Type" in df.columns:
        print("\nUnique Types:")
        print(df["Type"].unique())
    else:
        print("\nNo Type column found.")
    return df


def filter_dividends(df):
    if "Type" not in df.columns:
        print("Warning: Type column not found in the data")
        return df
    # Filter for dividends only
    filtered_df = df[df["Type"] == "Dividends"].copy()
    return filtered_df


# Main Execution
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="IBKR Dividend Tracker - Fetch and visualize dividend data from Interactive Brokers"
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force fetch fresh data from IBKR, ignoring any cached files from today",
    )
    args = parser.parse_args()

    # Check if a cash transactions CSV exists from today (unless --no-cache is specified)
    today = datetime.now().strftime("%Y%m%d")
    raw_dir = "raw"
    cash_files = [
        f
        for f in os.listdir(raw_dir)
        if f.startswith("cash_flex_report_") and f.endswith(".csv")
    ]
    latest_cash_file = None
    use_cache = not args.no_cache

    if cash_files and use_cache:
        latest_cash_file = max(
            cash_files, key=lambda x: os.path.getctime(os.path.join(raw_dir, x))
        )
        if today in latest_cash_file:
            print(f"Loading latest cash transactions from: {latest_cash_file}")
            cash_transactions_df = pd.read_csv(os.path.join(raw_dir, latest_cash_file))
        else:
            print("No cash transactions file found for today. Requesting new data...")
            reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
            print(
                f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report..."
            )
            report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash)
            cash_transactions_df = parse_report(report_content_cash)
    else:
        if args.no_cache:
            print("Cache override requested. Fetching fresh data from IBKR...")
        else:
            print("No cash transactions file found. Requesting new data...")
        reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
        print(
            f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report..."
        )
        report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash)
        cash_transactions_df = parse_report(report_content_cash)

    filtered_dividends = filter_dividends(cash_transactions_df)

    # Summary of dividends by Symbol (underlying)
    if not filtered_dividends.empty:
        summary_dividends = (
            filtered_dividends.groupby("Symbol")
            .agg({"Amount": "sum", "Date/Time": "count"})
            .rename(columns={"Amount": "Total Dividends", "Date/Time": "Count"})
        )
        print(summary_dividends[["Count", "Total Dividends"]])

    # Save filtered dividends
    if not filtered_dividends.empty:
        filtered_dividends.to_csv("filtered_dividends.csv", index=False)
        print("\nFiltered dividends saved to filtered_dividends.csv")

    # Print a clean DataFrame of the transactions
    if not filtered_dividends.empty:
        clean_df = filtered_dividends[
            ["Symbol", "SettleDate", "ReportDate", "ExDate", "Amount"]
        ]
        print("\nClean DataFrame of Transactions:")
        print(clean_df)

    # Create a monthly bar chart of dividends received each month
    if not filtered_dividends.empty:
        filtered_dividends["Date/Time"] = pd.to_datetime(
            filtered_dividends["Date/Time"]
        )
        monthly_dividends = (
            filtered_dividends.groupby(
                filtered_dividends["Date/Time"].dt.to_period("M")
            )
            .agg({"Amount": "sum"})
            .reset_index()
        )
        # Format monthly labels as MMM-YY
        monthly_dividends["Date/Time"] = (
            monthly_dividends["Date/Time"].dt.to_timestamp().dt.strftime("%b-%y")
        )
        # Add formatted dollar amounts for text labels
        monthly_dividends["Amount_Text"] = monthly_dividends["Amount"].apply(
            lambda x: f"${x:,.0f}"
        )
        fig_monthly = px.bar(
            monthly_dividends,
            x="Date/Time",
            y="Amount",
            text="Amount_Text",
            title="Monthly Dividends Received",
        )
        # Format text labels: bold
        fig_monthly.update_traces(
            texttemplate="<b>%{text}</b>",
            textposition="outside",
            textfont=dict(size=12),
        )
        fig_monthly.show()

    # Create a bar chart of dividends received over the last 16 weeks
    if not filtered_dividends.empty:
        sixteen_weeks_ago = datetime.now() - timedelta(weeks=16)
        recent_dividends = filtered_dividends[
            filtered_dividends["Date/Time"] >= sixteen_weeks_ago
        ]
        weekly_dividends = (
            recent_dividends.groupby(recent_dividends["Date/Time"].dt.to_period("W"))
            .agg({"Amount": "sum"})
            .reset_index()
        )
        # Format weekly labels as MMM-DD to MMM-YY
        weekly_start = weekly_dividends["Date/Time"].dt.start_time
        weekly_end = weekly_dividends["Date/Time"].dt.end_time
        weekly_dividends["Date/Time"] = (
            weekly_start.dt.strftime("%b-%d") + " to " + weekly_end.dt.strftime("%b-%y")
        )
        # Add formatted dollar amounts for text labels
        weekly_dividends["Amount_Text"] = weekly_dividends["Amount"].apply(
            lambda x: f"${x:,.0f}"
        )
        fig_weekly = px.bar(
            weekly_dividends,
            x="Date/Time",
            y="Amount",
            text="Amount_Text",
            title="Dividends Received Over the Last 16 Weeks",
        )
        # Format text labels: bold
        fig_weekly.update_traces(
            texttemplate="<b>%{text}</b>",
            textposition="outside",
            textfont=dict(size=12),
        )
        fig_weekly.show()
