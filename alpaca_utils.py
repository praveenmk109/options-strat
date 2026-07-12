import config
import os
from datetime import datetime, date
import yfinance as yf
import pandas as pd
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest, OptionLegRequest, MarketOrderRequest
from alpaca.trading.enums import AssetStatus, OrderClass, OrderSide, TimeInForce
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionLatestQuoteRequest

API_KEY = os.environ.get("APCA_API_KEY_ID", "YOUR_API_KEY")
API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "YOUR_API_SECRET")

def get_trading_client():
    return TradingClient(api_key=API_KEY, secret_key=API_SECRET, paper=True)

def get_option_data_client():
    return OptionHistoricalDataClient(api_key=API_KEY, secret_key=API_SECRET)

def get_current_stock_price(ticker):
    """
    Fetches the current stock price using yfinance.
    """
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="1d")
        if not hist.empty:
            return float(hist['Close'].iloc[-1])
    except Exception as e:
        print(f"Error fetching stock price for {ticker}: {e}")
    return None

def get_atm_straddle_implied_move(ticker, current_price):
    """
    Finds the closest expiration option chain, identifies the ATM Call/Put strikes,
    fetches their quotes, and calculates the implied move percentage.
    """
    if API_KEY == "YOUR_API_KEY":
        # Return fallback value for dry-running without API credentials
        print("[DRY-RUN] No credentials. Returning mock implied move of 4.5% for straddle.")
        return 4.5, current_price * 0.05, "260710", round(current_price), round(current_price)
        
    trading_client = get_trading_client()
    data_client = get_option_data_client()
    
    try:
        # 1. Fetch active option contracts
        req = GetOptionContractsRequest(
            underlying_symbol=[ticker],
            status=AssetStatus.ACTIVE
        )
        res = trading_client.get_option_contracts(req)
        contracts = res.option_contracts
        
        if not contracts:
            print(f"No option contracts found for {ticker}")
            return None
            
        # 2. Extract unique future expiration dates
        today = date.today()
        expirations = []
        for c in contracts:
            c_exp = c.expiration_date
            if isinstance(c_exp, str):
                c_exp_date = datetime.strptime(c_exp, "%Y-%m-%d").date()
            else:
                c_exp_date = c_exp
                
            if c_exp_date >= today:
                expirations.append(c_exp_date)
                
        if not expirations:
            print(f"No future expirations found for {ticker}")
            return None
            
        target_exp = min(expirations)
        target_exp_str = target_exp.strftime("%Y-%m-%d")
        
        # 3. Filter contracts for target expiration
        exp_contracts = []
        for c in contracts:
            c_exp = c.expiration_date
            if isinstance(c_exp, str):
                c_exp_date = datetime.strptime(c_exp, "%Y-%m-%d").date()
            else:
                c_exp_date = c_exp
                
            if c_exp_date == target_exp:
                exp_contracts.append(c)
                
        # 4. Find ATM Call and ATM Put
        calls = [c for c in exp_contracts if "call" in str(c.type).lower()]
        puts = [c for c in exp_contracts if "put" in str(c.type).lower()]
        
        if not calls or not puts:
            print(f"Missing Call or Put contracts for {ticker} on {target_exp_str}")
            return None
            
        atm_call = min(calls, key=lambda c: abs(c.strike_price - current_price))
        atm_put = min(puts, key=lambda c: abs(c.strike_price - current_price))
        
        call_symbol = atm_call.symbol
        put_symbol = atm_put.symbol
        
        # 5. Fetch quotes for both contracts
        quote_req = OptionLatestQuoteRequest(symbol_or_symbols=[call_symbol, put_symbol])
        quotes = data_client.get_option_latest_quote(quote_req)
        
        call_quote = quotes.get(call_symbol)
        put_quote = quotes.get(put_symbol)
        
        if not call_quote or not put_quote:
            print(f"Failed to fetch quotes for straddle legs on {ticker}")
            return None
            
        # Calc mid-prices
        call_mid = (call_quote.bid_price + call_quote.ask_price) / 2.0
        put_mid = (put_quote.bid_price + put_quote.ask_price) / 2.0
        straddle_price = call_mid + put_mid
        
        # Calculate implied move: 0.85 * (straddle_price / current_price) * 100
        implied_move = (0.85 * straddle_price / current_price) * 100
        
        return implied_move, straddle_price, target_exp.strftime("%y%m%d"), atm_call.strike_price, atm_put.strike_price
        
    except Exception as e:
        print(f"Error calculating straddle implied move for {ticker}: {e}")
        return None

