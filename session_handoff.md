# Session Handoff: Automated Self-Improving Options Earnings Trading Bot

This document outlines the architecture, mathematical model, codebase layout, and execution instructions for the automated options paper-trading system. The target system is designed to run on an Ubuntu VM (Oracle Cloud) and trade the options credit spreads of highly liquid S&P 500 stocks.

---

## 1. System Vision & Strategy Mechanics

The system exploits the **Implied Volatility (IV) Crush** that occurs immediately following a stock's earnings announcement. Option prices swell prior to the event (uncertainty) and collapse directly after open (certainty). 

### Go/No-Go Decision Edge
The bot queries the closest weekly At-The-Money (ATM) Straddle on Alpaca right before market close and calculates the market's expected move:
$$\text{Implied Move (\%)} \approx 0.85 \times \frac{\text{ATM Straddle Price}}{\text{Stock Price}} \times 100$$
* **Edge Requirement**: A trade is executed **only** if the current Implied Move is greater than or equal to the stock's historical average earnings move multiplied by a dynamic threshold:
$$\text{Implied Move (\%)} \ge \text{avg\_abs\_move (\%)} \times \text{dynamic\_multiplier}$$

### Self-Improving Adaptive Thresholds
The SQLite database stores a `dynamic_multiplier` for each stock (defaults to `1.5x`).
* **On Breach (Loss)**: If the post-earnings opening price gaps past the sold short strike, the stock's dynamic multiplier is increased by **+0.2** (requiring a wider safety edge for the next cycle).
* **On Success (Win)**: The multiplier decreases by **-0.05** per consecutive win (floor at 1.1x) to capture premium more aggressively during stable cycles.

### Capital Allocation & Risk Controls ($5,000 Account)
* **Maximum Risk**: Capped at 3% ($150) max loss per trade.
* **Strike Selection (5% OOTM spreads)**:
  * **Short Strike**: Set at 5% Out-Of-The-Money relative to the pre-earnings price.
  * **Spread Widths**: 
    * Stocks under $100 price: Sell **$1.00 wide** spreads (1 contract, ~$70 net risk).
    * Stocks between $100 and $250 price: Sell **$2.00 wide** spreads (1 contract, ~$130 net risk).
    * Stocks over $250 price: **Skip the trade** to prevent over-allocation.

---

## 2. File & Folder Structure

All core scripts and configs reside in the project root (`/home/ubuntu/options-strat/`):

* **`.env`**: Stores API credentials and Discord webhook URL.
* **`config.py`**: A zero-dependency script loader that parses `.env` parameters into `os.environ`.
* **`db_init.py`**: Creates the SQLite schema and seeds stock metadata with average historical moves.
* **`database_manager.py`**: Interacts with the local SQLite database (`earnings_trading.db`). Tracks skipped, open, and closed trades and updates multipliers.
* **`alpaca_utils.py`**: Wrapper for `alpaca-py`. Handles ATM Straddle price lookups, OCC symbol generation, and multi-leg order execution/liquidation.
* **`discord_utils.py`**: Formats and sends color-coded rich embeds (watchlists, fills, reviews) via Discord webhooks.
* **`automated_system.py`**: The primary daily orchestrator. Accepts `--mode morning`, `--mode afternoon`, and `--mode review` parameters.
* **`setup_scheduler.bat`**: Windows Task Scheduler helper (useful for local Windows testing).
* **`sp500_strategy_simulations.csv`**: Backtest results for the 102 highly liquid S&P 500 stocks.
* **`sp500_upcoming_earnings_calendar.csv`**: Compiled calendar of upcoming earnings matches.

---

## 3. SQLite Database Schema (`earnings_trading.db`)

* **`stocks_metadata`**:
  * `ticker` (TEXT, Primary Key)
  * `avg_abs_move` (REAL) - Historical average earnings move.
  * `dynamic_multiplier` (REAL) - Current multiplier threshold (starts at 1.5).
  * `consecutive_wins` (INTEGER) - Tracking consecutive wins for decaying.
* **`trade_log`**:
  * `id` (INTEGER, Primary Key)
  * `ticker` (TEXT), `earnings_date` (TEXT), `session` (TEXT), `strategy_type` (TEXT)
  * `short_strike_put` (REAL), `long_strike_put` (REAL), `short_strike_call` (REAL), `long_strike_call` (REAL)
  * `entry_price` (REAL), `exit_price` (REAL), `realized_open_price` (REAL), `pnl` (REAL)
  * `status` (TEXT: 'OPEN', 'CLOSED', 'SKIPPED')
  * `is_breached` (INTEGER: 0 or 1)
  * `alpaca_order_id` (TEXT), `entry_timestamp` (TEXT), `exit_timestamp` (TEXT)

---

## 4. Ubuntu VM Setup & Scheduling Instructions

### 1. Python Prerequisites
Install dependencies on the cloud VM:
```bash
pip install yfinance pandas numpy alpaca-py tabulate lxml bs4
```
### 2. Timezone Sync

The VM is set to America/Chicago (CT). If you prefer ET instead:
```bash
sudo timedatectl set-timezone America/New_York
```
Note: All crontab schedules below are in **CT** to match the current VM timezone.

### 3. Crontab Scheduling
Add the automated jobs by running `crontab -e` and appending these scheduled runs (adjust the directory path to match your VM path):

```text
# 1. Afternoon Trade Advisory (Runs 2:00 PM CT, Monday-Friday)
00 14 * * 1-5 cd /home/ubuntu/options-strat && python3 automated_system.py --mode afternoon >> afternoon.log 2>&1

# 2. Monthly Strategy Retraining (1st of month at 6:30 AM CT)
30 06 1 * * cd /home/ubuntu/options-strat && python3 get_sp500_earnings_prices.py && python3 simulate_sp500_strategies.py && python3 db_init.py >> retrain.log 2>&1
```

---

## 5. Verification Commands for the Next Session
To verify that everything is running correctly, ask the assistant to run:

1. **Test DB connection & Seeding**:
   `python db_init.py` (Reseeds/Verify DB connection).
2. **Dry-Run Watchlist Scan**:
   `python automated_system.py --mode morning` (Should scrape and check dates, sending a Discord embed watchlist).
