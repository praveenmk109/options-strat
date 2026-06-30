import pandas as pd
import yfinance as yf
import urllib.request
import io
import concurrent.futures
from datetime import datetime, timedelta
import time
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_sp500_tickers():
    print("Scraping S&P 500 tickers from Wikipedia...")
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
    # Replace dot with dash for Yahoo Finance compatibility (e.g. BRK.B -> BRK-B)
    tickers = [t.replace('.', '-') for t in tickers]
    return tickers

def filter_by_liquidity(tickers, min_volume=8000000):
    print(f"Downloading 1-month volume data in bulk for {len(tickers)} tickers...")
    try:
        # Fetch 1 month of history to calculate average volume
        df_vol = yf.download(
            tickers, 
            period='1mo', 
            group_by='ticker',
            progress=False
        )
    except Exception as e:
        print(f"Error downloading volume data: {e}")
        return tickers # Fallback to all tickers if download fails
        
    liquid_tickers = []
    print("Filtering tickers by average daily volume...")
    for t in tickers:
        try:
            if len(tickers) == 1:
                t_df = df_vol
            else:
                t_df = df_vol[t]
            
            # Calculate mean volume
            mean_vol = t_df['Volume'].mean()
            if pd.notna(mean_vol) and mean_vol >= min_volume:
                liquid_tickers.append(t)
        except Exception:
            pass
            
    print(f"Liquidity Filter Complete: {len(liquid_tickers)}/{len(tickers)} tickers passed (ADV >= {min_volume:,} shares).")
    return liquid_tickers

