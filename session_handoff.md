# Session Handoff: Automated Earnings Options Advisory Bot

Two-mode advisory-only system. No order execution.

- **Daily morning**: Mon-Fri 9:30 AM CT — IV crush edge scan
- **Weekly preview**: Sun 8:00 AM CT — upcoming week's earnings calendar

## Architecture

- **`automated_system.py`**: `run_afternoon_execution()` (daily) + `run_weekly_preview()` (Sunday) — finds candidates via Tradier + yfinance, sends Discord
- **`alpaca_utils.py`**: Tradier for price/straddle/chain quotes + yfinance for earnings calendar, analyst consensus, upgrades/downgrades
- **`tradier_client.py`**: Tradier API wrapper (quotes, option chains, expirations)
- **`discord_utils.py`**: Discord messages (content, not embeds)
- **`database_manager.py`**: SQLite metadata reader
- **`db_init.py`**: Schema + seed 127 S&P 500 stocks
- **`config.py`**: .env loader
- **`.env`**: Tradier API key + Discord webhook

## Go/No-Go Decision

1. **Base edge**: `implied_move >= avg_hist_move * multiplier` (default 1.2)
2. **Consensus alignment**: recommendation_mean (1=strong buy, 5=strong sell) vs strategy direction
   - Bull Put + Buy consensus → positive alignment (easier to pass)
   - Bear Call + Buy consensus → negative alignment/harder to pass (contrarian)
3. **Adjusted multiplier**: `multiplier * (1 + 0.1 * clamp(-(rec_mean - 3), -1, 1))` — ±10% adjustment
4. **Strategy selection**: Bull Put if bull win rate >= bear win rate, else Bear Call (fallback: Bull Put)
5. **Strike selection**: straddle-based offset at 1.2x straddle price, wing width = max(1, round(straddle * 0.5))

## Candidate Filtering

- Two-pass: fast `t.calendar` for all 127 tickers → `t.earnings_dates` for session detection
- Stale candidate filter: skips stocks where `Reported EPS` is non-NaN (already reported)
- Weekend skip: Friday scans jump to Monday for BMO candidates
- yfinance retry: 2 retries with 3s delay on rate limiting

## Data Sources

- **Earnings calendar**: yfinance `t.calendar` + `t.earnings_dates` (with retry)
- **Straddle / option prices / volume / OI**: Tradier API (10s timeout)
- **Stock price**: Tradier quote endpoint
- **Analyst consensus**: yfinance `t.info`
- **Upgrades/downgrades**: yfinance `t.upgrades_downgrades`
- **Historical earnings**: `sp500_earnings_summary.csv` + `sp500_strategy_simulations.csv`

## Crontab

```text
# Weekly Preview (Sunday 8:00 AM CT)
00 08 * * 0 cd /home/ubuntu/options-strat && python3 automated_system.py --mode weekly >> weekly.log 2>&1
# Morning Advisory (9:30 AM CT, Mon-Fri)
30 09 * * 1-5 cd /home/ubuntu/options-strat && python3 automated_system.py --mode afternoon >> afternoon.log 2>&1

# Monthly Retrain (1st at 6:30 AM CT)
30 06 1 * * cd /home/ubuntu/options-strat && python3 get_sp500_earnings_prices.py && python3 simulate_sp500_strategies.py && python3 db_init.py >> retrain.log 2>&1
```

## Verification

```bash
python3 automated_system.py --mode afternoon
```

## Key Files

| File | Purpose |
|---|---|
| `automated_system.py` | Main orchestrator (daily + weekly) |
| `alpaca_utils.py` | Tradier + yfinance wrappers |
| `tradier_client.py` | Tradier API client |
| `discord_utils.py` | Discord message builder |
| `database_manager.py` | SQLite metadata reader |
| `db_init.py` | Schema + seed |
| `earnings_trading.db` | SQLite DB, 127 stocks |
| `sp500_strategy_simulations.csv` | Win rates from last retrain |
| `.env` | API keys |
