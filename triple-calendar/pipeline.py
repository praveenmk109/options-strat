import pandas as pd
import numpy as np
from datetime import datetime, date, timedelta
import pytz
import yfinance as yf
from tradier_client import TradierClient
import database as db
import models
from scoring import calculate_score


class DataPipeline:
    def __init__(self):
        self.tc = TradierClient()

    # ── Scraping ────────────────────────────────────────────

    def scrape(self, symbol: str) -> bool:
        """Fetch underlying, vol index, and option chains for a symbol and save to DB."""
        et = pytz.timezone("America/New_York")
        ts = datetime.now(et).strftime("%Y-%m-%d %H:00")
        today_str = datetime.now(et).strftime("%Y-%m-%d")
        vol_ticker = {"QQQ": "^VXN", "SPY": "^VIX"}[symbol]

        quote = self.tc.get_quote(symbol)
        if not quote:
            return False
        price = float(quote.get("last") or quote.get("close") or 0)
        if price == 0:
            return False

        db.save_underlying_hourly([{"symbol": symbol, "timestamp": ts, "close": price}])

        expirations = self.tc.get_option_expirations(symbol)
        if not expirations:
            return False

        collection_horizon = datetime.now(et) + timedelta(weeks=10)
        valid_expiries = [
            e for e in expirations
            if today_str <= e <= collection_horizon.strftime("%Y-%m-%d")
            and datetime.strptime(e, "%Y-%m-%d").weekday() == 4
        ]

        lower_bound = price * 0.90
        upper_bound = price * 1.10
        all_records = []
        for expiry in valid_expiries:
            chain = self.tc.get_option_chain(symbol, expiry, greeks=True)
            if not chain:
                continue
            for opt in chain:
                strike = float(opt.get("strike", 0))
                if strike < lower_bound or strike > upper_bound:
                    continue
                if int(round(strike)) % 5 != 0:
                    continue
                raw_type = opt.get("option_type", "").upper()
                opt_type = "C" if raw_type == "CALL" else "P"
                greeks = opt.get("greeks") or {}
                bid = float(opt["bid"]) if opt.get("bid") is not None else 0.0
                ask = float(opt["ask"]) if opt.get("ask") is not None else 0.0
                mid = (bid + ask) / 2.0 if (bid > 0 and ask > 0) else 0.0
                all_records.append({
                    "symbol": symbol, "timestamp": ts,
                    "expiry": opt.get("expiration_date", expiry),
                    "strike": strike, "type": opt_type,
                    "bid": bid, "ask": ask, "mid": mid,
                    "volume": int(opt.get("volume", 0) or 0),
                    "open_interest": int(opt.get("open_interest", 0) or 0),
                    "implied_volatility": float(greeks.get("mid_iv", 0) or 0),
                    "delta": float(greeks.get("delta", 0) or 0),
                    "gamma": float(greeks.get("gamma", 0) or 0),
                    "theta": float(greeks.get("theta", 0) or 0),
                    "vega": float(greeks.get("vega", 0) or 0),
                })

        if all_records:
            db.save_options_hourly(all_records)

        vol_val = 20.0
        try:
            vix_hist = yf.Ticker(vol_ticker).history(period="1d")
            if not vix_hist.empty:
                vol_val = float(vix_hist["Close"].iloc[-1])
        except Exception:
            pass
        db.save_vol_index_hourly([{"symbol": symbol, "timestamp": ts, "close": vol_val}])

        return True

    # ── Historical strategy reconstruction + caching ──────

    def get_historical_strategy_data(self, symbol: str, sell_expiry: str, buy_expiry: str,
                                     lower_cushion: int, middle_cushion: int, upper_cushion: int) -> pd.DataFrame:
        """Load raw data, reconstruct strategy snapshots, cache scores, return enriched DataFrame."""
        underlying_rows = db.get_underlying_hourly(symbol)
        if not underlying_rows:
            return pd.DataFrame()

        vol_map = {r["timestamp"]: r["close"] for r in db.get_vol_index_hourly(symbol)}
        min_ts = underlying_rows[0]["timestamp"]

        options_df = db.get_options_for_strategy(symbol, sell_expiry, buy_expiry, min_ts)
        opt_map = {}
        iv_map = {}
        for _, row in options_df.iterrows():
            key = (row["timestamp"], row["expiry"], float(row["strike"]), row["type"])
            opt_map[key] = float(row["mid"])
            raw_iv = row["implied_volatility"]
            if raw_iv is not None and float(raw_iv) > 0:
                iv_map[key] = float(raw_iv)

        records = []
        for underlying_row in underlying_rows:
            ts_str = underlying_row["timestamp"]
            underlying_close = float(underlying_row["close"])
            snapshot = self._reconstruct_snapshot(
                ts_str, underlying_close, opt_map, iv_map,
                sell_expiry, buy_expiry, lower_cushion, middle_cushion, upper_cushion
            )
            if snapshot:
                vol_val = vol_map.get(ts_str)
                snapshot["vix_close"] = vol_val
                records.append(snapshot)

        if not records:
            return pd.DataFrame()

        df_res = pd.DataFrame(records)
        df_res = df_res.sort_values("timestamp").reset_index(drop=True)

        # Compute VXN/20DMA ratio for each snapshot
        vol_ticker = {"QQQ": "^VXN", "SPY": "^VIX"}[symbol]
        try:
            vxn = yf.Ticker(vol_ticker).history(period="3mo")
            if not vxn.empty:
                close = vxn['Close']
                dma20 = close.rolling(20, min_periods=5).mean()
                dma_map = {}
                for date_idx in close.index:
                    d_str = date_idx.strftime('%Y-%m-%d')
                    c = close.loc[date_idx]
                    d = dma20.loc[date_idx]
                    if d > 0:
                        dma_map[d_str] = c / d
                df_res['vol_ratio'] = df_res['timestamp'].apply(
                    lambda ts: dma_map.get(ts.split()[0])
                )
        except Exception:
            df_res['vol_ratio'] = None

        cached = db.load_strategy_scores(sell_expiry, buy_expiry, symbol, min_ts)
        cached_map = {r["timestamp"]: r for r in cached}

        scores_to_save = []
        score_col = []
        label_col = []

        for i in range(len(df_res)):
            ts_val = df_res.iloc[i]["timestamp"]
            if ts_val in cached_map:
                score_col.append(cached_map[ts_val]["score"])
                label_col.append(cached_map[ts_val]["label"])
            else:
                raw_cost = df_res.iloc[i]["total_strategy_cost"]
                cost = None if pd.isna(raw_cost) else raw_cost
                vol_ratio = df_res.iloc[i].get("vol_ratio")
                vol_ratio = None if vol_ratio is None or pd.isna(vol_ratio) else vol_ratio
                raw_rc = df_res.iloc[i].get("rounded_cost") if "rounded_cost" in df_res.columns else None
                rc_val = None if raw_rc is None or pd.isna(raw_rc) else raw_rc
                raw_iv = df_res.iloc[i].get("avg_iv_ratio") if "avg_iv_ratio" in df_res.columns else None
                iv_ratio_val = None if raw_iv is None or pd.isna(raw_iv) else raw_iv
                if vol_ratio is None or cost is None or cost <= 0:
                    score_col.append(None)
                    label_col.append("N/A")
                else:
                    s, lbl, _ = calculate_score(
                        df_res, cost, vol_ratio, sell_expiry, buy_expiry,
                        current_rounded_cost=rc_val, current_iv_ratio=iv_ratio_val,
                        symbol=symbol,
                    )
                    if s is None:
                        score_col.append(None)
                        label_col.append("Incomplete")
                    else:
                        score_col.append(s)
                        label_col.append(lbl)
                        scores_to_save.append({
                            "symbol": symbol, "timestamp": ts_val,
                            "expiry_short": sell_expiry, "expiry_long": buy_expiry,
                            "score": s, "label": lbl,
                        })

        if scores_to_save:
            db.save_strategy_scores(scores_to_save)

        df_res["buy_score"] = score_col
        df_res["buy_label"] = label_col

        if "avg_iv_ratio" in df_res.columns:
            df_res["iv_ratio_percentile"] = (
                df_res["avg_iv_ratio"]
                .rolling(window=70, min_periods=1)
                .apply(lambda x: (x[-1] >= x).sum() / len(x) * 100 if not np.isnan(x[-1]) else np.nan, raw=True)
            )

        # For backfilled buy-leg data (no IV), keep only the 16:00 close
        # row where both legs share the same underlying price.
        backfilled_mask = df_res["avg_iv_ratio"].isna()
        df_res = df_res[~(backfilled_mask & ~df_res["timestamp"].str.endswith(" 16:00"))]

        return df_res

    # ── Live snapshot (for alerter and dashboard live card) ──

    def get_current_snapshot(self, symbol: str, sell_expiry: str, buy_expiry: str,
                             lower_cushion: int, middle_cushion: int, upper_cushion: int) -> dict:
        """Compute current strategy params from live market data."""
        import utils

        quote = self.tc.get_quote(symbol, greeks=False)
        if not quote:
            return {}
        live_price = quote.get("last") or ((quote.get("bid", 0) + quote.get("ask", 0)) / 2.0)
        if live_price <= 0:
            return {}

        atm_strike = int(round(live_price / 5.0) * 5)

        atm_sell_c = utils.format_osi(symbol, sell_expiry, "C", atm_strike)
        atm_sell_p = utils.format_osi(symbol, sell_expiry, "P", atm_strike)
        atm_quotes = self.tc.get_quotes([atm_sell_c, atm_sell_p])
        call_q = atm_quotes.get(atm_sell_c)
        put_q = atm_quotes.get(atm_sell_p)
        call_mid = (call_q["bid"] + call_q["ask"]) / 2.0 if call_q and call_q.get("bid") is not None and call_q.get("ask") is not None else 0.0
        put_mid = (put_q["bid"] + put_q["ask"]) / 2.0 if put_q and put_q.get("bid") is not None and put_q.get("ask") is not None else 0.0
        straddle = call_mid + put_mid
        rounded = models.compute_rounded_cost(straddle) if straddle > 0 else 5

        lower_strike, middle_strike, upper_strike = models.compute_strikes(
            atm_strike, rounded, lower_cushion, middle_cushion, upper_cushion
        )

        leg_syms = [
            utils.format_osi(symbol, sell_expiry, "P", lower_strike),
            utils.format_osi(symbol, buy_expiry, "P", lower_strike),
            utils.format_osi(symbol, sell_expiry, "P", middle_strike),
            utils.format_osi(symbol, buy_expiry, "P", middle_strike),
            utils.format_osi(symbol, sell_expiry, "C", upper_strike),
            utils.format_osi(symbol, buy_expiry, "C", upper_strike),
        ]
        all_syms = leg_syms + [atm_sell_c, atm_sell_p,
                               utils.format_osi(symbol, buy_expiry, "C", atm_strike),
                               utils.format_osi(symbol, buy_expiry, "P", atm_strike)]

        quotes = self.tc.get_quotes(all_syms)
        if not quotes:
            return {}

        def get_mid_price(sym):
            q = quotes.get(sym)
            if not q:
                return None
            if q.get("bid") is not None and q.get("ask") is not None:
                return (q["bid"] + q["ask"]) / 2.0
            return q.get("last")

        l_cost = models.compute_leg_cost(
            get_mid_price(leg_syms[1]) or 0, get_mid_price(leg_syms[0]) or 0
        )
        m_cost = models.compute_leg_cost(
            get_mid_price(leg_syms[3]) or 0, get_mid_price(leg_syms[2]) or 0
        )
        u_cost = models.compute_leg_cost(
            get_mid_price(leg_syms[5]) or 0, get_mid_price(leg_syms[4]) or 0
        )
        total_cost = models.compute_strategy_costs(l_cost, m_cost, u_cost)

        vol_ticker = {"QQQ": "^VXN", "SPY": "^VIX"}[symbol]
        vol_val = 20.0
        vol_ratio = 1.0
        try:
            vol_df = yf.Ticker(vol_ticker).history(period="3mo")
            if not vol_df.empty:
                close = vol_df['Close']
                vol_val = float(close.iloc[-1])
                dma20 = close.rolling(20, min_periods=5).mean().iloc[-1]
                vol_ratio = vol_val / dma20 if dma20 > 0 else 1.0
        except Exception:
            pass

        leg_ratios = []
        for i in range(0, 6, 2):
            sq = quotes.get(leg_syms[i])
            lq = quotes.get(leg_syms[i + 1])
            if sq and lq:
                iv_s = sq.get("greeks", {}).get("mid_iv")
                iv_l = lq.get("greeks", {}).get("mid_iv")
                ratio = models.compute_iv_ratio(iv_s, iv_l)
                if ratio is not None:
                    leg_ratios.append(ratio)
        avg_iv_ratio = models.compute_avg_iv_ratio(leg_ratios) if len(leg_ratios) >= 2 else None

        return {
            "live_price": live_price,
            "atm_strike": atm_strike,
            "rounded_cost": rounded,
            "lower_strike": lower_strike,
            "middle_strike": middle_strike,
            "upper_strike": upper_strike,
            "total_cost": total_cost,
            "vol_val": vol_val,
            "vol_ratio": vol_ratio,
            "avg_iv_ratio": avg_iv_ratio,
            "leg_syms": leg_syms,
            "l_cost": l_cost,
            "m_cost": m_cost,
            "u_cost": u_cost,
        }

    # ── Internal helpers ──────────────────────────────────

    def _reconstruct_snapshot(self, ts_str, underlying_close, opt_map, iv_map,
                              sell_expiry, buy_expiry,
                              lower_cushion, middle_cushion, upper_cushion):
        """Reconstruct strategy parameters for a single historical timestamp."""
        atm_strike = int(round(underlying_close / 5.0) * 5)

        s_ac = opt_map.get((ts_str, sell_expiry, float(atm_strike), "C"))
        s_ap = opt_map.get((ts_str, sell_expiry, float(atm_strike), "P"))

        if s_ac is None or s_ap is None:
            straddle = 15.0
        else:
            straddle = s_ac + s_ap

        rounded_cost = models.compute_rounded_cost(straddle)

        lower_strike, middle_strike, upper_strike = models.compute_strikes(
            atm_strike, rounded_cost, lower_cushion, middle_cushion, upper_cushion
        )

        l_put_s = opt_map.get((ts_str, sell_expiry, float(lower_strike), "P"))
        l_put_l = opt_map.get((ts_str, buy_expiry, float(lower_strike), "P"))
        m_put_s = opt_map.get((ts_str, sell_expiry, float(middle_strike), "P"))
        m_put_l = opt_map.get((ts_str, buy_expiry, float(middle_strike), "P"))
        u_call_s = opt_map.get((ts_str, sell_expiry, float(upper_strike), "C"))
        u_call_l = opt_map.get((ts_str, buy_expiry, float(upper_strike), "C"))

        if None in [l_put_s, l_put_l, m_put_s, m_put_l, u_call_s, u_call_l]:
            return None

        lower_cost = models.compute_leg_cost(l_put_l, l_put_s)
        middle_cost = models.compute_leg_cost(m_put_l, m_put_s)
        upper_cost = models.compute_leg_cost(u_call_l, u_call_s)
        total_cost = models.compute_strategy_costs(lower_cost, middle_cost, upper_cost)

        leg_ratios = []
        leg_keys = [
            (sell_expiry, float(lower_strike), "P", buy_expiry, float(lower_strike), "P"),
            (sell_expiry, float(middle_strike), "P", buy_expiry, float(middle_strike), "P"),
            (sell_expiry, float(upper_strike), "C", buy_expiry, float(upper_strike), "C"),
        ]
        for e_s, k_s, t_s, e_l, k_l, t_l in leg_keys:
            iv_s = iv_map.get((ts_str, e_s, k_s, t_s))
            iv_l = iv_map.get((ts_str, e_l, k_l, t_l))
            ratio = models.compute_iv_ratio(iv_s, iv_l)
            if ratio is not None:
                leg_ratios.append(ratio)
        avg_iv_ratio_val = models.compute_avg_iv_ratio(leg_ratios)

        return {
            "timestamp": ts_str,
            "qqq_close": underlying_close,
            "atm_strike": atm_strike,
            "lower_strike": lower_strike,
            "middle_strike": middle_strike,
            "upper_strike": upper_strike,
            "rounded_cost": rounded_cost,
            "lower_calendar_cost": lower_cost,
            "middle_calendar_cost": middle_cost,
            "upper_calendar_cost": upper_cost,
            "total_strategy_cost": total_cost,
            "avg_iv_ratio": avg_iv_ratio_val,
        }
