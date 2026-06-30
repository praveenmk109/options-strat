from alpaca.trading.client import TradingClient
import alpaca.trading.requests as reqs
import alpaca.trading.enums as enums

def main():
    print("Available classes in alpaca.trading.requests:")
    names = dir(reqs)
    # Print names related to options or leg or order
    for n in sorted(names):
        if any(x in n.lower() for x in ["option", "leg", "mleg", "order"]):
            print(" -", n)
            
    print("\nAvailable enums in alpaca.trading.enums:")
    for n in sorted(dir(enums)):
        if any(x in n.lower() for x in ["order", "class", "side"]):
            print(" -", n)

if __name__ == "__main__":
    main()
