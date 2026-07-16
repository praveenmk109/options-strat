import sqlite3
import pandas as pd
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(SCRIPT_DIR, "earnings_trading.db")
SIMS_CSV = os.path.join(SCRIPT_DIR, "sp500_strategy_simulations.csv")

def init_db():
    print(f"Initializing SQLite database at {DB_PATH}...")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create stocks_metadata table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stocks_metadata (
        ticker TEXT PRIMARY KEY,
        avg_abs_move REAL NOT NULL,
        dynamic_multiplier REAL NOT NULL DEFAULT 1.2,
        consecutive_wins INTEGER NOT NULL DEFAULT 0
    )
    """)
    
    # Create trade_log table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT NOT NULL,
        earnings_date TEXT NOT NULL,
        session TEXT NOT NULL,
        strategy_type TEXT NOT NULL,
        short_strike_put REAL,
        long_strike_put REAL,
        short_strike_call REAL,
        long_strike_call REAL,
        entry_price REAL,
        exit_price REAL,
        realized_open_price REAL,
        pnl REAL,
        status TEXT NOT NULL, -- 'OPEN', 'CLOSED', 'SKIPPED'
        is_breached INTEGER DEFAULT 0,
        alpaca_order_id TEXT,
        entry_timestamp TEXT,
        exit_timestamp TEXT,
        notes TEXT
    )
    """)
    
    conn.commit()
    print("Database tables created successfully.")
    return conn, cursor

def seed_data(conn, cursor):
    if not os.path.exists(SIMS_CSV):
        print(f"[ERROR] Simulation file {SIMS_CSV} not found! Cannot seed database.")
        return
        
    print(f"Loading simulation stats from {SIMS_CSV}...")
    df = pd.read_csv(SIMS_CSV)
    
    inserted_count = 0
    for _, row in df.iterrows():
        ticker = row['Ticker']
        avg_move = row['avg_abs_move']
        
        # Insert or ignore to avoid duplicates on re-runs
        cursor.execute("""
        INSERT OR IGNORE INTO stocks_metadata (ticker, avg_abs_move, dynamic_multiplier, consecutive_wins)
        VALUES (?, ?, 1.2, 0)
        """, (ticker, avg_move))
        
        # If it was already there, update avg_abs_move in case it changed
        cursor.execute("""
        UPDATE stocks_metadata 
        SET avg_abs_move = ? 
        WHERE ticker = ?
        """, (avg_move, ticker))
        
        inserted_count += 1
        
    conn.commit()
    print(f"Successfully seeded {inserted_count} tickers in stocks_metadata.")

def main():
    conn, cursor = init_db()
    seed_data(conn, cursor)
    conn.close()
    print("Database setup complete.")

if __name__ == "__main__":
    main()
