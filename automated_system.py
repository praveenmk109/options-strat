import config
import argparse
import pandas as pd
from datetime import datetime, timedelta
import yfinance as yf
import os
import time
import numpy as np

import database_manager as db
import alpaca_utils as alpaca
import discord_utils as discord

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIMS_CSV = os.path.join(SCRIPT_DIR, "sp500_strategy_simulations.csv")
MAX_RETRIES = 2
RETRY_DELAY = 3  # seconds

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
    for attempt in range(1 + MAX_RETRIES):
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
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return None

def _fetch_earnings_with_session(ticker_symbol):
    for attempt in range(1 + MAX_RETRIES):
        try:
            t = yf.Ticker(ticker_symbol)
            df = t.earnings_dates
            if df is not None and not df.empty:
                return df
        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(RETRY_DELAY)
    return None

def run_afternoon_execution():
    print("\n--- Running Afternoon Trade Scan (1:00 PM CT) ---")
    today = datetime.now()
    today_str = today.strftime('%Y-%m-%d')
    days_ahead = 1
    if today.weekday() == 4:  # Friday → skip to Monday
        days_ahead = 3
    elif today.weekday() == 5:  # Saturday → skip to Monday
        days_ahead = 2
    tomorrow_str = (today + timedelta(days=days_ahead)).strftime('%Y-%m-%d')

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
        session = None
        df_ed = earnings_data.get(t)
        if df_ed is not None and not df_ed.empty:
            for idx in df_ed.index:
                idx_str = idx.strftime('%Y-%m-%d')
                hour = idx.hour
                is_bmo = hour < 12
                if idx_str == today_str and not is_bmo:
                    session = "After-Hours (AMC)"
                    break
                elif idx_str == tomorrow_str and is_bmo:
                    session = "Pre-Market (BMO)"
                    break
        if session is None and ed_str == today_str:
            session = "After-Hours (AMC)"
        if session:
            if df_ed is not None and not df_ed.empty:
                for idx in df_ed.index:
                    idx_str = idx.strftime('%Y-%m-%d')
                    if idx_str == ed_str:
                        if 'Reported EPS' in df_ed.columns:
                            reported_eps = df_ed.loc[idx, 'Reported EPS']
                            if pd.notna(reported_eps):
                                print(f"Skipping {t}: Already reported (EPS: {reported_eps})")
                                session = None
                        break
        if session:
            candidates.append((t, ed_str, session))

    print(f"Found {len(candidates)} potential candidates reporting today AMC or confirmed tomorrow BMO.")

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

        res_straddle = alpaca.get_atm_straddle_implied_move(t, price)
        if not res_straddle:
            msg = "Failed to fetch option straddle quotes"
            print(f"Skipping {t}: {msg}.")
            skipped.append((t, msg))
            continue

        implied_move, straddle_price, expiration_yymmdd, call_strike, put_strike = res_straddle

        consensus = alpaca.get_analyst_consensus(t)
        target_upside = None
        if consensus.get('target_mean') and price > 0:
            target_upside = (consensus['target_mean'] / price - 1) * 100

        suggested_strat = "Bull Put"
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

        adj_multiplier = multiplier * (1.0 + 0.1 * max(-1.0, min(1.0, -alignment)))
        adj_required_move = avg_move * adj_multiplier

        print(f"  Live Implied Move: {implied_move:.2f}%")
        print(f"  Required Move (Historical {avg_move:.2f}% * Multiplier {multiplier}): {avg_move * multiplier:.2f}%")
        print(f"  Consensus Alignment: {alignment:.2f} | Adj Multiplier: {adj_multiplier:.2f}")
        print(f"  Adjusted Required Move: {adj_required_move:.2f}%")

        if implied_move < adj_required_move:
            msg = f"Implied move {implied_move:.2f}% < Required move {adj_required_move:.2f}%"
            print(f"Skipping {t}: {msg} (No Edge).")
            skipped.append((t, msg))
            continue

        call_vol, call_oi, put_vol, put_oi = alpaca.get_option_volume_and_oi(
            t, expiration_yymmdd, call_strike, put_strike
        )

        analyst_calls = alpaca.get_analyst_calls(t, max_count=3)

        ww = int(max(1, round(straddle_price * 0.5)))
        straddle_buffer = 1.2
        offset = round(straddle_price * straddle_buffer / ww) * ww

        short_put, long_put = None, None
        short_call, long_call = None, None

        if suggested_strat == "Bull Put":
            short_put = round(price / ww) * ww - offset
            long_put = short_put - ww
        else:
            short_call = round(price / ww) * ww + offset
            long_call = short_call + ww

        est_credit = None
        if suggested_strat == "Bear Call" and short_call:
            short_price = alpaca.get_option_price(t, expiration_yymmdd, short_call, "call")
            long_price = alpaca.get_option_price(t, expiration_yymmdd, long_call, "call")
            if short_price is not None and long_price is not None:
                est_credit = short_price - long_price
        elif short_put:
            short_price = alpaca.get_option_price(t, expiration_yymmdd, short_put, "put")
            long_price = alpaca.get_option_price(t, expiration_yymmdd, long_put, "put")
            if short_price is not None and long_price is not None:
                est_credit = short_price - long_price
        if est_credit is None or est_credit <= 0:
            est_credit = 0.20 * ww
        margin = ww * 100.0

        viable.append({
            "ticker": t,
            "company_name": alpaca.get_company_name(t),
            "session": session,
            "earnings_date": earnings_date,
            "strategy": suggested_strat,
            "short_put": short_put,
            "long_put": long_put,
            "short_call": short_call,
            "long_call": long_call,
            "price": price,
            "wing_width": ww,
            "est_credit": est_credit,
            "margin": margin,
            "implied_move": implied_move,
            "straddle_price": straddle_price,
            "hist_move": avg_move,
            "required_move": adj_required_move,
            "multiplier": adj_multiplier,
            "expiration_yymmdd": expiration_yymmdd,
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

def run_weekly_preview():
    print("\n--- Running Weekly Earnings Preview (Sunday 8 AM CT) ---")
    today = datetime.now()
    end_date = today + timedelta(days=7)

    tickers = get_monitored_tickers()
    print(f"Scanning {len(tickers)} tickers for this week's earnings...")

    summ = {}
    try:
        df = pd.read_csv(os.path.join(SCRIPT_DIR, "sp500_earnings_summary.csv"))
        for _, r in df.iterrows():
            summ[r['Ticker']] = r
    except Exception:
        pass

    sims = {}
    try:
        df = pd.read_csv(SIMS_CSV)
        for _, r in df.iterrows():
            sims[r['Ticker']] = r
    except Exception:
        pass

    week = []
    for t in tickers:
        ed = _get_calendar_date(t)
        if ed is None:
            continue
        if today.date() <= ed <= end_date.date():
            try:
                tk = yf.Ticker(t)
                price = tk.info.get('currentPrice') or tk.info.get('regularMarketPrice')
            except Exception:
                price = None
            if not price:
                continue
            win_rate = None
            strategy = "Bull Put"
            if t in sims:
                r = sims[t]
                bps = r.get('bps_win_rate_5', 0)
                bcs = r.get('bcs_win_rate_5', 0)
                if bps >= bcs:
                    strategy = "Bull Put"
                    win_rate = float(bps)
                else:
                    strategy = "Bear Call"
                    win_rate = float(bcs)

            if t not in summ:
                continue
            hist_abs = float(summ[t]['Avg Abs Change (%)'])
            hist_net = float(summ[t]['Avg Net Change (%)'])

            weekday_num = ed.weekday()
            day_name = ed.strftime('%A')
            date_str = ed.strftime('%b %d')

            week.append({
                "ticker": t,
                "price": price,
                "date": ed,
                "day_name": day_name,
                "date_str": date_str,
                "hist_abs": hist_abs,
                "hist_net": hist_net,
                "strategy": strategy,
                "win_rate": win_rate,
            })

    week.sort(key=lambda x: (x['date'], x['ticker']))
    print(f"Found {len(week)} tickers with earnings this week.")

    if not week:
        print("No earnings this week. Skipping preview.")
        return False

    groups = []
    current_key = None
    current_group = None
    for s in week:
        key = f"{s['day_name']} {s['date_str']}"
        if key != current_key:
            if current_group is not None:
                groups.append((current_key, current_group))
            current_key = key
            current_group = []
        current_group.append(s)
    if current_group is not None:
        groups.append((current_key, current_group))

    result = discord.send_weekly_preview(groups)
    if result:
        print(f"Weekly preview sent: {len(week)} tickers across {len(groups)} days.")
    else:
        print("Weekly preview send failed.")
    return bool(result)

def main():
    parser = argparse.ArgumentParser(description="Automated Earnings Option Trading System")
    parser.add_argument(
        "--mode",
        required=True,
        choices=["afternoon", "weekly"],
        help="afternoon (1:00 PM CT advisory) | weekly (Sunday 8 AM CT preview)"
    )
    args = parser.parse_args()

    try:
        if args.mode == "afternoon":
            run_afternoon_execution()
        elif args.mode == "weekly":
            run_weekly_preview()
    except Exception as e:
        import traceback
        err_msg = traceback.format_exc()
        print(f"System error: {e}")

if __name__ == "__main__":
    main()
