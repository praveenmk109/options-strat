#!/usr/bin/env python3
"""One-off backfill: fill missing buy-leg option prices for timestamps
where sell-leg data exists but buy-leg data is missing.

Usage: ./venv/bin/python backfill_buy_leg.py
"""
import sys, os, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime
from tradier_client import TradierClient
from database import init_db, save_options_hourly
from utils import format_osi
import models

DB_PATH = os.path.join(os.path.dirname(__file__), "options_history.db")
tc = TradierClient()

SYMBOL = "QQQ"
SELL_EXP = "2026-08-07"
BUY_EXP = "2026-08-14"
CUSHIONS = (5, 0, 5)


def get_timestamps_with_sell_leg():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT timestamp FROM options_hourly WHERE symbol=? AND expiry=? ORDER BY timestamp",
        (SYMBOL, SELL_EXP),
    )
    rows = [r[0] for r in c.fetchall()]
    conn.close()
    return rows


def buy_leg_option_exists(timestamp, strike, opt_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT 1 FROM options_hourly WHERE symbol=? AND timestamp=? AND expiry=? AND strike=? AND type=? LIMIT 1",
        (SYMBOL, timestamp, BUY_EXP, float(strike), opt_type),
    )
    exists = c.fetchone() is not None
    conn.close()
    return exists


def get_underlying_close(timestamp):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT close FROM underlying_hourly WHERE symbol=? AND timestamp=?", (SYMBOL, timestamp))
    row = c.fetchone()
    conn.close()
    return float(row[0]) if row else None


def get_option_mid(timestamp, expiry, strike, opt_type):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT bid, ask FROM options_hourly WHERE symbol=? AND timestamp=? AND expiry=? AND strike=? AND type=?",
        (SYMBOL, timestamp, expiry, float(strike), opt_type),
    )
    row = c.fetchone()
    conn.close()
    if row and row[0] is not None and row[1] is not None:
        return (float(row[0]) + float(row[1])) / 2.0
    return None


def fetch_historical_price(occ, day_str):
    try:
        hist = tc.get_history(occ, start=day_str, end=day_str)
        if hist:
            return float(hist[0]["close"])
    except Exception as e:
        print(f"      API error for {occ}: {e}")
    return None


def run():
    print(f"=== Backfilling {BUY_EXP} options for {SYMBOL} ===")
    print(f"  Sell expiry: {SELL_EXP}")
    print(f"  Buy expiry:  {BUY_EXP}")
    print(f"  Cushions:    {CUSHIONS}")
    print()

    init_db()

    timestamps = get_timestamps_with_sell_leg()
    print(f"Found {len(timestamps)} timestamps with sell-leg data\n")

    total_saved = 0
    processed = 0
    skipped_already = 0
    skipped_no_price = 0
    skipped_no_data = 0

    for i, ts in enumerate(timestamps, 1):
        price = get_underlying_close(ts)
        if not price:
            print(f"  [{i}/{len(timestamps)}] {ts}: no underlying price, skipping")
            skipped_no_price += 1
            continue

        atm_strike = int(round(price / 5.0) * 5)

        atm_call = get_option_mid(ts, SELL_EXP, atm_strike, "C")
        atm_put = get_option_mid(ts, SELL_EXP, atm_strike, "P")

        if atm_call is not None and atm_put is not None:
            straddle = atm_call + atm_put
        else:
            straddle = 15.0

        rounded = models.compute_rounded_cost(straddle)
        lower, middle, upper = models.compute_strikes(atm_strike, rounded, *CUSHIONS)

        needed = [
            (BUY_EXP, lower, "P"),
            (BUY_EXP, middle, "P"),
            (BUY_EXP, upper, "C"),
        ]

        # Check if all 3 already exist
        if all(buy_leg_option_exists(ts, s, t) for _, s, t in needed):
            skipped_already += 1
            continue

        day_str = ts.split()[0]
        records = []

        for exp, strike, opt_type in needed:
            if buy_leg_option_exists(ts, strike, opt_type):
                continue
            occ = format_osi(SYMBOL, exp, opt_type, strike)
            hist_price = fetch_historical_price(occ, day_str)
            if hist_price is None:
                print(f"      {occ}: no history data for {day_str}")
                continue
            records.append({
                "symbol": SYMBOL, "timestamp": ts,
                "expiry": exp, "strike": float(strike), "type": opt_type,
                "bid": hist_price, "ask": hist_price, "mid": hist_price,
                "volume": 0, "open_interest": 0,
                "implied_volatility": 0.0,
                "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0,
            })

        if records:
            save_options_hourly(records)
            total_saved += len(records)
            print(f"  [{i}/{len(timestamps)}] {ts}: saved {len(records)} records "
                  f"(atm={atm_strike}, strikes={lower}/{middle}/{upper})")
            processed += 1
        else:
            skipped_no_data += 1
            if skipped_no_data <= 3:
                print(f"  [{i}/{len(timestamps)}] {ts}: no records to save")

    print(f"\n{'=' * 50}")
    print(f"Timestamps processed:   {processed}")
    print(f"Already had all data:   {skipped_already}")
    print(f"Skipped (no price):     {skipped_no_price}")
    print(f"Skipped (no history):   {skipped_no_data}")
    print(f"Total records saved:    {total_saved}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    run()
