import config
import argparse
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import os
import numpy as np

import database_manager as db
import alpaca_utils as alpaca
import discord_utils as discord

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIMS_CSV = os.path.join(SCRIPT_DIR, "sp500_strategy_simulations.csv")

def get_monitored_tickers():
    conn = db.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT ticker FROM stocks_metadata")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def safe_val(v, fmt=None, default="N/A"):
    if v is None:
        return default
    try:
        if np.isnan(v):
            return default
    except (TypeError, ValueError):
        pass
    if fmt:
        return fmt % v
    return v

def _get_calendar_date(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        cal = t.calendar
        if not cal or not isinstance(cal, dict):
            return None
        ed_list = cal.get('Earnings Date')
        if not ed_list or not isinstance(ed_list, list) or not ed_list:
            return None
        return ed_list[0]
    except Exception:
        return None

def _fetch_earnings_with_session(ticker_symbol):
    try:
        t = yf.Ticker(ticker_symbol)
        df = t.earnings_dates
        if df is not None and not df.empty:
            return df
    except Exception:
        pass
    return None

def run_afternoon_execution():
    print("\n--- Running Afternoon Trade Scan (1:00 PM CT) ---")
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    tomorrow_str = (today + timedelta(days=1)).strftime('%Y-%m-%d')

    tickers = get_monitored_tickers()

    print(f"Fetching earnings dates for {len(tickers)} tickers (fast calendar pass)...")
    matching = []
    for t in tickers:
        ed = _get_calendar_date(t)
        if ed is None:
            continue
        ed_date = ed.strftime('%Y-%m-%d') if hasattr(ed, 'strftime') else str(ed)[:10]
        if ed_date == today_str or ed_date == tomorrow_str:
            matching.append((t, ed_date))

    print(f"Found {len(matching)} tickers with calendar dates matching today/tomorrow.")

    print(f"Fetching session details for {len(matching)} matching tickers...")
    earnings_data = {}
    for t, _ in matching:
        df_ed = _fetch_earnings_with_session(t)
        if df_ed is not None:
            earnings_data[t] = df_ed

    candidates = []
    for t, ed_str in matching:
        df_ed = earnings_data.get(t)
        if df_ed is not None and not df_ed.empty:
            for idx in df_ed.index:
                idx_str = idx.strftime('%Y-%m-%d')
                hour = idx.hour
                is_bmo = hour < 12
                if idx_str == today_str and not is_bmo:
                    candidates.append((t, idx_str, "After-Hours (AMC)"))
                    break
                elif idx_str == tomorrow_str and is_bmo:
                    candidates.append((t, idx_str, "Pre-Market (BMO)"))
                    break
                elif idx_str == ed_str:
                    candidates.append((t, idx_str, "Pre-Market (BMO)" if is_bmo else "After-Hours (AMC)"))
                    break

    print(f"Found {len(candidates)} potential candidates reporting today AMC or tomorrow BMO.")

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

        consensus, trend = alpaca.get_analyst_consensus(t)
        target_upside = None
        if consensus.get('target_mean') and price > 0:
            target_upside = (consensus['target_mean'] / price - 1) * 100

        suggested_strat = "Iron Condor"
        strategy_win_rate = 0
        if df_sims is not None:
            try:
                row_sim = df_sims[df_sims['Ticker'] == t].iloc[0]
                bps = row_sim.get('bps_win_rate_5', 0)
                bcs = row_sim.get('bcs_win_rate_5', 0)

                if bps >= bcs:
                    suggested_strat = "Bull Put"
                    strategy_win_rate = bps
                else:
                    suggested_strat = "Bear Call"
                    strategy_win_rate = bcs
            except Exception:
                pass

        alignment = 0
        if consensus.get('recommendation_mean') is not None:
            rec_mean = consensus['recommendation_mean']
            alignment = 3.0 - rec_mean  # positive = bullish, negative = bearish
            if suggested_strat == "Bear Call":
                alignment = -alignment

        adj_multiplier = multiplier * (1.0 + 0.2 * max(-1.0, min(1.0, -alignment)))
        adj_required_move = avg_move * adj_multiplier

        print(f"  Live Implied Move: {implied_move:.2f}%")
        print(f"  Required Move (Historical {avg_move:.2f}% * Multiplier {multiplier}): {required_move:.2f}%")
        print(f"  Consensus Alignment: {alignment:.2f} | Adj Multiplier: {adj_multiplier:.2f}")
        print(f"  Adjusted Required Move: {adj_required_move:.2f}%")

        if implied_move < adj_required_move:
            msg = f"Implied move {implied_move:.2f}% < Required move {adj_required_move:.2f}%"
            print(f"Skipping {t}: {msg} (No Edge).")
            skipped.append((t, msg))
            continue

        eps_est = eps_reported = eps_surprise = None
        try:
            df_earn = earnings_data.get(t)
            if df_earn is not None and not df_earn.empty:
                latest = df_earn.iloc[0]
                eps_est = safe_val(latest.get('EPS Estimate'), default=None)
                eps_reported = safe_val(latest.get('Reported EPS'), default=None)
                eps_surprise = safe_val(latest.get('Surprise(%)'), default=None)
        except Exception:
            pass

        call_vol, call_oi, put_vol, put_oi = alpaca.get_option_volume_and_oi(
            t, expiration_yymmdd, call_strike, put_strike
        )

        analyst_calls = alpaca.get_analyst_calls(t, max_count=3)

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
            "required_move": adj_required_move,
            "multiplier": adj_multiplier,
            "expiration_yymmdd": expiration_yymmdd,
            "eps_estimate": eps_est,
            "eps_reported": eps_reported,
            "eps_surprise": eps_surprise,
            "call_volume": call_vol,
            "call_open_interest": call_oi,
            "put_volume": put_vol,
            "put_open_interest": put_oi,
            "analyst_calls": analyst_calls,
            "consensus": consensus,
            "alignment": alignment,
            "target_upside": target_upside,
            "strategy_win_rate": strategy_win_rate,
        })

    result = discord.send_afternoon_advisory(today_str, candidates, viable, skipped)
    if result:
        print(f"Advisory sent: {len(viable)} viable, {len(skipped)} skipped of {len(candidates)} candidates.")
    else:
        print(f"Advisory skipped: no candidates ({len(candidates)}) or empty.")

    return bool(result)

def main():
    parser = argparse.ArgumentParser(description="Automated Earnings Option Trading System")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["afternoon"],
        help="afternoon (1:00 PM CT advisory)"
    )
    args = parser.parse_args()

    if alpaca.API_KEY == "YOUR_API_KEY":
        print("[WARNING] Running in DRY-RUN mode. Alpaca credentials are not set.")

    try:
        if args.mode == "afternoon":
            run_afternoon_execution()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"System error: {e}")

if __name__ == "__main__":
    main()
