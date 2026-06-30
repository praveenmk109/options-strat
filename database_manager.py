import os
import sqlite3
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "earnings_trading.db")

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def migrate_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("ALTER TABLE trade_log ADD COLUMN notes TEXT")
        conn.commit()
        print("DB migration: added notes column.")
    except sqlite3.OperationalError:
        pass
    conn.close()

migrate_db()

def get_stock_metadata(ticker):
    """
    Fetches the average absolute move, dynamic multiplier, and consecutive wins for a ticker.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT avg_abs_move, dynamic_multiplier, consecutive_wins 
    FROM stocks_metadata 
    WHERE ticker = ?
    """, (ticker,))
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "avg_abs_move": row[0],
            "dynamic_multiplier": row[1],
            "consecutive_wins": row[2]
        }
    return None

def log_skipped_trade(ticker, date, session, reason):
    """
    Logs a skipped trade opportunity (e.g. no edge, stock price too high).
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().isoformat()
    cursor.execute("""
    INSERT INTO trade_log (ticker, earnings_date, session, strategy_type, status, entry_timestamp, notes)
    VALUES (?, ?, ?, 'SKIPPED', 'SKIPPED', ?, ?)
    """, (ticker, date, session, now_str, reason))
    
    conn.commit()
    conn.close()
    print(f"Logged skipped trade for {ticker} on {date}. Reason: {reason}")

def log_trade_entry(ticker, date, session, strategy_type, short_put, long_put, short_call, long_call, entry_price, order_id):
    """
    Logs a newly opened options trade.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().isoformat()
    cursor.execute("""
    INSERT INTO trade_log (
        ticker, earnings_date, session, strategy_type, 
        short_strike_put, long_strike_put, short_strike_call, long_strike_call, 
        entry_price, status, alpaca_order_id, entry_timestamp
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?, ?)
    """, (ticker, date, session, strategy_type, short_put, long_put, short_call, long_call, entry_price, order_id, now_str))
    
    conn.commit()
    conn.close()
    print(f"Logged trade entry for {ticker} (Order ID: {order_id})")

def get_open_trades():
    """
    Returns a list of all currently open trades.
    """
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM trade_log WHERE status = 'OPEN'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def log_trade_exit(trade_id, ticker, exit_price, realized_open_price, pnl, is_breached):
    """
    Logs the exit of an open options trade and updates the threshold multiplier.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    now_str = datetime.now().isoformat()
    cursor.execute("""
    UPDATE trade_log
    SET status = 'CLOSED',
        exit_price = ?,
        realized_open_price = ?,
        pnl = ?,
        is_breached = ?,
        exit_timestamp = ?
    WHERE id = ?
    """, (exit_price, realized_open_price, pnl, 1 if is_breached else 0, now_str, trade_id))
    
    conn.commit()
    conn.close()
    print(f"Logged trade exit for {ticker} (Trade ID: {trade_id}). PnL: ${pnl:.2f}, Breached: {is_breached}")
    
    # Run the adaptive threshold optimizer
    update_multiplier_post_trade(ticker, is_breached)

def update_multiplier_post_trade(ticker, is_breached):
    """
    Adaptive Threshold Optimizer logic:
    - If trade was breached: increase multiplier by +0.2 and reset wins to 0.
    - If trade succeeded: decay multiplier by -0.05 (floor at 1.1) and increment wins.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current multiplier and wins
    cursor.execute("""
    SELECT dynamic_multiplier, consecutive_wins 
    FROM stocks_metadata 
    WHERE ticker = ?
    """, (ticker,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return
        
    current_mult, current_wins = row
    
    if is_breached:
        new_mult = round(current_mult + 0.2, 2)
        new_wins = 0
        print(f"[THRESHOLD ADAPTATION] {ticker} breached! Increasing multiplier from {current_mult} to {new_mult}")
    else:
        new_mult = round(max(1.1, current_mult - 0.05), 2)
        new_wins = current_wins + 1
        print(f"[THRESHOLD ADAPTATION] {ticker} trade succeeded. Decaying multiplier from {current_mult} to {new_mult} (Wins: {new_wins})")
        
    # Update stocks_metadata
    cursor.execute("""
    UPDATE stocks_metadata
    SET dynamic_multiplier = ?,
        consecutive_wins = ?
    WHERE ticker = ?
    """, (new_mult, new_wins, ticker))
    
    conn.commit()
    conn.close()
