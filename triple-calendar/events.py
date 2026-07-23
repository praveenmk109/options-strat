"""
Event calendar for triple calendar strategy.
Provides FOMC, CPI, and earnings dates for trade period analysis.
"""
from datetime import datetime, date, timedelta
import yfinance as yf

# 2026 FOMC decision dates (Fed publishes schedule ~1 year in advance)
# Standard 8-meeting schedule: late Jan, mid-Mar, late Apr, mid-Jun,
# late Jul, mid-Sep, late Oct, mid-Dec
FOMC_2026 = [
    "2026-01-28", "2026-03-18", "2026-04-29",
    "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-09",
]

# 2026 CPI release dates (BLS publishes annual schedule)
# Typically 2nd week of each month
CPI_2026 = [
    "2026-01-14", "2026-02-11", "2026-03-11",
    "2026-04-10", "2026-05-13", "2026-06-10",
    "2026-07-14", "2026-08-12", "2026-09-11",
    "2026-10-14", "2026-11-11", "2026-12-10",
]

# Top QQQ holdings tracked for earnings
MAJOR_QQQ_HOLDINGS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOG",
    "META", "AVGO", "TSLA", "JPM", "V",
]


def get_fomc_dates() -> list[str]:
    return FOMC_2026.copy()


def get_cpi_dates() -> list[str]:
    return CPI_2026.copy()


def get_earnings_dates() -> list[dict]:
    """Fetch next earnings dates for major QQQ holdings via yfinance."""
    results = []
    today = date.today()
    for ticker_symbol in MAJOR_QQQ_HOLDINGS:
        try:
            ticker = yf.Ticker(ticker_symbol)
            cal = ticker.calendar
            if cal and "Earnings Date" in cal:
                earnings_dates = cal["Earnings Date"]
                if earnings_dates:
                    d = earnings_dates[0]
                    if isinstance(d, datetime):
                        d_str = d.strftime("%Y-%m-%d")
                        d_date = d.date()
                    elif isinstance(d, date):
                        d_str = d.strftime("%Y-%m-%d")
                        d_date = d
                    else:
                        continue
                    if d_date < today - timedelta(days=5):
                        continue
                    results.append({"date": d_str, "ticker": ticker_symbol})
        except Exception:
            continue
    return results


def get_events_for_trade(sell_expiry: str, buy_expiry: str,
                         buffer_days: int = 3,
                         earnings: list[dict] | None = None) -> dict:
    """Categorize events by risk level for a given trade period.

    Returns:
        {
            "near_short": [{"date": str, "type": str, "detail": str}],
            "during_trade": [{"date": str, "type": str, "detail": str}],
        }

    near_short: event within buffer_days before short expiry (risky)
    during_trade: event after short expiry but before long expiry (safe)
    """
    sell_dt = datetime.strptime(sell_expiry, "%Y-%m-%d").date()
    buy_dt = datetime.strptime(buy_expiry, "%Y-%m-%d").date()

    all_events = []
    for d in get_fomc_dates():
        all_events.append({"date": d, "type": "FOMC", "detail": "FOMC Meeting"})
    for d in get_cpi_dates():
        all_events.append({"date": d, "type": "CPI", "detail": "CPI Release"})
    if earnings is None:
        earnings = get_earnings_dates()
    for e in earnings:
        all_events.append({"date": e["date"], "type": "Earnings", "detail": f"{e['ticker']} Earnings"})

    result = {"near_short": [], "during_trade": []}

    buffer_start = sell_dt - timedelta(days=buffer_days)
    for event in all_events:
        ev_dt = datetime.strptime(event["date"], "%Y-%m-%d").date()
        if buffer_start <= ev_dt <= sell_dt:
            result["near_short"].append(event)
        elif sell_dt < ev_dt <= buy_dt:
            result["during_trade"].append(event)

    for key in result:
        result[key].sort(key=lambda x: x["date"])

    return result
