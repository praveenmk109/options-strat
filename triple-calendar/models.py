from datetime import datetime, date, timedelta
from typing import Optional


def find_expiries(expiration_dates: list[str], today: Optional[date] = None,
                  target_sell_days: int = 21, target_buy_days: int = 28) -> tuple[Optional[str], Optional[str]]:
    """Find nearest Friday expiries >= target sell/buy DTE."""
    if today is None:
        today = date.today()
    exp_dates = sorted([
        datetime.strptime(e, "%Y-%m-%d").date()
        for e in expiration_dates
        if datetime.strptime(e, "%Y-%m-%d").date() >= today
    ])
    target_sell = today + timedelta(days=target_sell_days)
    target_buy = today + timedelta(days=target_buy_days)
    sell_expiry = buy_expiry = None
    for exp_dt in exp_dates:
        if not sell_expiry and exp_dt >= target_sell:
            sell_expiry = exp_dt.strftime("%Y-%m-%d")
        if not buy_expiry and exp_dt >= target_buy:
            buy_expiry = exp_dt.strftime("%Y-%m-%d")
    if not sell_expiry or not buy_expiry:
        return None, None
    if buy_expiry <= sell_expiry:
        sell_dt = datetime.strptime(sell_expiry, "%Y-%m-%d").date()
        idx = exp_dates.index(sell_dt)
        if idx + 1 < len(exp_dates):
            buy_expiry = exp_dates[idx + 1].strftime("%Y-%m-%d")
        else:
            return None, None
    return sell_expiry, buy_expiry


def compute_rounded_cost(straddle: float, step: int = 5) -> int:
    """Round straddle to nearest $5 increment, minimum $5."""
    return max(step, int(round(straddle / step) * step))


def compute_strikes(atm_strike: int, rounded_cost: int,
                    lower_cushion: int, middle_cushion: int, upper_cushion: int) -> tuple[int, int, int]:
    """Compute lower/middle/upper strikes from ATM strike, rounded cost, and cushions."""
    lower = int(atm_strike - (rounded_cost + lower_cushion))
    middle = int(atm_strike + middle_cushion)
    upper = int(atm_strike + (rounded_cost + upper_cushion))
    return lower, middle, upper


def compute_leg_cost(long_mid: float, short_mid: float) -> float:
    """Cost of a calendar spread leg (long - short)."""
    return max(0.01, long_mid - short_mid)


def compute_strategy_costs(lower_cost: float, middle_cost: float, upper_cost: float) -> float:
    return lower_cost + middle_cost + upper_cost


def compute_iv_ratio(sell_iv: float, buy_iv: float) -> Optional[float]:
    """IV ratio for a single leg pair (sell IV / buy IV)."""
    if sell_iv is not None and buy_iv is not None and buy_iv > 0:
        return sell_iv / buy_iv
    return None


def compute_avg_iv_ratio(leg_ratios: list[float]) -> Optional[float]:
    """Average of available leg IV ratios."""
    if len(leg_ratios) >= 2:
        return sum(leg_ratios) / len(leg_ratios)
    return None
