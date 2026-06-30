import pandas as pd
import yfinance as yf
import urllib.request
import io
import concurrent.futures
import numpy as np
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    req = urllib.request.Request(
        url, 
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    )
    with urllib.request.urlopen(req) as response:
        html = response.read()
    html_str = html.decode('utf-8')
    tables = pd.read_html(io.StringIO(html_str), attrs={'id': 'constituents'})
    df = tables[0]
    tickers = sorted(df['Symbol'].unique().tolist())
    tickers = [t.replace('.', '-') for t in tickers]
    return tickers

def fetch_next_earnings(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.earnings_dates
        if df is not None and not df.empty:
            now = pd.Timestamp.now(tz='America/New_York')
            future_df = df[df.index > now]
            if not future_df.empty:
                future_df_sorted = future_df.sort_index(ascending=True)
                next_date = future_df_sorted.index[0]
                return ticker_symbol, next_date
    except Exception:
        pass
    return ticker_symbol, None

def main():
    print("Loading strategy simulations for S&P 500...")
    try:
        df_sims = pd.read_csv(os.path.join(SCRIPT_DIR, "sp500_strategy_simulations.csv"))
    except Exception as e:
        print("Could not load sp500_strategy_simulations.csv. Exiting.")
        return
        
    tickers = df_sims['Ticker'].tolist()
    print(f"Checking upcoming earnings dates for {len(tickers)} liquid S&P 500 stocks...")
    
    upcoming_earnings = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        future_to_ticker = {executor.submit(fetch_next_earnings, t): t for t in tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            ticker_symbol, next_date = future.result()
            if next_date is not None:
                upcoming_earnings.append({
                    "Ticker": ticker_symbol,
                    "Next Earnings Timestamp": next_date,
                    "Next Earnings Date": next_date.strftime('%Y-%m-%d'),
                    "Time (ET)": next_date.strftime('%I:%M %p')
                })
                
    if not upcoming_earnings:
        print("No upcoming earnings dates found for S&P 500.")
        return
        
    df_upcoming = pd.DataFrame(upcoming_earnings)
    df_upcoming = df_upcoming.sort_values(by="Next Earnings Timestamp", ascending=True)
    
    df_merged = pd.merge(df_upcoming, df_sims, on="Ticker", how="left")
    
    recommendations = []
    for _, row in df_merged.iterrows():
        ticker = row['Ticker']
        date_str = row['Next Earnings Date']
        time_str = row['Time (ET)']
        
        hour = row['Next Earnings Timestamp'].hour
        timing_class = "Pre-Market (BMO)" if hour < 12 else "After-Hours (AMC)"
        
        best_strategy = "No specific pattern"
        win_rate = 0.0
        avg_move = row.get('avg_abs_move', np.nan)
        
        bps = row.get('bps_win_rate_5', 0)
        bcs = row.get('bcs_win_rate_5', 0)
        ic5 = row.get('ic_win_rate_5', 0)
        ic3 = row.get('ic_win_rate_3', 0)
        
        if pd.notna(avg_move):
            if ic5 == 100.0:
                best_strategy = "Iron Condor (±5%)"
                win_rate = ic5
            elif bps == 100.0 and avg_move > 2.0:
                best_strategy = "Bull Put Spread (-5%)"
                win_rate = bps
            elif bcs == 100.0 and avg_move > 2.0:
                best_strategy = "Bear Call Spread (+5%)"
                win_rate = bcs
            elif ic3 >= 90.0:
                best_strategy = "Tight Iron Condor (±3%)"
                win_rate = ic3
            elif ic5 >= 90.0:
                best_strategy = "Iron Condor (±5%)"
                win_rate = ic5
            elif bps >= 90.0:
                best_strategy = "Bull Put Spread (-5%)"
                win_rate = bps
            elif bcs >= 90.0:
                best_strategy = "Bear Call Spread (+5%)"
                win_rate = bcs
                
        recommendations.append({
            "Ticker": ticker,
            "Earnings Date": date_str,
            "Time (ET)": time_str,
            "Session": timing_class,
            "Suggested Strategy": best_strategy,
            "Hist. Win Rate (%)": f"{win_rate:.1f}%" if win_rate > 0 else "N/A",
            "Avg Move (%)": f"{avg_move:.2f}%" if pd.notna(avg_move) else "N/A"
        })
        
    df_final = pd.DataFrame(recommendations)
    df_final.to_csv(os.path.join(SCRIPT_DIR, "sp500_upcoming_earnings_calendar.csv"), index=False)
    print("Saved upcoming calendar to sp500_upcoming_earnings_calendar.csv!")
    
    print("\nNext 20 Upcoming Earnings for liquid S&P 500 Stocks:")
    print(df_final.head(20).to_markdown(index=False))

if __name__ == "__main__":
    main()
