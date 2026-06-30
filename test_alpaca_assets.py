from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import AssetStatus
import os

API_KEY = os.environ.get("APCA_API_KEY_ID", "YOUR_API_KEY")
API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "YOUR_API_SECRET")

def main():
    if API_KEY == "YOUR_API_KEY":
        print("API Key not configured. Skipping active test.")
        return
        
    client = TradingClient(API_KEY, API_SECRET, paper=True)
    try:
        req = GetOptionContractsRequest(
            underlying_symbol=["AAPL"],
            status=AssetStatus.ACTIVE
        )
        res = client.get_option_contracts(req)
        print(f"Success! Found {len(res.option_contracts)} contracts for AAPL.")
        # Print a few contracts
        for c in res.option_contracts[:5]:
            print(f" - Symbol: {c.symbol}, Expiration: {c.expiration_date}, Strike: {c.strike_price}, Type: {c.type}")
    except Exception as e:
        print("Error:", e)

if __name__ == "__main__":
    main()