def get_option_volume_and_oi(ticker, expiration_yymmdd, call_strike, put_strike):
    try:
        exp_date_str = datetime.strptime(expiration_yymmdd, "%y%m%d").strftime("%Y-%m-%d")
        t = yf.Ticker(ticker)
        available = t.options
        if exp_date_str not in available:
            target = datetime.strptime(expiration_yymmdd, "%y%m%d").date()
            future = [d for d in available if datetime.strptime(d, '%Y-%m-%d').date() >= target]
            if not future:
                return None, None, None, None
            exp_date_str = future[0]
        chain = t.option_chain(exp_date_str)
        calls = chain.calls
        puts = chain.puts

        def extract(row, col):
            val = row[col].values[0] if col in row.columns else None
            return int(val) if val is not None and not (isinstance(val, float) and pd.isna(val)) else None

        call_row = calls.iloc[(calls['strike'] - call_strike).abs().argsort()[:1]]
        put_row = puts.iloc[(puts['strike'] - put_strike).abs().argsort()[:1]]
        return (
            extract(call_row, 'volume'), extract(call_row, 'openInterest'),
            extract(put_row, 'volume'), extract(put_row, 'openInterest'),
        )
    except Exception as e:
        print(f"Error fetching option volume for {ticker}: {e}")
        return None, None, None, None

def get_option_price(ticker, expiration_yymmdd, strike, option_type):
    try:
        exp_date = datetime.strptime(expiration_yymmdd, "%y%m%d").strftime("%Y-%m-%d")
        t = yf.Ticker(ticker)
        avail = t.options
        if exp_date not in avail:
            target = datetime.strptime(expiration_yymmdd, "%y%m%d").date()
            future = [d for d in avail if datetime.strptime(d, '%Y-%m-%d').date() >= target]
            if not future:
                return None
            exp_date = future[0]
        chain = t.option_chain(exp_date)
        df = chain.calls if option_type == "call" else chain.puts
        row = df.iloc[(df['strike'] - strike).abs().argsort()[:1]]
        bid = row['bid'].values[0]
        ask = row['ask'].values[0]
        if pd.isna(bid) and pd.isna(ask):
            mid = row['lastPrice'].values[0]
            return None if pd.isna(mid) else float(mid)
        bid = 0 if pd.isna(bid) else float(bid)
        ask = 0 if pd.isna(ask) else float(ask)
        return (bid + ask) / 2
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
    """Fetch consensus price target, recommendation, and rating trend via yfinance (free, no rate limit)."""
    try:
        t = yf.Ticker(ticker)
        info = t.info
        consensus = {
            "target_mean": info.get('targetMeanPrice'),
            "target_high": info.get('targetHighPrice'),
            "target_low": info.get('targetLowPrice'),
            "recommendation": info.get('recommendationKey'),
            "recommendation_mean": info.get('recommendationMean'),
            "analyst_count": info.get('numberOfAnalystOpinions'),
        }
        # Rating trend from recommendations_summary (0m, -1m, -2m, -3m)
        trend = []
        try:
            rs = t.recommendations_summary
            if rs is not None and not rs.empty:
                for idx, row in rs.iterrows():
                    trend.append({
                        "period": idx,
                        "strong_buy": int(row.get('strongBuy', 0)),
                        "buy": int(row.get('buy', 0)),
                        "hold": int(row.get('hold', 0)),
                        "sell": int(row.get('sell', 0)),
                        "strong_sell": int(row.get('strongSell', 0)),
                    })
        except Exception:
            pass
        return consensus, trend
    except Exception as e:
        print(f"Error fetching analyst consensus for {ticker}: {e}")
        return {"target_mean": None, "target_high": None, "target_low": None,
                "recommendation": None, "recommendation_mean": None, "analyst_count": None}, []

def find_option_contract(ticker, expiration_yymmdd, option_type, strike):
    """
    Search Alpaca for the exact OCC option symbol based on parameters.
    """
    trading_client = get_trading_client()
    try:
        # Standardize expiration date format to YYYY-MM-DD
        exp_date_obj = datetime.strptime(expiration_yymmdd, "%y%m%d").date()
        exp_date_str = exp_date_obj.strftime("%Y-%m-%d")
        
        req = GetOptionContractsRequest(
            underlying_symbol=[ticker],
            status=AssetStatus.ACTIVE,
            expiration_date=exp_date_str
        )
        res = trading_client.get_option_contracts(req)
        
        # Filter by option type, then find closest matching strike
        matching = [c for c in res.option_contracts if option_type.lower() in str(c.type).lower()]
        if matching:
            closest = min(matching, key=lambda c: abs(c.strike_price - strike))
            return closest.symbol
    except Exception as e:
        print(f"Error finding option contract {ticker} {expiration_yymmdd} {option_type} {strike}: {e}")
    return None

def submit_mleg_order(order_legs, qty=1):
    """
    Submits a multi-leg market order on Alpaca.
    """
    if API_KEY == "YOUR_API_KEY":
        print("[DRY-RUN] No credentials. Returning mock order ID: 'order-123456'")
        return "order-123456"
        
    trading_client = get_trading_client()
    try:
        # Market Multi-Leg Order
        mleg_order = MarketOrderRequest(
            qty=qty,
            order_class=OrderClass.MLEG,
            time_in_force=TimeInForce.DAY,
            legs=order_legs
        )
        
        order = trading_client.submit_order(order_data=mleg_order)
        return order.id
    except Exception as e:
        print(f"Failed to submit multi-leg order: {e}")
        return None
