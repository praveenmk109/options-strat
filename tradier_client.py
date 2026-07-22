import os
import requests

BASE_PROD = "https://api.tradier.com/v1"
REQUEST_TIMEOUT = 10  # seconds


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
