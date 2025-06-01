import os
import requests
import pandas as pd
from dotenv import load_dotenv
from io import StringIO
from datetime import datetime

# Load the .env file to get your token
load_dotenv()
TOKEN = os.getenv("TOKEN")

# IBKR Flex Web Service endpoint
FLEX_URL = "https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t="
QUERY_ID_CASH_TRANSACTIONS = (
    "1229475"  # Flex Query ID for cash transactions (including dividends)
)
QUERY_ID_TRADES = "1229476"  # Flex Query ID for trades


# Step 1: Request Flex Report generation
def request_flex_report(token, query_id):
    url = f"{FLEX_URL}{token}&q={query_id}&v=3"
    response = requests.get(url)
    response.raise_for_status()
    print("Response content:", response.text)
    reference_code = response.text.split("<ReferenceCode>")[1].split(
        "</ReferenceCode>"
    )[0]
    return reference_code


# Step 2: Retrieve Flex Report using the reference code
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


# Step 3: Parse the CSV report into a DataFrame
def parse_report(report_content):
    data = StringIO(report_content)
    df = pd.read_csv(data)
    print("\nDataFrame info:")
    print(df.info())
    if "TransactionType" in df.columns:
        print("\nUnique Transaction Types:")
        print(df["TransactionType"].unique())
    else:
        print("\nNo TransactionType column found.")
    return df


# Step 4: Filter transactions for dividends, buys, and sells
def filter_transactions(df):
    if "TransactionType" not in df.columns:
        print("Warning: TransactionType column not found in the data")
        return df
    # Filter for all trades and dividends
    filtered_df = df[
        df["TransactionType"].isin(["ExchTrade", "BookTrade", "Code", "Dividend"])
    ]
    return filtered_df


# Main Execution
if __name__ == "__main__":
    # Request cash transactions (including dividends)
    reference_code_cash = request_flex_report(TOKEN, QUERY_ID_CASH_TRANSACTIONS)
    print(
        f"Reference code for cash transactions received: {reference_code_cash}. Retrieving report..."
    )
    report_content_cash = retrieve_flex_report(TOKEN, reference_code_cash)
    cash_transactions_df = parse_report(report_content_cash)
    filtered_cash_transactions = filter_transactions(cash_transactions_df)
    print("\nFiltered cash transactions:")
    print(filtered_cash_transactions)

    # Request trades
    reference_code_trades = request_flex_report(TOKEN, QUERY_ID_TRADES)
    print(
        f"Reference code for trades received: {reference_code_trades}. Retrieving report..."
    )
    report_content_trades = retrieve_flex_report(TOKEN, reference_code_trades)
    trades_df = parse_report(report_content_trades)
    filtered_trades = filter_transactions(trades_df)
    print("\nFiltered trades:")
    print(filtered_trades)

    # Summary of trades and dividends
    if not filtered_cash_transactions.empty:
        print("\nSummary of cash transactions (including dividends):")
        summary_cash = (
            filtered_cash_transactions.groupby("TransactionType")
            .agg({"Symbol": "count", "TradeMoney": "sum"})
            .rename(columns={"Symbol": "Count", "TradeMoney": "Total Amount"})
        )
        print(summary_cash)

    if not filtered_trades.empty:
        print("\nSummary of trades:")
        summary_trades = (
            filtered_trades.groupby("TransactionType")
            .agg({"Symbol": "count", "TradeMoney": "sum"})
            .rename(columns={"Symbol": "Count", "TradeMoney": "Total Amount"})
        )
        print(summary_trades)

    # Save filtered transactions
    if not filtered_cash_transactions.empty:
        filtered_cash_transactions.to_csv("filtered_cash_transactions.csv", index=False)
        print("\nFiltered cash transactions saved to filtered_cash_transactions.csv")

    if not filtered_trades.empty:
        filtered_trades.to_csv("filtered_trades.csv", index=False)
        print("\nFiltered trades saved to filtered_trades.csv")
