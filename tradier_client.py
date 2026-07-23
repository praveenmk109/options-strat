import os
import requests
from datetime import datetime, timedelta

BASE_PROD = "https://api.tradier.com/v1"
REQUEST_TIMEOUT = 10  # seconds
NASDAQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def get_nasdaq_earnings(date_str):
    """Get earnings calendar from Nasdaq for a specific date (YYYY-MM-DD).
    Returns dict mapping ticker -> timing ('BMO', 'AMC', or None).
    """
    url = f"https://api.nasdaq.com/api/calendar/earnings?date={date_str}"
    try:
        r = requests.get(url, headers=NASDAQ_HEADERS, timeout=15)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", {}).get("rows", [])
        result = {}
        for row in rows:
            ticker = row.get("symbol")
            time_raw = row.get("time", "")
            if time_raw == "time-pre-market":
                timing = "BMO"
            elif time_raw == "time-after-hours":
                timing = "AMC"
            else:
                timing = None
            if ticker:
                result[ticker] = timing
        return result
    except Exception:
        return {}


def get_nasdaq_earnings_week(start_date):
    """Get earnings for Mon-Fri starting from start_date (datetime).
    Returns dict mapping ticker -> {'timing': 'BMO'/'AMC'/None, 'date': date, 'trading_date': date}.
    """
    # Find Monday of the week
    monday = start_date - timedelta(days=start_date.weekday())
    all_earnings = {}

    for i in range(5):  # Mon-Fri
        day = monday + timedelta(days=i)
        date_str = day.strftime("%Y-%m-%d")
        day_earnings = get_nasdaq_earnings(date_str)

        for ticker, timing in day_earnings.items():
            if timing == "BMO":
                # Trade day before
                trading_date = day - timedelta(days=1)
                # If day before is weekend, go back to Friday
                if trading_date.weekday() == 5:  # Saturday
                    trading_date = day - timedelta(days=2)
                elif trading_date.weekday() == 6:  # Sunday
                    trading_date = day - timedelta(days=3)
            else:
                # AMC or unknown: trade same day
                trading_date = day

            all_earnings[ticker] = {
                "timing": timing,
                "date": day,
                "trading_date": trading_date,
            }

    return all_earnings


class TradierError(Exception):
    pass


class TradierClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.environ.get("TRADIER_API_KEY")
        if not self.api_key:
            raise TradierError("TRADIER_API_KEY not set in environment")
        self.base = BASE_PROD
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def _get(self, path, params=None):
        res = self.session.get(f"{self.base}{path}", params=params, timeout=REQUEST_TIMEOUT)
        if res.status_code == 401:
            raise TradierError("Unauthorized — check TRADIER_API_KEY")
        if res.status_code == 400:
            raise TradierError(f"Bad request: {res.text}")
        res.raise_for_status()
        return res.json()

    def get_quote(self, symbol, greeks=True):
        data = self._get("/markets/quotes", {"symbols": symbol, "greeks": str(greeks).lower()})
        try:
            q = data["quotes"]["quote"]
            if isinstance(q, list):
                return q[0]
            return q
        except (KeyError, TypeError, IndexError):
            return None

    def get_option_expirations(self, symbol):
        data = self._get("/markets/options/expirations", {"symbol": symbol})
        try:
            dates = data["expirations"]["date"]
            if isinstance(dates, str):
                return [dates]
            return dates
        except (KeyError, TypeError):
            return []

    def get_option_chain(self, symbol, expiry, greeks=True):
        data = self._get("/markets/options/chains", {
            "symbol": symbol,
            "expiration": expiry,
            "greeks": str(greeks).lower(),
        })
        try:
            opts = data["options"]["option"]
            if isinstance(opts, dict):
                return [opts]
            return opts
        except (KeyError, TypeError):
            return []
