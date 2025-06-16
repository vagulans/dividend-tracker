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


def filter_cash_inflows(df):
    """Filter for all cash inflow types: Dividends, Payment In Lieu Of Dividends, and Broker Interest Received"""
    if "Type" not in df.columns:
        print("Warning: Type column not found in the data")
        return df
    
    # Define cash inflow types
    cash_inflow_types = [
        "Dividends",
        "Payment In Lieu Of Dividends", 
        "Broker Interest Received"
    ]
    
    # Filter for all cash inflow types
    filtered_df = df[df["Type"].isin(cash_inflow_types)].copy()
    return filtered_df


# Main Execution
if __name__ == "__main__":
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description="IBKR Cash Flow Tracker - Fetch and visualize cash inflow data from Interactive Brokers"
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

    # Filter for all cash inflows (not just dividends)
    filtered_cash_inflows = filter_cash_inflows(cash_transactions_df)

    # Summary of cash inflows by Type and Symbol
    if not filtered_cash_inflows.empty:
        print("\nSummary by Type:")
        type_summary = (
            filtered_cash_inflows.groupby("Type")
            .agg({"Amount": "sum", "Date/Time": "count"})
            .rename(columns={"Amount": "Total Amount", "Date/Time": "Count"})
        )
        print(type_summary[["Count", "Total Amount"]])
        
        print("\nSummary by Symbol (for dividends and PILODs):")
        symbol_data = filtered_cash_inflows[filtered_cash_inflows["Symbol"].notna()]
        if not symbol_data.empty:
            symbol_summary = (
                symbol_data.groupby(["Symbol", "Type"])
                .agg({"Amount": "sum", "Date/Time": "count"})
                .rename(columns={"Amount": "Total Amount", "Date/Time": "Count"})
            )
            print(symbol_summary[["Count", "Total Amount"]])

    # Save filtered cash inflows
    if not filtered_cash_inflows.empty:
        filtered_cash_inflows.to_csv("filtered_cash_inflows.csv", index=False)
        print("\nFiltered cash inflows saved to filtered_cash_inflows.csv")

    # Print a clean DataFrame of the transactions
    if not filtered_cash_inflows.empty:
        clean_df = filtered_cash_inflows[
            ["Type", "Symbol", "SettleDate", "ReportDate", "ExDate", "Amount"]
        ]
        print("\nClean DataFrame of Cash Inflow Transactions:")
        print(clean_df)

    # Create a monthly stacked bar chart of cash inflows by type
    if not filtered_cash_inflows.empty:
        # Handle mixed date formats in the Date/Time column
        # Some dates are "YYYY-MM-DD;HHMMSS" and others are just "YYYY-MM-DD"
        filtered_cash_inflows["Date/Time"] = filtered_cash_inflows["Date/Time"].str.split(";").str[0]
        filtered_cash_inflows["Date/Time"] = pd.to_datetime(
            filtered_cash_inflows["Date/Time"]
        )
        
        # Group by month and type
        monthly_cash_inflows = (
            filtered_cash_inflows.groupby([
                filtered_cash_inflows["Date/Time"].dt.to_period("M"),
                "Type"
            ])
            .agg({"Amount": "sum"})
            .reset_index()
        )
        
        # Sort by date chronologically before formatting to strings
        monthly_cash_inflows = monthly_cash_inflows.sort_values("Date/Time")
        
        # Format monthly labels as MMM-YY after sorting
        monthly_cash_inflows["Date/Time"] = (
            monthly_cash_inflows["Date/Time"].dt.to_timestamp().dt.strftime("%b-%y")
        )
        
        # Get unique months in chronological order to preserve sorting in plotly
        month_order = monthly_cash_inflows["Date/Time"].unique().tolist()
        
        # Create stacked bar chart
        fig_monthly = px.bar(
            monthly_cash_inflows,
            x="Date/Time",
            y="Amount",
            color="Type",
            title="Monthly Cash Inflows by Type",
            color_discrete_map={
                "Dividends": "#2E86AB",
                "Payment In Lieu Of Dividends": "#A23B72", 
                "Broker Interest Received": "#F18F01"
            },
            category_orders={"Date/Time": month_order}
        )
        
        # Calculate totals for each month to add labels
        monthly_totals = (
            monthly_cash_inflows.groupby("Date/Time")["Amount"]
            .sum()
            .reset_index()
        )
        monthly_totals["Amount_Text"] = monthly_totals["Amount"].apply(
            lambda x: f"${x:,.0f}"
        )
        
        # Add total labels on top of stacked bars
        for i, row in monthly_totals.iterrows():
            fig_monthly.add_annotation(
                x=row["Date/Time"],
                y=row["Amount"],
                text=f"<b>{row['Amount_Text']}</b>",
                showarrow=False,
                yshift=10,
                font=dict(size=12, color="black")
            )
        
        fig_monthly.update_layout(
            barmode='stack',
            yaxis_title="Amount ($)",
            xaxis_title="Month"
        )
        # Save HTML file as backup
        monthly_file = "monthly_cash_inflows.html"
        fig_monthly.write_html(monthly_file)
        print(f"\nMonthly chart saved as {monthly_file}")
        
        print("Opening monthly chart in browser...")
        try:
            fig_monthly.show()
            print("Monthly chart opened successfully in browser.")
        except Exception as e:
            print(f"Could not open monthly chart in browser: {e}")
            print(f"Please open {monthly_file} manually in your browser.")

    # Create a stacked bar chart of cash inflows over the last 16 weeks
    if not filtered_cash_inflows.empty:
        sixteen_weeks_ago = datetime.now() - timedelta(weeks=16)
        recent_cash_inflows = filtered_cash_inflows[
            filtered_cash_inflows["Date/Time"] >= sixteen_weeks_ago
        ]
        
        # If no recent data, show all data
        if recent_cash_inflows.empty:
            print("No transactions in last 16 weeks. Showing all data for weekly chart.")
            recent_cash_inflows = filtered_cash_inflows.copy()
        
        if not recent_cash_inflows.empty:
            # Group by week and type
            weekly_cash_inflows = (
                recent_cash_inflows.groupby([
                    recent_cash_inflows["Date/Time"].dt.to_period("W"),
                    "Type"
                ])
                .agg({"Amount": "sum"})
                .reset_index()
            )
            
            # Format weekly labels as MMM-DD to MMM-DD (or just MMM-DD if same month)
            weekly_start = weekly_cash_inflows["Date/Time"].dt.start_time
            weekly_end = weekly_cash_inflows["Date/Time"].dt.end_time
            
            # Create date range labels
            date_labels = []
            for start, end in zip(weekly_start, weekly_end):
                if start.month == end.month:
                    # Same month: "Jun-02 to Jun-08"
                    label = f"{start.strftime('%b-%d')} to {end.strftime('%b-%d')}"
                else:
                    # Different months: "May-30 to Jun-05"
                    label = f"{start.strftime('%b-%d')} to {end.strftime('%b-%d')}"
                date_labels.append(label)
            
            weekly_cash_inflows["Date/Time"] = date_labels
            
            # Determine chart title based on data range
            num_recent = len(recent_cash_inflows)
            total_transactions = len(filtered_cash_inflows)
            if num_recent == total_transactions:
                chart_title = "Weekly Cash Inflows by Type - All Data"
            else:
                chart_title = "Weekly Cash Inflows by Type - Last 16 Weeks"
            
            # Create stacked bar chart
            fig_weekly = px.bar(
                weekly_cash_inflows,
                x="Date/Time",
                y="Amount",
                color="Type",
                title=chart_title,
                color_discrete_map={
                    "Dividends": "#2E86AB",
                    "Payment In Lieu Of Dividends": "#A23B72",
                    "Broker Interest Received": "#F18F01"
                }
            )
            
            # Calculate totals for each week to add labels
            weekly_totals = (
                weekly_cash_inflows.groupby("Date/Time")["Amount"]
                .sum()
                .reset_index()
            )
            weekly_totals["Amount_Text"] = weekly_totals["Amount"].apply(
                lambda x: f"${x:,.0f}"
            )
            
            # Add total labels on top of stacked bars
            for i, row in weekly_totals.iterrows():
                fig_weekly.add_annotation(
                    x=row["Date/Time"],
                    y=row["Amount"],
                    text=f"<b>{row['Amount_Text']}</b>",
                    showarrow=False,
                    yshift=10,
                    font=dict(size=12, color="black")
                )
            
            fig_weekly.update_layout(
                barmode='stack',
                yaxis_title="Amount ($)",
                xaxis_title="Week"
            )
            # Save HTML file as backup
            weekly_file = "weekly_cash_inflows.html"
            fig_weekly.write_html(weekly_file)
            print(f"\nWeekly chart saved as {weekly_file}")
            
            print(f"Opening weekly chart in browser ({chart_title})...")
            try:
                fig_weekly.show()
                print("Weekly chart opened successfully in browser.")
            except Exception as e:
                print(f"Could not open weekly chart in browser: {e}")
                print(f"Please open {weekly_file} manually in your browser.")
        else:
            print("Unable to create weekly chart - no data available.")
