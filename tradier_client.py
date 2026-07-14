import os
import requests
from datetime import datetime

BASE_PROD = "https://api.tradier.com/v1"


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
        res = self.session.get(f"{self.base}{path}", params=params)
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


def format_osi(underlying, expiry_str, opt_type_str, strike):
    dt = datetime.strptime(expiry_str, "%Y-%m-%d")
    yymmdd = dt.strftime("%y%m%d")
    strike_cents = int(round(strike * 1000))
    strike_str = f"{strike_cents:08d}"
    symbol_type = "C" if opt_type_str.upper() in ("C", "CALL") else "P"
    return f"{underlying}{yymmdd}{symbol_type}{strike_str}"
