import config
import os
from datetime import datetime, date
import yfinance as yf
import pandas as pd
from tradier_client import TradierClient

def get_current_stock_price(ticker):
    try:
        tc = TradierClient()
        quote = tc.get_quote(ticker, greeks=False)
        if not quote:
            return None
        last = quote.get('last')
        if last is not None and float(last) > 0:
            return float(last)
        bid = quote.get('bid')
        ask = quote.get('ask')
        if bid is not None and ask is not None and float(bid) > 0 and float(ask) > 0:
            return (float(bid) + float(ask)) / 2
        return None
    except Exception as e:
        print(f"Error fetching stock price for {ticker}: {e}")
        return None

def get_atm_straddle_implied_move(ticker, current_price):
    tc = TradierClient()
    expirations = tc.get_option_expirations(ticker)
    if not expirations:
        print(f"No option expirations from Tradier for {ticker}")
        return None

    today_str = date.today().isoformat()
    future = sorted([e for e in expirations if e >= today_str])
    if not future:
        print(f"No future expirations from Tradier for {ticker}")
        return None
    target_exp = future[0]

    chain = tc.get_option_chain(ticker, target_exp, greeks=False)
    if not chain:
        print(f"Empty option chain from Tradier for {ticker} {target_exp}")
        return None

    calls = [o for o in chain if o.get('option_type') == 'call']
    puts = [o for o in chain if o.get('option_type') == 'put']
    if not calls or not puts:
        print(f"Missing call/put in Tradier chain for {ticker}")
        return None

    atm_call = min(calls, key=lambda o: abs(float(o['strike']) - current_price))
    atm_put = min(puts, key=lambda o: abs(float(o['strike']) - current_price))

    call_bid = float(atm_call.get('bid') or 0)
    call_ask = float(atm_call.get('ask') or 0)
    put_bid = float(atm_put.get('bid') or 0)
    put_ask = float(atm_put.get('ask') or 0)

    call_mid = (call_bid + call_ask) / 2 if call_bid > 0 and call_ask > 0 else None
    put_mid = (put_bid + put_ask) / 2 if put_bid > 0 and put_ask > 0 else None

    if call_mid is None and put_mid is None:
        print(f"No valid mid prices for {ticker} ATM straddle via Tradier")
        return None
    if call_mid is None:
        call_mid = float(atm_call.get('last') or 0)
    if put_mid is None:
        put_mid = float(atm_put.get('last') or 0)

    straddle_price = call_mid + put_mid
    if straddle_price <= 0:
        print(f"Zero/negative straddle price ({straddle_price}) for {ticker}")
        return None
    implied_move = (0.85 * straddle_price / current_price) * 100

    exp_ymd = datetime.strptime(target_exp, "%Y-%m-%d").strftime("%y%m%d")
    return implied_move, straddle_price, exp_ymd, float(atm_call['strike']), float(atm_put['strike'])

def get_option_volume_and_oi(ticker, expiration_yymmdd, call_strike, put_strike):
    try:
        exp_date = datetime.strptime(expiration_yymmdd, "%y%m%d").strftime("%Y-%m-%d")
        tc = TradierClient()
        chain = tc.get_option_chain(ticker, exp_date, greeks=False)
        if not chain:
            print(f"Empty Tradier chain for {ticker} {exp_date}")
            return None, None, None, None

        calls = [o for o in chain if o.get('option_type') == 'call']
        puts = [o for o in chain if o.get('option_type') == 'put']

        def find_closest(opt_list, target_strike):
            if not opt_list:
                return None, None
            closest = min(opt_list, key=lambda o: abs(float(o['strike']) - target_strike))
            raw_vol = closest.get('volume')
            raw_oi = closest.get('open_interest')
            vol = int(raw_vol) if raw_vol is not None and int(raw_vol) > 0 else None
            oi = int(raw_oi) if raw_oi is not None and int(raw_oi) > 0 else None
            return vol, oi

        cv, coi = find_closest(calls, call_strike)
        pv, poi = find_closest(puts, put_strike)
        return cv, coi, pv, poi
    except Exception as e:
        print(f"Error fetching option volume for {ticker}: {e}")
        return None, None, None, None

def get_option_price(ticker, expiration_yymmdd, strike, option_type):
    try:
        exp_date = datetime.strptime(expiration_yymmdd, "%y%m%d").strftime("%Y-%m-%d")
        tc = TradierClient()
        chain = tc.get_option_chain(ticker, exp_date, greeks=False)
        if not chain:
            print(f"Empty Tradier chain for {ticker} {exp_date}")
            return None
        opts = [o for o in chain if o.get('option_type') == option_type.lower()]
        if not opts:
            print(f"No {option_type} options in Tradier chain for {ticker}")
            return None
        closest = min(opts, key=lambda o: abs(float(o['strike']) - strike))
        bid = float(closest.get('bid') or 0)
        ask = float(closest.get('ask') or 0)
        if bid > 0 and ask > 0:
            return (bid + ask) / 2
        last = closest.get('last')
        return float(last) if last is not None else None
    except Exception as e:
        print(f"Error fetching option price for {ticker}: {e}")
        return None

def get_analyst_calls(ticker, max_count=3):
    """Get most recent analyst upgrades/downgrades/price target changes."""
    try:
        t = yf.Ticker(ticker)
        ud = t.upgrades_downgrades
        if ud is None or ud.empty:
            return []
        recent = ud.head(max_count)
        calls = []
        for idx, row in recent.iterrows():
            firm = row.get('Firm', '')
            action = row.get('Action', '')
            to_grade = row.get('ToGrade', '')
            curr_pt = row.get('currentPriceTarget', None)
            prior_pt = row.get('priorPriceTarget', None)
            date_str = idx.strftime('%b %d') if hasattr(idx, 'strftime') else str(idx)
            parts = [f"**{firm}**"]
            if action and action.lower() in ('up', 'down'):
                parts.append(action.title())
            if to_grade:
                parts.append(f"→ {to_grade}")
            if curr_pt and curr_pt > 0:
                pt_str = f"PT ${curr_pt:.0f}"
                if prior_pt and prior_pt > 0:
                    pt_str += f" (from ${prior_pt:.0f})"
                parts.append(pt_str)
            calls.append({"summary": " | ".join(parts), "date": date_str})
        return calls
    except Exception as e:
        print(f"Error fetching analyst calls for {ticker}: {e}")
        return []

def get_analyst_consensus(ticker):
    """Fetch consensus price target and recommendation via yfinance."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        return {
            "target_mean": info.get('targetMeanPrice'),
            "target_high": info.get('targetHighPrice'),
            "target_low": info.get('targetLowPrice'),
            "recommendation": info.get('recommendationKey'),
            "recommendation_mean": info.get('recommendationMean'),
            "analyst_count": info.get('numberOfAnalystOpinions'),
        }
    except Exception as e:
        print(f"Error fetching analyst consensus for {ticker}: {e}")
        return {"target_mean": None, "target_high": None, "target_low": None,
                "recommendation": None, "recommendation_mean": None, "analyst_count": None}


