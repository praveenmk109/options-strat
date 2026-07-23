import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from datetime import datetime, date
import pytz
from tradier_client import TradierClient
import database as db
from discord_webhook import send_entry_alert
from pipeline import DataPipeline
from scoring import calculate_score
from models import find_expiries
from events import get_events_for_trade, get_earnings_dates

BUY_SCORE_THRESHOLD = float(os.getenv("BUY_SCORE_THRESHOLD", "70"))
LOWER_CUSHION = int(os.getenv("LOWER_CUSHION", "5"))
MIDDLE_CUSHION = int(os.getenv("MIDDLE_CUSHION", "0"))
UPPER_CUSHION = int(os.getenv("UPPER_CUSHION", "5"))


def is_market_open():
    try:
        tc = TradierClient()
        state = tc.get_clock()
        if state is not None:
            return state
    except Exception:
        pass
    tz_ny = pytz.timezone("America/New_York")
    now_ny = datetime.now(tz_ny)
    if now_ny.weekday() >= 5:
        return False
    hour_min = now_ny.hour * 60 + now_ny.minute
    return 9 * 60 + 30 <= hour_min < 16 * 60


def run():
    print(f"\n--- Alerter run at {datetime.now().isoformat()} ---")
    if not is_market_open():
        print("Market closed. Skipping.")
        return
    db.init_db()
    pipeline = DataPipeline()

    for symbol in ['QQQ', 'SPY']:
        today_str = date.today().isoformat()
        if db.is_alert_throttled(symbol, today_str):
            print(f"  Alert already sent today for {symbol}. Skipping.")
            continue

        try:
            quote = pipeline.tc.get_quote(symbol, greeks=False)
            if not quote:
                print(f"Failed to get {symbol} quote")
                continue
            live_price = quote.get("last") or ((quote.get("bid", 0) + quote.get("ask", 0)) / 2.0)
            if live_price <= 0:
                print(f"Invalid {symbol} price: {live_price}")
                continue
        except Exception as e:
            print(f"Failed to get {symbol} price: {e}")
            continue

        ts_ny = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d %H:00")
        db.save_underlying_hourly([{"symbol": symbol, "timestamp": ts_ny, "close": live_price}])
        print(f"{symbol}: ${live_price:.2f}")

        try:
            expirations = pipeline.tc.get_option_expirations(symbol)
        except Exception as e:
            print(f"Expirations error for {symbol}: {e}")
            continue
        if not expirations:
            print(f"No expirations found for {symbol}")
            continue

        sell_expiry, buy_expiry = find_expiries(expirations)
        if not sell_expiry or not buy_expiry:
            print(f"Could not find suitable expiries for {symbol}")
            continue
        print(f"Expiries: sell={sell_expiry}, buy={buy_expiry}")

        snap = pipeline.get_current_snapshot(symbol, sell_expiry, buy_expiry,
                                             LOWER_CUSHION, MIDDLE_CUSHION, UPPER_CUSHION)
        if not snap:
            print(f"Failed to get current snapshot for {symbol}")
            continue

        total_cost = snap["total_cost"]
        avg_iv_ratio = snap["avg_iv_ratio"]
        vol_val = snap["vol_val"]
        lower_strike = snap["lower_strike"]
        middle_strike = snap["middle_strike"]
        upper_strike = snap["upper_strike"]
        rounded = snap["rounded_cost"]
        l_cost = snap["l_cost"]
        m_cost = snap["m_cost"]
        u_cost = snap["u_cost"]
        live_price = snap["live_price"]

        print(f"Rounded straddle: ${rounded}")
        print(f"Strikes: L={lower_strike} M={middle_strike} U={upper_strike}")
        print(f"Costs: L=${l_cost:.2f} M=${m_cost:.2f} U=${u_cost:.2f} Total=${total_cost:.2f}")
        if avg_iv_ratio is not None:
            print(f"Avg IV ratio: {avg_iv_ratio:.4f}")

        db.save_vol_index_hourly([{"symbol": symbol, "timestamp": ts_ny, "close": vol_val}])

        df_hist = pipeline.get_historical_strategy_data(
            symbol, sell_expiry, buy_expiry,
            LOWER_CUSHION, MIDDLE_CUSHION, UPPER_CUSHION,
        )

        score, label, _ = calculate_score(
            df_hist, total_cost, snap["vol_ratio"], sell_expiry, buy_expiry,
            current_iv_ratio=avg_iv_ratio, current_rounded_cost=rounded,
            symbol=symbol,
        )
        if score is None:
            print(f"Incomplete score — missing components for {symbol}")
            continue
        print(f"Score: {score:.0f}/100 ({label})")

        iv_percentile = 50.0
        if avg_iv_ratio is not None and not df_hist.empty and "avg_iv_ratio" in df_hist.columns:
            hist = df_hist["avg_iv_ratio"].dropna().tail(70).values
            if len(hist) > 0:
                iv_percentile = (avg_iv_ratio >= hist).sum() / len(hist) * 100
                print(f"IV Ratio %ile: {iv_percentile:.0f}")

        if score >= BUY_SCORE_THRESHOLD:
            print(f"Entry signal for {symbol}: score {score:.0f} >= {BUY_SCORE_THRESHOLD:.0f}")
            ratio = vol_val / total_cost if total_cost > 0 else 0

            events_summary = ""
            try:
                earnings = get_earnings_dates()
                ev = get_events_for_trade(sell_expiry, buy_expiry, buffer_days=3, earnings=earnings)
                event_parts = []
                for e in ev["near_short"]:
                    event_parts.append(f"🔴{e['detail']}")
                for e in ev["during_trade"]:
                    event_parts.append(f"🟢{e['detail']}")
                if event_parts:
                    events_summary = ", ".join(event_parts)
            except Exception:
                pass

            db.save_alerts([{
                "symbol": symbol, "score": score, "label": label, "total_cost": total_cost,
                "vix": vol_val, "underlying_price": live_price, "iv_ratio": avg_iv_ratio,
                "iv_percentile": iv_percentile, "sell_expiry": sell_expiry,
                "buy_expiry": buy_expiry, "lower_strike": lower_strike,
                "middle_strike": middle_strike, "upper_strike": upper_strike,
            }])
            send_entry_alert(symbol, score, label, total_cost, vol_val, live_price, ratio,
                             sell_expiry, buy_expiry, lower_strike, middle_strike, upper_strike,
                             iv_ratio=avg_iv_ratio, iv_percentile=iv_percentile,
                             events_summary=events_summary)
            db.set_alert_throttle(symbol, today_str)
            print(f"Alert sent for {symbol} on {today_str}")
        else:
            print(f"Score {score:.0f} < {BUY_SCORE_THRESHOLD:.0f}, no alert for {symbol}")


if __name__ == "__main__":
    run()
