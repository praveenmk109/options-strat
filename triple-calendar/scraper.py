import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime
from pipeline import DataPipeline
from database import init_db


def run_scraper():
    print(f"Starting scraper at {datetime.now()}")
    init_db()
    pipeline = DataPipeline()
    for symbol in ['QQQ', 'SPY']:
        print(f"\n=== Processing {symbol} ===")
        success = pipeline.scrape(symbol)
        print(f"{symbol}: {'OK' if success else 'FAILED'}")
    print("Scraper run completed.")


if __name__ == "__main__":
    run_scraper()
