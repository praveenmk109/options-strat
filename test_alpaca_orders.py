from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, OptionLegRequest
from alpaca.trading.enums import OrderClass, OrderSide, TimeInForce
import inspect

def main():
    print("MarketOrderRequest fields:")
    m = MarketOrderRequest(symbol="AAPL", qty=1, side=OrderSide.BUY, time_in_force=TimeInForce.DAY)
    for k, v in m.dict().items():
        print(f" - {k}: {v}")
        
    print("\nOptionLegRequest fields:")
    l = OptionLegRequest(symbol="AAPL260710C00150000", side=OrderSide.BUY, ratio_qty=1)
    for k, v in l.dict().items():
        print(f" - {k}: {v}")

if __name__ == "__main__":
    main()
