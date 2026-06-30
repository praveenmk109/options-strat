import alpaca.data.historical.option as option_data
import alpaca.data.requests as reqs

def main():
    print("Option historical data classes:")
    for n in sorted(dir(option_data)):
        if "option" in n.lower() or "client" in n.lower():
            print(" -", n)
            
    print("\nData request classes:")
    for n in sorted(dir(reqs)):
        if "option" in n.lower() or "quote" in n.lower():
            print(" -", n)

if __name__ == "__main__":
    main()
