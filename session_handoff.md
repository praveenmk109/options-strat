# Session Handoff: Automated Earnings Options Advisory Bot

Two-mode advisory-only system. No order execution.

- **Daily afternoon**: Mon-Fri 1:00 PM CT — per-candidate IV crush edge scan
- **Weekly preview**: Sun 8:00 AM CT — upcoming week's earnings calendar

## Architecture

- **`automated_system.py`**: `run_afternoon_execution()` (daily) + `run_weekly_preview()` (Sunday) — finds candidates, fetches straddle/consensus/upgrades/volume/OI/EPS, sends Discord
- **`alpaca_utils.py`**: Alpaca price/straddle quotes + yfinance for upgrades/downgrades, analyst consensus, options volume/OI, option mid prices
- **`discord_utils.py`**: Regular Discord messages (not embeds — normal chat font). `send_afternoon_advisory()`, `send_weekly_preview()`
- **`database_manager.py`**: SQLite CRUD (advisory-only, no trades logged)
- **`db_init.py`**: Schema + seed 127 S&P 500 stocks
- **`config.py`**: .env loader
- **`.env`**: Alpaca keys ($53K paper, from option-wheel) + Discord webhook

## Go/No-Go Decision

1. **Base edge**: `implied_move >= avg_hist_move * multiplier` (multiplier defaults to 1.5)
2. **Consensus alignment**: recommendation_mean (1=strong buy, 5=strong sell) vs strategy direction
   - Bull Put + Buy → positive alignment (easier to pass)
   - Bear Call + Buy → negative alignment/harder to pass (contrarian)
3. **Adjusted multiplier**: `multiplier * (1 - alignment * 0.2)` — ±20% adjustment
4. **Badge**: "✅ Pass" (aligned/neutral) or "⚠️ Pass (Contrarian)"

## Data Sources

- **Earnings calendar**: yfinance `t.calendar` (fast, no rate limit) + `t.earnings_dates` (scrape) for subset
- **Straddle**: Alpaca option quotes
- **Analyst consensus (free)**: yfinance `t.info` (target price, recommendation) + `t.recommendations_summary` (rating trend)
- **Upgrades/downgrades**: yfinance `t.upgrades_downgrades`
- **Options chain**: yfinance for volume/OI
- **EPS data**: yfinance `earnings_dates` DataFrame

## Crontab

```text
# Weekly Preview (Sunday 8:00 AM CT)
00 08 * * 0 cd /home/ubuntu/options-strat && python3 automated_system.py --mode weekly >> weekly.log 2>&1
# Afternoon Advisory (1:00 PM CT, Mon-Fri)
00 13 * * 1-5 cd /home/ubuntu/options-strat && python3 automated_system.py --mode afternoon >> afternoon.log 2>&1

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
| `alpaca_utils.py` | Alpaca + yfinance wrappers (275 lines) |
| `discord_utils.py` | Discord message builder (content, not embed) |
| `database_manager.py` | SQLite CRUD |
| `db_init.py` | Schema + seed |
| `earnings_trading.db` | SQLite DB, 127 stocks |
| `sp500_strategy_simulations.csv` | Win rates from last retrain |
| `.env` | API keys |
| `session_handoff.md` | This file |
