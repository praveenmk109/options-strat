import os
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

BASE_PROD = "https://api.tradier.com/v1"


class TradierError(Exception):
    pass


class TradierClient:
    def __init__(self, api_key=None):
        self.api_key = api_key or os.getenv("TRADIER_API_KEY")
        if not self.api_key:
            raise TradierError("TRADIER_API_KEY not set")
        self.base = BASE_PROD
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        })

    def _get(self, path, params=None):
        res = self.session.get(f"{self.base}{path}", params=params)
        if res.status_code == 401:
            raise TradierError("Unauthorized \u2014 check TRADIER_API_KEY")
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

    def get_quotes(self, symbols, greeks=True):
        if not symbols:
            return {}
        data = self._get("/markets/quotes", {
            "symbols": ",".join(symbols),
            "greeks": str(greeks).lower()
        })
        try:
            quotes = data["quotes"]["quote"]
            if isinstance(quotes, dict):
                return {quotes["symbol"]: quotes}
            return {q["symbol"]: q for q in quotes}
        except (KeyError, TypeError):
            return {}

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

    def get_clock(self):
        try:
            data = self._get("/markets/clock")
            return data.get("clock", {}).get("state") == "open"
        except Exception:
            return None

    def get_history(self, symbol, start=None, end=None, interval="daily"):
        params = {"symbol": symbol, "interval": interval}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        data = self._get("/markets/history", params)
        try:
            days = data["history"]["day"]
            if isinstance(days, dict):
                return [days]
            return days
        except (KeyError, TypeError):
            return []
