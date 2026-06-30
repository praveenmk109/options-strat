import config
import argparse
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import os
import concurrent.futures

# Import our modular utilities
import database_manager as db
import alpaca_utils as alpaca
import discord_utils as discord

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIMS_CSV = os.path.join(SCRIPT_DIR, "sp500_strategy_simulations.csv")

# Define the list of liquid S&P 500 stocks (we have 100 seeded in SQLite)
def get_monitored_tickers():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticker FROM stocks_metadata")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def fetch_earnings_dates_batch(tickers):
    """Fetch earnings dates for multiple tickers in parallel."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_ticker = {executor.submit(_fetch_single_earnings, t): t for t in tickers}
        for future in concurrent.futures.as_completed(future_to_ticker):
            t, df = future.result()
            if df is not None:
                results[t] = df
    return results

def _fetch_single_earnings(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        df = ticker_obj.earnings_dates
        if df is not None and not df.empty:
            return ticker, df
    except Exception:
        pass
    return ticker, None

def run_afternoon_execution():
    print("\n--- Running Afternoon Trade Scan (2:00 PM CT) ---")
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')
    
    tickers = get_monitored_tickers()
    candidates = []
    
    # At 2:00 PM CT, we target:
    # 1. Stocks reporting TODAY After-Hours (AMC)
    # 2. Stocks reporting TOMORROW Pre-Market (BMO)
    print(f"Fetching earnings dates for {len(tickers)} tickers (parallel)...")
    earnings_data = fetch_earnings_dates_batch(tickers)
    
    for t, df_earnings in earnings_data.items():
        for idx in df_earnings.index:
            earnings_date_str = idx.strftime('%Y-%m-%d')
            hour = idx.hour
            is_pre_market = hour < 12
            
            if earnings_date_str == today_str and not is_pre_market:
                candidates.append((t, earnings_date_str, "After-Hours (AMC)"))
            elif earnings_date_str == tomorrow_str and is_pre_market:
                candidates.append((t, earnings_date_str, "Pre-Market (BMO)"))
            
    print(f"Found {len(candidates)} potential candidates reporting today AMC or tomorrow BMO.")
    
    # Load simulation data once
    try:
        df_sims = pd.read_csv(SIMS_CSV)
    except Exception:
        df_sims = None

    viable = []
    skipped = []

    for t, earnings_date, session in candidates:
        print(f"\nProcessing candidate: {t}")
        
        price = alpaca.get_current_stock_price(t)
        if not price:
            msg = "Could not retrieve stock price"
            print(f"Skipping {t}: {msg}.")
            skipped.append((t, msg))
            continue
            
            
        meta = db.get_stock_metadata(t)
        if not meta:
            msg = "No database metadata found"
            print(f"Skipping {t}: {msg}.")
            skipped.append((t, msg))
            continue
            
        avg_move = meta['avg_abs_move']
        multiplier = meta['dynamic_multiplier']
        required_move = avg_move * multiplier
        
        res_straddle = alpaca.get_atm_straddle_implied_move(t, price)
        if not res_straddle:
            msg = "Failed to fetch option straddle quotes"
            print(f"Skipping {t}: {msg}.")
            skipped.append((t, msg))
            continue
            
        implied_move, straddle_price, expiration_yymmdd, call_strike, put_strike = res_straddle
        
        # Fetch option volume / OI for the ATM strikes
        call_vol, call_oi, put_vol, put_oi = alpaca.get_option_volume_and_oi(
            t, expiration_yymmdd, call_strike, put_strike
        )
        news = alpaca.get_recent_news(t, max_count=3)

        print(f"  Live Implied Move: {implied_move:.2f}%")
        print(f"  Required Move (Historical {avg_move:.2f}% * Multiplier {multiplier}): {required_move:.2f}%")
        
        if implied_move < required_move:
            msg = f"Implied move {implied_move:.2f}% < Required move {required_move:.2f}%"
            print(f"Skipping {t}: {msg} (No Edge).")
            skipped.append((t, msg))
            continue
            
        # Fetch last EPS data from yfinance earnings dates
        eps_est = eps_reported = eps_surprise = None
        try:
            df_earn = earnings_data[t]
            if df_earn is not None and not df_earn.empty:
                latest = df_earn.iloc[0]
                eps_est = latest.get('EPS Estimate')
                eps_reported = latest.get('Reported EPS')
                eps_surprise = latest.get('Surprise(%)')
        except Exception:
            pass
            
        # Edge confirmed! Determine strategy
        suggested_strat = "Iron Condor"
        if df_sims is not None:
            try:
                row_sim = df_sims[df_sims['Ticker'] == t].iloc[0]
                bps = row_sim.get('bps_win_rate_5', 0)
                bcs = row_sim.get('bcs_win_rate_5', 0)
                
                if bps >= bcs:
                    suggested_strat = "Bull Put"
                else:
                    suggested_strat = "Bear Call"
            except Exception:
                pass
            
        wing_width = 1.0 if price < 100.0 else 2.0
        
        short_put, long_put = None, None
        short_call, long_call = None, None
        
        if suggested_strat in ["Iron Condor", "Bull Put"]:
            short_put = round(price * 0.95)
            long_put = short_put - wing_width
                
        if suggested_strat in ["Iron Condor", "Bear Call"]:
            short_call = round(price * 1.05)
            long_call = short_call + wing_width
            
        est_credit = 0.35 * wing_width if suggested_strat == "Iron Condor" else 0.20 * wing_width
        margin = wing_width * 100.0
        
        viable.append({
            "ticker": t,
            "session": session,
            "earnings_date": earnings_date,
            "strategy": suggested_strat,
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call,
            "price": price,
            "wing_width": wing_width,
            "est_credit": est_credit,
            "margin": margin,
            "implied_move": implied_move,
            "straddle_price": straddle_price,
            "hist_move": avg_move,
            "required_move": required_move,
            "multiplier": multiplier,
            "expiration_yymmdd": expiration_yymmdd,
            "eps_estimate": eps_est,
            "eps_reported": eps_reported,
            "eps_surprise": eps_surprise,
            "call_volume": call_vol,
            "call_open_interest": call_oi,
            "put_volume": put_vol,
            "put_open_interest": put_oi,
            "news": news,
        })
    
    discord.send_afternoon_advisory(today_str, candidates, viable, skipped)

def main():
    parser = argparse.ArgumentParser(description="Automated Earnings Option Trading System")
    parser.add_argument(
        "--mode", 
        required=True, 
        choices=["afternoon"],
        help="afternoon (2:00 PM CT advisory)"
    )
    args = parser.parse_args()
    
    # Check credentials
    if alpaca.API_KEY == "YOUR_API_KEY":
        print("[WARNING] Running in DRY-RUN mode. Alpaca credentials are not set.")
        
    try:
        if args.mode == "afternoon":
            run_afternoon_execution()
    except Exception as e:
        # Send crash alerts to Discord
        import traceback
        err_msg = traceback.format_exc()
        print(f"System error: {e}")
        discord.send_error_alert(err_msg)

if __name__ == "__main__":
    main()
