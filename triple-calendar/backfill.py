import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytz
import yfinance as yf
from tradier_client import TradierClient
from database import init_db, save_options_hourly, save_underlying_hourly, save_vol_index_hourly
from utils import format_osi

tc = TradierClient()
TZ_ET = pytz.timezone("America/New_York")
TODAY = date.today()


def get_underlying_vol_history(symbol, days=14):
    vol_ticker = {"QQQ": "^VXN", "SPY": "^VIX"}[symbol]
    print(f"Fetching {symbol} and {vol_ticker} daily history from yfinance...")
    underlying = yf.Ticker(symbol).history(period=f"{days+5}d")
    vol = yf.Ticker(vol_ticker).history(period=f"{days+5}d")
    underlying_records = []
    vol_records = []
    for ts, row in underlying.iterrows():
        d = ts.strftime("%Y-%m-%d")
        underlying_records.append({"symbol": symbol, "timestamp": f"{d} 16:00", "close": float(row["Close"])})
    for ts, row in vol.iterrows():
        d = ts.strftime("%Y-%m-%d")
        vol_records.append({"symbol": symbol, "timestamp": f"{d} 16:00", "close": float(row["Close"])})
    return underlying_records, vol_records


def get_straddle_for_day(price, expiry, day_str, symbol):
    atm_strike = int(round(price / 5.0) * 5)
    call_occ = format_osi(symbol, expiry, "C", atm_strike)
    put_occ = format_osi(symbol, expiry, "P", atm_strike)
    call_hist = tc.get_history(call_occ, start=day_str, end=day_str)
    put_hist = tc.get_history(put_occ, start=day_str, end=day_str)
    call_close = float(call_hist[0]["close"]) if call_hist else None
    put_close = float(put_hist[0]["close"]) if put_hist else None
    return call_close, put_close, atm_strike


def get_option_history(occ, day_str):
    hist = tc.get_history(occ, start=day_str, end=day_str)
    if hist:
        return float(hist[0]["close"])
    return None


def backfill_historical_options(underlying_records, sell_expiry, buy_expiry, symbol, cushion_l=5, cushion_m=0, cushion_u=5):
    opt_records = []
    tasks = []
    executor = ThreadPoolExecutor(max_workers=10)

    day_map = {}

    for qr in underlying_records:
        ts = qr["timestamp"]
        day_str = ts.split()[0]
        close = qr["close"]

        if day_str >= TODAY.isoformat():
            continue

        def do_day(ds, qc, ts_s):
            call_c, put_c, atm = get_straddle_for_day(qc, sell_expiry, ds, symbol)
            if call_c is None or put_c is None:
                return None
            straddle = call_c + put_c
            rounded_cost = max(5, int(round(straddle / 5.0) * 5))
            lower = int(atm - (rounded_cost + cushion_l))
            middle = int(atm + cushion_m)
            upper = int(atm + (rounded_cost + cushion_u))

            leg_occs = [
                format_osi(symbol, sell_expiry, "C", atm),
                format_osi(symbol, sell_expiry, "P", atm),
                format_osi(symbol, sell_expiry, "P", lower),
                format_osi(symbol, buy_expiry, "P", lower),
                format_osi(symbol, sell_expiry, "P", middle),
                format_osi(symbol, buy_expiry, "P", middle),
                format_osi(symbol, sell_expiry, "C", upper),
                format_osi(symbol, buy_expiry, "C", upper),
            ]

            leg_prices = {}
            for occ in leg_occs:
                p = get_option_history(occ, ds)
                if p is not None:
                    leg_prices[occ] = p

            return {
                "timestamp": ts_s,
                "day": ds,
                "atm_strike": atm,
                "straddle": straddle,
                "lower": lower, "middle": middle, "upper": upper,
                "leg_prices": leg_prices,
            }

        tasks.append(executor.submit(do_day, day_str, close, ts))

    for ft in as_completed(tasks):
        try:
            result = ft.result()
        except Exception:
            continue
        if result is None:
            continue

        ts = result["timestamp"]
        day = result["day"]
        leg_prices = result["leg_prices"]

        atm = result["atm_strike"]
        strikes_info = [
            (sell_expiry, atm, "C"),
            (sell_expiry, atm, "P"),
            (sell_expiry, result["lower"], "P"),
            (buy_expiry, result["lower"], "P"),
            (sell_expiry, result["middle"], "P"),
            (buy_expiry, result["middle"], "P"),
            (sell_expiry, result["upper"], "C"),
            (buy_expiry, result["upper"], "C"),
        ]
        for exp, strike, opt_type in strikes_info:
            occ = format_osi(symbol, exp, opt_type, strike)
            price = leg_prices.get(occ)
            if price is not None:
                opt_records.append({
                    "symbol": symbol,
                    "timestamp": ts,
                    "expiry": exp,
                    "strike": float(strike),
                    "type": opt_type,
                    "bid": price, "ask": price, "mid": price,
                    "volume": 0, "open_interest": 0,
                    "implied_volatility": 0.0,
                    "delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0,
                })

    executor.shutdown()
    return opt_records


def find_expiries(expiration_dates):
    target_sell = TODAY + timedelta(days=21)
    target_buy = TODAY + timedelta(days=28)
    sell_expiry = buy_expiry = None
    for e in expiration_dates:
        e_date = datetime.strptime(e, "%Y-%m-%d").date()
        if not sell_expiry and e_date >= target_sell:
            sell_expiry = e
        if not buy_expiry and e_date >= target_buy:
            buy_expiry = e
    return sell_expiry, buy_expiry


def run():
    print("=== Backfill: historical option prices ===")

    init_db()

    for symbol in ['QQQ', 'SPY']:
        print(f"\n--- Processing {symbol} ---")

        underlying_records, vol_records = get_underlying_vol_history(symbol, days=14)
        print(f"  {symbol}: {len(underlying_records)} days, vol: {len(vol_records)} days")

        save_underlying_hourly(underlying_records)
        save_vol_index_hourly(vol_records)

        exps = tc.get_option_expirations(symbol)
        if not exps:
            print(f"  No expirations found for {symbol}")
            continue

        sell_expiry, buy_expiry = find_expiries(exps)
        if not sell_expiry or not buy_expiry:
            print(f"  Could not find suitable expiries for {symbol}")
            continue

        print(f"  Sell expiry: {sell_expiry}, Buy expiry: {buy_expiry}")

        opt_records = backfill_historical_options(underlying_records, sell_expiry, buy_expiry, symbol)

        if opt_records:
            save_options_hourly(opt_records)
            print(f"  Saved {len(opt_records)} historical option records for {symbol}")
        else:
            print(f"  No option records saved for {symbol}")

    print("=== Backfill complete ===")


if __name__ == "__main__":
    run()
