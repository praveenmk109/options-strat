import os
import sqlite3
import pandas as pd

DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "options_history.db")


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS underlying_hourly (
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            close REAL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vol_index_hourly (
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            close REAL,
            PRIMARY KEY (symbol, timestamp)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS options_hourly (
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            expiry TEXT NOT NULL,
            strike REAL NOT NULL,
            type TEXT NOT NULL,
            bid REAL,
            ask REAL,
            mid REAL,
            volume INTEGER DEFAULT 0,
            open_interest INTEGER DEFAULT 0,
            implied_volatility REAL,
            delta REAL,
            gamma REAL,
            theta REAL,
            vega REAL,
            PRIMARY KEY (symbol, timestamp, expiry, strike, type)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS strategy_scores (
            symbol TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            expiry_short TEXT NOT NULL,
            expiry_long TEXT NOT NULL,
            score REAL,
            label TEXT,
            PRIMARY KEY (symbol, timestamp, expiry_short, expiry_long)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT DEFAULT (datetime('now')),
            symbol TEXT NOT NULL DEFAULT 'QQQ',
            score REAL,
            label TEXT,
            total_cost REAL,
            vix REAL,
            underlying_price REAL,
            iv_ratio REAL,
            iv_percentile REAL,
            sell_expiry TEXT,
            buy_expiry TEXT,
            lower_strike REAL,
            middle_strike REAL,
            upper_strike REAL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_throttle (
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            PRIMARY KEY (symbol, date)
        )
    """)

    conn.commit()
    conn.close()


def clear_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    for table in ["underlying_hourly", "vol_index_hourly", "options_hourly", "strategy_scores", "alerts", "alert_throttle"]:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    conn.commit()
    conn.close()


def get_latest_timestamps():
    conn = get_db_connection()
    cursor = conn.cursor()
    result = {}

    cursor.execute("SELECT symbol, MAX(timestamp) FROM underlying_hourly GROUP BY symbol")
    for row in cursor.fetchall():
        result[f"underlying_hourly_{row['symbol']}"] = row[1]

    cursor.execute("SELECT symbol, MAX(timestamp) FROM vol_index_hourly GROUP BY symbol")
    for row in cursor.fetchall():
        result[f"vol_index_hourly_{row['symbol']}"] = row[1]

    cursor.execute("SELECT symbol, MAX(timestamp) FROM options_hourly GROUP BY symbol")
    for row in cursor.fetchall():
        result[f"options_hourly_{row['symbol']}"] = row[1]

    conn.close()
    return result


def save_underlying_hourly(records):
    if not records:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO underlying_hourly (symbol, timestamp, close)
        VALUES (:symbol, :timestamp, :close)
    """, records)
    conn.commit()
    conn.close()


def save_vol_index_hourly(records):
    if not records:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO vol_index_hourly (symbol, timestamp, close)
        VALUES (:symbol, :timestamp, :close)
    """, records)
    conn.commit()
    conn.close()


def save_options_hourly(records):
    if not records:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO options_hourly
        (symbol, timestamp, expiry, strike, type, bid, ask, mid, volume, open_interest, implied_volatility, delta, gamma, theta, vega)
        VALUES (:symbol, :timestamp, :expiry, :strike, :type, :bid, :ask, :mid, :volume, :open_interest, :implied_volatility, :delta, :gamma, :theta, :vega)
    """, records)
    conn.commit()
    conn.close()


def save_strategy_scores(records):
    if not records:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO strategy_scores (symbol, timestamp, expiry_short, expiry_long, score, label)
        VALUES (:symbol, :timestamp, :expiry_short, :expiry_long, :score, :label)
    """, records)
    conn.commit()
    conn.close()


def load_strategy_scores(expiry_short, expiry_long, symbol='QQQ', min_timestamp=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if min_timestamp:
        cursor.execute("""
            SELECT timestamp, score, label FROM strategy_scores
            WHERE symbol = ? AND expiry_short = ? AND expiry_long = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (symbol, expiry_short, expiry_long, min_timestamp))
    else:
        cursor.execute("""
            SELECT timestamp, score, label FROM strategy_scores
            WHERE symbol = ? AND expiry_short = ? AND expiry_long = ?
            ORDER BY timestamp ASC
        """, (symbol, expiry_short, expiry_long))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def save_alerts(records):
    if not records:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO alerts (symbol, score, label, total_cost, vix, underlying_price, iv_ratio, iv_percentile, sell_expiry, buy_expiry, lower_strike, middle_strike, upper_strike)
        VALUES (:symbol, :score, :label, :total_cost, :vix, :underlying_price, :iv_ratio, :iv_percentile, :sell_expiry, :buy_expiry, :lower_strike, :middle_strike, :upper_strike)
    """, records)
    conn.commit()
    conn.close()


def get_recent_alerts(limit=20, symbol=None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if symbol:
        cursor.execute("SELECT * FROM alerts WHERE symbol = ? ORDER BY id DESC LIMIT ?", (symbol, limit))
    else:
        cursor.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ── Raw data queries (used by pipeline) ─────────────────


def get_underlying_hourly(symbol: str) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, close FROM underlying_hourly WHERE symbol = ? ORDER BY timestamp ASC", (symbol,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_vol_index_hourly(symbol: str) -> list[dict]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT timestamp, close FROM vol_index_hourly WHERE symbol = ? ORDER BY timestamp ASC", (symbol,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_options_for_strategy(symbol: str, sell_expiry: str, buy_expiry: str, min_timestamp: str):
    conn = get_db_connection()
    df = pd.read_sql_query("""
        SELECT timestamp, expiry, strike, type, mid, implied_volatility
        FROM options_hourly
        WHERE symbol = ? AND expiry IN (?, ?) AND timestamp >= ?
    """, conn, params=(symbol, sell_expiry, buy_expiry, min_timestamp))
    conn.close()
    return df


# ── Alert throttle (DB-based, survives /tmp cleanup) ────


def is_alert_throttled(symbol: str, date_str: str) -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM alert_throttle WHERE symbol = ? AND date = ?", (symbol, date_str))
    result = cursor.fetchone() is not None
    conn.close()
    return result


def set_alert_throttle(symbol: str, date_str: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO alert_throttle (symbol, date) VALUES (?, ?)", (symbol, date_str))
    conn.commit()
    conn.close()


def clear_alert_throttle(symbol: str, date_str: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alert_throttle WHERE symbol = ? AND date = ?", (symbol, date_str))
    conn.commit()
    conn.close()


def prune_old_options(days=60):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM options_hourly WHERE timestamp < datetime('now', ? || ' days')", (f"-{days}",))
    conn.commit()
    conn.close()
