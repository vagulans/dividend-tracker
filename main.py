import os
import requests
import pandas as pd
import argparse
from dotenv import load_dotenv
from io import StringIO
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import plotly.colors
from plotly.subplots import make_subplots

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
    # Avoid printing the entire XML to speed things up
    reference_code = response.text.split("<ReferenceCode>")[1].split("</ReferenceCode>")[0]
    return reference_code


def retrieve_flex_report(token, reference_code, quiet: bool = False):
    url = f"https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement?q={reference_code}&t={token}&v=3"
    response = requests.get(url)
    response.raise_for_status()

    # Save raw CSV response (align filename prefix with loader)
    os.makedirs("raw", exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    raw_file = f"raw/cash_flex_report_{timestamp}.csv"
    with open(raw_file, "w", encoding="utf-8") as f:
        f.write(response.text)
    if not quiet:
        print(f"\nRaw CSV data saved to: {raw_file}")

    return response.text


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
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Reduce console output for faster, cleaner runs",
    )
    parser.add_argument(
        "--no-show",
        action="store_true",
        help="Do not open charts in the browser; only save HTML files",
    )
    parser.add_argument(
        "--top-symbols",
        type=int,
        default=12,
        help="Number of top symbols to display in the symbol chart; others are grouped as 'Other'",
    )
    parser.add_argument(
        "--only-symbol-chart",
        action="store_true",
        help="Only generate the Symbol/Type weekly chart and skip other charts",
    )
    args = parser.parse_args()

    def log(message: str):
        if not args.quiet:
            print(message)

    # Setup cache directories and today's stamp
    today = datetime.now().strftime("%Y%m%d")
    raw_dir = "raw"
    os.makedirs(raw_dir, exist_ok=True)
    cache_dir = "cache"
    os.makedirs(cache_dir, exist_ok=True)
    parquet_cache_path = os.path.join(cache_dir, f"filtered_cash_inflows_{today}.parquet")

    latest_cash_file = None
    use_cache = not args.no_cache

    # Try parsed cache first to skip processing entirely
    filtered_cash_inflows = pd.DataFrame()
    if use_cache and os.path.exists(parquet_cache_path):
        try:
            log(f"Loading parsed cache from: {parquet_cache_path}")
            filtered_cash_inflows = pd.read_parquet(parquet_cache_path)
        except Exception as e:
            log(f"Warning: Could not read parsed cache, will rebuild: {e}")
            filtered_cash_inflows = pd.DataFrame()
    else:
        # Check if a cash transactions CSV exists from today
        cash_files = [
            f
            for f in os.listdir(raw_dir)
            if f.endswith(".csv") and (f.startswith("cash_flex_report_") or f.startswith("flex_report_"))
        ]
        if cash_files and use_cache:
            latest_cash_file = max(
                cash_files, key=lambda x: os.path.getctime(os.path.join(raw_dir, x))
            )
            if today in latest_cash_file:
                log(f"Loading latest cash transactions from: {latest_cash_file}")
                cash_transactions_df = pd.read_csv(os.path.join(raw_dir, latest_cash_file))
            else:
                log("No cash transactions file found for today. Requesting new data...")
                reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
                log(
                    f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report..."
                )
                report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash, quiet=args.quiet)
                cash_transactions_df = parse_report(report_content_cash, quiet=args.quiet)
        else:
            if args.no_cache:
                log("Cache override requested. Fetching fresh data from IBKR...")
            else:
                log("No cash transactions file found. Requesting new data...")
            reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
            log(
                f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report..."
            )
            report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash, quiet=args.quiet)
            cash_transactions_df = parse_report(report_content_cash, quiet=args.quiet)

    # Filter for all cash inflows (not just dividends) if not loaded from parsed cache
    if filtered_cash_inflows.empty:
        filtered_cash_inflows = filter_cash_inflows(cash_transactions_df)

    # Precompute dates once for speed and reuse
    if not filtered_cash_inflows.empty and "DateOnly" not in filtered_cash_inflows.columns:
        # Normalize to date-only
        if filtered_cash_inflows["Date/Time"].dtype == object:
            filtered_cash_inflows["Date/Time"] = filtered_cash_inflows["Date/Time"].str.split(";").str[0]
        filtered_cash_inflows["DateOnly"] = pd.to_datetime(filtered_cash_inflows["Date/Time"])  # datetime64
        filtered_cash_inflows["MonthPeriod"] = filtered_cash_inflows["DateOnly"].dt.to_period("M")
        filtered_cash_inflows["WeekPeriod"] = filtered_cash_inflows["DateOnly"].dt.to_period("W")

    # Persist parsed cache for warm runs
    if not filtered_cash_inflows.empty and not os.path.exists(parquet_cache_path):
        try:
            filtered_cash_inflows.to_parquet(parquet_cache_path, index=False)
            log(f"Saved parsed cache to: {parquet_cache_path}")
        except Exception as e:
            log(f"Warning: Could not save parsed cache: {e}")

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
        log("\nFiltered cash inflows saved to filtered_cash_inflows.csv")

    # Print a clean DataFrame of the transactions
    if not filtered_cash_inflows.empty:
        clean_df = filtered_cash_inflows[
            ["Type", "Symbol", "SettleDate", "ReportDate", "ExDate", "Amount"]
        ]
        print("\nClean DataFrame of Cash Inflow Transactions:")
        print(clean_df)

    # Create a monthly stacked bar chart of cash inflows by type
    if not filtered_cash_inflows.empty and not args.only_symbol_chart:
        # Group by month and type using precomputed periods
        monthly_cash_inflows = (
            filtered_cash_inflows.groupby([
                filtered_cash_inflows["MonthPeriod"],
                "Type",
            ]).agg({"Amount": "sum"}).reset_index()
        )
        # Normalize column name for downstream formatting logic
        monthly_cash_inflows["Date/Time"] = monthly_cash_inflows["MonthPeriod"]
        
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
        fig_monthly.write_html(monthly_file, include_plotlyjs="cdn")
        log(f"\nMonthly chart saved as {monthly_file}")

        if not args.no_show:
            log("Opening monthly chart in browser...")
            try:
                fig_monthly.show()
                log("Monthly chart opened successfully in browser.")
            except Exception as e:
                log(f"Could not open monthly chart in browser: {e}")
                log(f"Please open {monthly_file} manually in your browser.")

    # Create a stacked bar chart of cash inflows over the last 16 weeks
    if not filtered_cash_inflows.empty and not args.only_symbol_chart:
        sixteen_weeks_ago = datetime.now() - timedelta(weeks=16)
        recent_cash_inflows = filtered_cash_inflows[
            filtered_cash_inflows["DateOnly"] >= sixteen_weeks_ago
        ]
        
        # If no recent data, show all data
        if recent_cash_inflows.empty:
            print("No transactions in last 16 weeks. Showing all data for weekly chart.")
            recent_cash_inflows = filtered_cash_inflows.copy()
        
        if not recent_cash_inflows.empty:
            # Group by week and type
            weekly_cash_inflows = (
                recent_cash_inflows.groupby([
                    recent_cash_inflows["WeekPeriod"],
                    "Type",
                ]).agg({"Amount": "sum"}).reset_index()
            )
            # Normalize column name for downstream labeling logic
            weekly_cash_inflows["Date/Time"] = weekly_cash_inflows["WeekPeriod"]
            
            # Sort by date chronologically before formatting to strings
            weekly_cash_inflows = weekly_cash_inflows.sort_values("Date/Time")
            
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
            
            # Get unique weeks in chronological order to preserve sorting in plotly
            week_order = weekly_cash_inflows["Date/Time"].unique().tolist()
            
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
                },
                category_orders={"Date/Time": week_order}
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
            fig_weekly.write_html(weekly_file, include_plotlyjs="cdn")
            log(f"\nWeekly chart saved as {weekly_file}")

            if not args.no_show:
                log(f"Opening weekly chart in browser ({chart_title})...")
                try:
                    fig_weekly.show()
                    log("Weekly chart opened successfully in browser.")
                except Exception as e:
                    log(f"Could not open weekly chart in browser: {e}")
                    log(f"Please open {weekly_file} manually in your browser.")
        else:
            log("Unable to create weekly chart - no data available.")

    # Create a third chart showing cash inflows by Symbol/Type over the last 16 weeks
    if not filtered_cash_inflows.empty:
        sixteen_weeks_ago = datetime.now() - timedelta(weeks=16)
        recent_cash_inflows = filtered_cash_inflows[
            filtered_cash_inflows["DateOnly"] >= sixteen_weeks_ago
        ]
        
        # If no recent data, show all data
        if recent_cash_inflows.empty:
            print("No transactions in last 16 weeks. Showing all data for symbol chart.")
            recent_cash_inflows = filtered_cash_inflows.copy()
        
        if not recent_cash_inflows.empty:
            # Create hybrid Symbol/Type field: use Symbol when available, fallback to Type
            recent_cash_inflows_copy = recent_cash_inflows.copy()
            recent_cash_inflows_copy["Symbol_Type"] = recent_cash_inflows_copy["Symbol"].fillna(
                recent_cash_inflows_copy["Type"]
            )

            # Limit to Top N symbols/types and group the rest into 'Other' for faster rendering
            totals_by_symbol = (
                recent_cash_inflows_copy.groupby("Symbol_Type")["Amount"].sum().sort_values(ascending=False)
            )
            top_n = max(1, args.top_symbols)
            top_symbols = set(totals_by_symbol.head(top_n).index.tolist())
            recent_cash_inflows_copy.loc[~recent_cash_inflows_copy["Symbol_Type"].isin(top_symbols), "Symbol_Type"] = "Other"
            
            # Group by week and Symbol/Type
            symbol_weekly_cash_inflows = (
                recent_cash_inflows_copy.groupby([
                    recent_cash_inflows_copy["WeekPeriod"],
                    "Symbol_Type",
                ]).agg({"Amount": "sum"}).reset_index()
            )
            # Normalize column name for downstream labeling logic
            symbol_weekly_cash_inflows["Date/Time"] = symbol_weekly_cash_inflows["WeekPeriod"]
            
            # Sort by date chronologically before formatting to strings
            symbol_weekly_cash_inflows = symbol_weekly_cash_inflows.sort_values("Date/Time")
            
            # Format weekly labels as MMM-DD to MMM-DD (same as weekly chart)
            weekly_start = symbol_weekly_cash_inflows["Date/Time"].dt.start_time
            weekly_end = symbol_weekly_cash_inflows["Date/Time"].dt.end_time
            
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
            
            symbol_weekly_cash_inflows["Date/Time"] = date_labels
            
            # Get unique weeks in chronological order to preserve sorting in plotly
            week_order = symbol_weekly_cash_inflows["Date/Time"].unique().tolist()
            
            # Get unique symbols/types and assign colors dynamically
            unique_symbols = symbol_weekly_cash_inflows["Symbol_Type"].unique()
            color_palette = plotly.colors.qualitative.Set3
            
            # Create color map for symbols
            symbol_color_map = {}
            for i, symbol in enumerate(unique_symbols):
                symbol_color_map[symbol] = color_palette[i % len(color_palette)]
            
            # Determine chart title based on data range
            num_recent = len(recent_cash_inflows)
            total_transactions = len(filtered_cash_inflows)
            if num_recent == total_transactions:
                symbol_chart_title = "Weekly Cash Inflows by Symbol/Type - All Data"
            else:
                symbol_chart_title = "Weekly Cash Inflows by Symbol/Type - Last 16 Weeks"
            
            # Prepare summary table data
            symbol_totals = (
                recent_cash_inflows_copy.groupby("Symbol_Type")["Amount"]
                .sum()
                .sort_values(ascending=False)
                .reset_index()
            )
            symbol_totals["Total Amount"] = symbol_totals["Amount"].apply(lambda x: f"${x:,.2f}")
            grand_total = symbol_totals["Amount"].sum()
            
            # Create subplot layout: bar chart on left, table on right
            fig_symbol = make_subplots(
                rows=1, cols=2,
                column_widths=[0.72, 0.28],
                specs=[[{"type": "xy"}, {"type": "table"}]],
                subplot_titles=[symbol_chart_title, "Total Cash Inflows by Symbol/Type"],
                horizontal_spacing=0.06
            )
            
            # Create individual bar traces for each Symbol/Type (for stacking)
            for symbol in unique_symbols:
                symbol_data = symbol_weekly_cash_inflows[
                    symbol_weekly_cash_inflows["Symbol_Type"] == symbol
                ]
                fig_symbol.add_trace(
                    go.Bar(
                        x=symbol_data["Date/Time"],
                        y=symbol_data["Amount"],
                        name=symbol,
                        marker_color=symbol_color_map[symbol],
                        showlegend=True
                    ),
                    row=1, col=1
                )
            
            # Calculate totals for each week to add labels
            symbol_weekly_totals = (
                symbol_weekly_cash_inflows.groupby("Date/Time")["Amount"]
                .sum()
                .reset_index()
            )
            symbol_weekly_totals["Amount_Text"] = symbol_weekly_totals["Amount"].apply(
                lambda x: f"${x:,.0f}"
            )
            
            # Add total labels on top of stacked bars
            for i, row in symbol_weekly_totals.iterrows():
                fig_symbol.add_annotation(
                    x=row["Date/Time"],
                    y=row["Amount"],
                    text=f"<b>{row['Amount_Text']}</b>",
                    showarrow=False,
                    yshift=10,
                    font=dict(size=12, color="black"),
                    row=1, col=1
                )
            
            # Add summary table
            fig_symbol.add_trace(
                go.Table(
                    header=dict(
                        values=["<b>Symbol/Type</b>", "<b>Total Amount</b>"],
                        fill_color="lightblue",
                        align="left",
                        font=dict(size=12, color="black")
                    ),
                    cells=dict(
                        values=[
                            symbol_totals["Symbol_Type"].tolist() + ["<b>GRAND TOTAL</b>"],
                            symbol_totals["Total Amount"].tolist() + [f"<b>${grand_total:,.2f}</b>"]
                        ],
                        fill_color=[["white", "lightgray"] * (len(symbol_totals) + 1)],
                        align="left",
                        font=dict(size=11)
                    )
                ),
                row=1, col=2
            )
            
            # Update layout
            fig_symbol.update_layout(
                barmode='stack',
                height=600,
                showlegend=True,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0.0),
                margin=dict(t=110)
            )
            
            # Update axes for the bar chart
            fig_symbol.update_xaxes(title_text="Week", row=1, col=1, categoryorder="array", categoryarray=week_order)
            fig_symbol.update_yaxes(title_text="Amount ($)", row=1, col=1)
            
            # Save HTML file as backup
            symbol_file = "symbol_weekly_cash_inflows.html"
            fig_symbol.write_html(symbol_file, include_plotlyjs="cdn")
            log(f"\nSymbol-based weekly chart with embedded table saved as {symbol_file}")

            if not args.no_show:
                log(f"\nOpening symbol-based weekly chart in browser ({symbol_chart_title})...")
                try:
                    fig_symbol.show()
                    log("Symbol-based weekly chart opened successfully in browser.")
                except Exception as e:
                    log(f"Could not open symbol-based weekly chart in browser: {e}")
                    log(f"Please open {symbol_file} manually in your browser.")
        else:
            log("Unable to create symbol-based weekly chart - no data available.")
