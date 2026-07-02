# Session Handoff: Automated Earnings Options Advisory Bot

Single-mode advisory-only system. No order execution. Runs at 2:00 PM CT daily.

## Architecture

- **`automated_system.py`**: `run_afternoon_execution()` — finds AMC/BMO candidates, fetches straddle data, analyst consensus, upgrades, volume/OI, EPS, sends Discord advisory
- **`alpaca_utils.py`**: Alpaca price/straddle quotes + yfinance for upgrades/downgrades, analyst consensus, options volume/OI
- **`discord_utils.py`**: Single-embed advisory message (no embed fields — select-all copyable)
- **`database_manager.py`**: SQLite CRUD (advisory-only, no trades logged)
- **`db_init.py`**: Schema + seed 100 S&P 500 stocks
- **`config.py`**: .env loader
- **`.env`**: Alpaca keys ($53K paper, from option-wheel) + Discord webhook

## Go/No-Go Decision

1. **Base edge**: `implied_move >= avg_hist_move * multiplier` (multiplier defaults to 1.5)
2. **Consensus alignment**: recommendation_mean (1=strong buy, 5=strong sell) vs strategy direction
   - Bull Put + Buy → positive alignment (easier to pass)
   - Bear Call + Buy → negative alignment/harder to pass (contrarian)
3. **Adjusted multiplier**: `multiplier * (1 - alignment * 0.2)` — ±20% adjustment
4. **Badge**: "✅ Go" (aligned/neutral) or "⚠️ Go (Contrarian)"

## Data Sources

- **Earnings calendar**: yfinance `t.calendar` (fast, no rate limit) + `t.earnings_dates` (scrape) for subset
- **Straddle**: Alpaca option quotes
- **Analyst consensus (free)**: yfinance `t.info` (target price, recommendation) + `t.recommendations_summary` (rating trend)
- **Upgrades/downgrades**: yfinance `t.upgrades_downgrades`
- **Options chain**: yfinance for volume/OI
- **EPS data**: yfinance `earnings_dates` DataFrame

## Crontab

```text
# Afternoon Advisory (2:00 PM CT, Mon-Fri)
00 14 * * 1-5 cd /home/ubuntu/options-strat && python3 automated_system.py --mode afternoon >> afternoon.log 2>&1

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
| `automated_system.py` | Main orchestrator (287 lines) |
| `alpaca_utils.py` | Alpaca + yfinance wrappers (256 lines) |
| `discord_utils.py` | Discord embed builder (193 lines) |
| `database_manager.py` | SQLite CRUD |
| `db_init.py` | Schema + seed |
| `earnings_trading.db` | SQLite DB, 100 stocks |
| `sp500_strategy_simulations.csv` | Win rates from last retrain |
| `.env` | API keys |
