import math
import bisect
from datetime import datetime


def percentile_rank(value, population):
    """Smooth percentile rank 0-100 using linear interpolation."""
    if isinstance(value, float) and math.isnan(value):
        return 50.0
    if len(population) < 2:
        return 50.0
    sorted_pop = sorted(population)
    n = len(sorted_pop)
    if value <= sorted_pop[0]:
        return 0.0
    if value >= sorted_pop[-1]:
        return 100.0
    idx = bisect.bisect_left(sorted_pop, value)
    if idx == 0:
        return 0.0
    if idx == n:
        return 100.0
    lower = sorted_pop[idx - 1]
    upper = sorted_pop[idx]
    if upper == lower:
        return (idx - 1) / (n - 1) * 100
    frac = (value - lower) / (upper - lower)
    return (idx - 1 + frac) / (n - 1) * 100


def calculate_score(df_hist, current_cost, current_vol_ratio, sell_expiry=None, buy_expiry=None,
                    current_iv_ratio=None, current_rounded_cost=None, symbol="QQQ"):
    """4-factor percentile-based scoring. Returns (score, label, color).

    Weights vary by symbol: SPY gets lower IV ratio weight due to structural contango.
    """
    if (df_hist.empty
        or current_cost is None
        or (isinstance(current_cost, float) and math.isnan(current_cost))
        or current_vol_ratio is None
        or (isinstance(current_vol_ratio, float) and math.isnan(current_vol_ratio))
        or current_cost <= 0):
        return None, "Incomplete", "#6b7280"

    valid_df = df_hist[df_hist['total_strategy_cost'] > 0].dropna(subset=['total_strategy_cost', 'vol_ratio']).copy()
    if valid_df.empty:
        return None, "Incomplete", "#6b7280"

    if sell_expiry and buy_expiry:
        try:
            sell_dt = datetime.strptime(sell_expiry, "%Y-%m-%d")
            buy_dt = datetime.strptime(buy_expiry, "%Y-%m-%d")

            def get_time_factor(ts_str):
                d_str = ts_str.split()[0] if " " in ts_str else ts_str
                dt = datetime.strptime(d_str, "%Y-%m-%d")
                s_dte = max(1, (sell_dt - dt).days)
                l_dte = max(2, (buy_dt - dt).days)
                tf = math.sqrt(l_dte) - math.sqrt(s_dte)
                return tf if tf > 0 else 1.0

            valid_df['tf'] = valid_df['timestamp'].apply(get_time_factor)
            valid_df['norm_cost'] = valid_df['total_strategy_cost'] / valid_df['tf']

            current_tf = get_time_factor(datetime.now().strftime("%Y-%m-%d"))
            current_norm_cost = current_cost / current_tf

            costs = valid_df['norm_cost'].tolist()
            current_cost_for_rank = current_norm_cost

        except Exception:
            costs = valid_df['total_strategy_cost'].tolist()
            current_cost_for_rank = current_cost
    else:
        costs = valid_df['total_strategy_cost'].tolist()
        current_cost_for_rank = current_cost

    # Factor 1: Cost (35%) — lower is better
    cost_pct = percentile_rank(current_cost_for_rank, costs)
    cost_score = 100.0 - cost_pct

    # Factor 2: Vol (25%) — lower VXN/20DMA ratio is better (room to expand)
    ratios = valid_df['vol_ratio'].tolist()
    vol_pct = percentile_rank(current_vol_ratio, ratios)
    vol_score = 100.0 - vol_pct

    # Factor 3: IV ratio (25%) — higher is better
    iv_ratios = valid_df['avg_iv_ratio'].dropna().tolist()
    iv_score = None
    if current_iv_ratio is not None and len(iv_ratios) >= 3:
        iv_score = percentile_rank(current_iv_ratio, iv_ratios)

    # Factor 4: Width (15%) — higher width-per-cost is better
    width_score = None
    hist_widths = []
    if 'rounded_cost' in valid_df.columns:
        hist_widths = (valid_df['rounded_cost'] * 2.0 / valid_df['total_strategy_cost']).dropna().tolist()
    if current_rounded_cost is not None and current_rounded_cost > 0 and current_cost > 0 and len(hist_widths) >= 3:
        current_width = current_rounded_cost * 2.0 / current_cost
        width_score = percentile_rank(current_width, hist_widths)

    # Require all 4 components or return no score
    if iv_score is None or width_score is None:
        return None, "Incomplete", "#6b7280"

    if symbol == "SPY":
        w_cost, w_iv, w_vol, w_width = 0.35, 0.15, 0.35, 0.15
    else:
        w_cost, w_iv, w_vol, w_width = 0.35, 0.25, 0.25, 0.15

    score = w_cost * cost_score + w_iv * iv_score + w_vol * vol_score + w_width * width_score
    score = max(0.0, min(100.0, score))

    if score >= 80.0:
        label = "Strong Buy"
        color = "#10b981"
    elif score >= 40.0:
        label = "Neutral"
        color = "#f59e0b"
    else:
        label = "Avoid"
        color = "#ef4444"

    return score, label, color