def fetch_earnings_dates(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        df = ticker.earnings_dates
        if df is not None and not df.empty:
            return ticker_symbol, df
    except Exception:
        pass
    return ticker_symbol, None

def main():
    start_time = time.time()
    
    # 1. Scrape S&P 500 tickers
    all_tickers = get_sp500_tickers()
    
    # 2. Filter by Liquidity to get tradeable options candidates (ADV >= 8M)
    tickers = filter_by_liquidity(all_tickers, min_volume=8000000)
    
    if not tickers:
        print("No tickers passed the liquidity filter. Exiting.")
        return
        
    # 3. Fetch earnings dates in parallel for liquid survivors
    print(f"Fetching earnings dates for {len(tickers)} liquid tickers in parallel (using ThreadPool)...")
    earnings_dict = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        future_to_ticker = {executor.submit(fetch_earnings_dates, t): t for t in tickers}
        for i, future in enumerate(concurrent.futures.as_completed(future_to_ticker)):
            ticker_symbol, df_earnings = future.result()
            if df_earnings is not None:
                earnings_dict[ticker_symbol] = df_earnings
            if (i + 1) % 20 == 0 or (i + 1) == len(tickers):
                print(f"  Processed {i + 1}/{len(tickers)} tickers...")
                
    successful_tickers = list(earnings_dict.keys())
    print(f"Successfully retrieved earnings dates for {len(successful_tickers)} tickers.")
    
    if not successful_tickers:
        print("No earnings data retrieved. Exiting.")
        return
        
    # 4. Fetch daily price data in bulk for 36 months
    today = datetime.now()
    months = 36
    start_date = today - timedelta(days=months * 30.4375)
    price_start_date = start_date - timedelta(days=15)  # Pad start date for pre-earnings matching
    price_end_date = today + timedelta(days=5)          # Pad end date for post-earnings matching
    
    print(f"Downloading historical daily prices for {len(successful_tickers)} tickers in bulk...")
    try:
        df_prices = yf.download(
            successful_tickers, 
            start=price_start_date.strftime('%Y-%m-%d'), 
            end=price_end_date.strftime('%Y-%m-%d'),
            group_by='ticker',
            auto_adjust=True,
            progress=False
        )
    except Exception as e:
        print(f"Error downloading daily prices: {e}")
        return
        
    # Localize price DataFrame index to America/New_York
    if df_prices.index.tz is None:
        df_prices.index = df_prices.index.tz_localize('America/New_York')
    else:
        df_prices.index = df_prices.index.tz_convert('America/New_York')
        
    # Build prices dict by ticker for fast lookup
    prices_by_ticker = {}
    for t in successful_tickers:
        try:
            if len(successful_tickers) == 1:
                t_df = df_prices
            else:
                t_df = df_prices[t]
            t_df = t_df.dropna(subset=['Open', 'Close'])
            if not t_df.empty:
                prices_by_ticker[t] = {timestamp.date(): (timestamp, row['Open'], row['Close']) for timestamp, row in t_df.iterrows()}
        except Exception:
            pass
            
    # 5. Align prices with earnings dates
    results = []
    print("Aligning price data with earnings dates...")
    for t in successful_tickers:
        if t not in prices_by_ticker:
            continue
            
        ticker_prices = prices_by_ticker[t]
        trading_dates = sorted(list(ticker_prices.keys()))
        if not trading_dates:
            continue
            
        df_earnings = earnings_dict[t]
        df_earnings_filtered = df_earnings[df_earnings.index >= pd.Timestamp(start_date, tz='America/New_York')].copy()
        
        for earnings_timestamp, row in df_earnings_filtered.iterrows():
            earnings_date = earnings_timestamp.date()
            hour = earnings_timestamp.hour
            is_pre_market = hour < 12
            timing_str = "Pre-Market (BMO)" if is_pre_market else "After-Hours (AMC)"
            
            pre_earnings_date = None
            post_earnings_date = None
            
            if is_pre_market:
                if earnings_date in ticker_prices:
                    post_earnings_date = earnings_date
                    idx = trading_dates.index(post_earnings_date)
                    if idx > 0:
                        pre_earnings_date = trading_dates[idx - 1]
                else:
                    future_dates = [d for d in trading_dates if d >= earnings_date]
                    if future_dates:
                        post_earnings_date = future_dates[0]
                        idx = trading_dates.index(post_earnings_date)
                        if idx > 0:
                            pre_earnings_date = trading_dates[idx - 1]
            else:
                if earnings_date in ticker_prices:
                    pre_earnings_date = earnings_date
                    idx = trading_dates.index(pre_earnings_date)
                    if idx + 1 < len(trading_dates):
                        post_earnings_date = trading_dates[idx + 1]
                else:
                    past_dates = [d for d in trading_dates if d <= earnings_date]
                    if past_dates:
                        pre_earnings_date = past_dates[-1]
                        idx = trading_dates.index(pre_earnings_date)
                        if idx + 1 < len(trading_dates):
                            post_earnings_date = trading_dates[idx + 1]
                            
            if pre_earnings_date and post_earnings_date:
                _, _, pre_close = ticker_prices[pre_earnings_date]
                _, post_open, _ = ticker_prices[post_earnings_date]
                
                if pd.notna(pre_close) and pd.notna(post_open) and pre_close > 0:
                    change = post_open - pre_close
                    pct_change = (change / pre_close) * 100
                    
                    results.append({
                        "Ticker": t,
                        "Earnings Date": earnings_date.strftime('%Y-%m-%d'),
                        "Timing": timing_str,
                        "Pre-Earnings Date": pre_earnings_date.strftime('%Y-%m-%d'),
                        "Pre-Earnings Close ($)": round(pre_close, 2),
                        "Post-Earnings Date": post_earnings_date.strftime('%Y-%m-%d'),
                        "Post-Earnings Open ($)": round(post_open, 2),
                        "Change ($)": round(change, 2),
                        "Change (%)": round(pct_change, 2),
                        "EPS Estimate": row.get('EPS Estimate', None),
                        "Reported EPS": row.get('Reported EPS', None),
                        "Surprise (%)": row.get('Surprise(%)', None)
                    })
                    
    # 6. Save results to CSV
    df_results = pd.DataFrame(results)
    if not df_results.empty:
        output_file = os.path.join(SCRIPT_DIR, "sp500_earnings_reactions.csv")
        df_results = df_results.sort_values(by=["Ticker", "Earnings Date"], ascending=[True, False])
        df_results.to_csv(output_file, index=False)
        print(f"\nSaved {len(df_results)} records to {output_file}!")
        
        # Calculate summary statistics
        df_results['Abs Change (%)'] = df_results['Change (%)'].abs()
        summary_stats = df_results.groupby('Ticker').agg({
            'Abs Change (%)': 'mean',
            'Change (%)': ['mean', 'std', 'count']
        })
        summary_stats.columns = ['Avg Abs Change (%)', 'Avg Net Change (%)', 'Std Dev Change (%)', 'Earnings Count']
        summary_stats = summary_stats.reset_index()
        summary_stats = summary_stats.sort_values(by="Avg Abs Change (%)", ascending=False)
        
        summary_stats.to_csv(os.path.join(SCRIPT_DIR, "sp500_earnings_summary.csv"), index=False)
        print("Saved summary statistics to sp500_earnings_summary.csv!")
    else:
        print("No aligned records generated.")
        
    print(f"\nExecution finished in {time.time() - start_time:.2f} seconds.")

if __name__ == "__main__":
    main()
