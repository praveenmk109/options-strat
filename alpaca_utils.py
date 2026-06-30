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
        exp_date = datetime.strptime(expiration_yymmdd, "%y%m%d").strftime("%Y-%m-%d")
        t = yf.Ticker(ticker)
        chain = t.option_chain(exp_date)
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

def get_recent_news(ticker, max_count=3):
    try:
        t = yf.Ticker(ticker)
        news = t.news
        if not news:
            return []
        headlines = []
        for item in news[:max_count]:
            title = item.get('title', '').strip()
            publisher = item.get('publisher', '')
            link = item.get('link', '')
            if title:
                headlines.append({'title': title, 'publisher': publisher, 'link': link})
        return headlines
    except Exception as e:
        print(f"Error fetching news for {ticker}: {e}")
        return []

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
