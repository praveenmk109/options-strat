import os
import sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "earnings_trading.db")

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def get_stock_metadata(ticker):
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
