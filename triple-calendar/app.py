import streamlit as st
import pandas as pd
import numpy as np
import os
from datetime import datetime, timedelta
import pytz
import yfinance as yf
from tradier_client import TradierClient
import database as db
import utils
from collections import defaultdict
from pipeline import DataPipeline
from scoring import calculate_score
from models import find_expiries, compute_rounded_cost, compute_strikes
from events import get_events_for_trade, get_earnings_dates

# ── Constants ──────────────────────────────────────────

SYMBOL_CONFIG = {
    "QQQ": {"vol_ticker": "^VXN", "vol_label": "VXN"},
    "SPY": {"vol_ticker": "^VIX", "vol_label": "VIX"},
}

EVENT_BUFFER_DAYS = int(os.getenv("EVENT_BUFFER_DAYS", "3"))


@st.cache_data(ttl=3600)
def fetch_earnings_cached():
    return get_earnings_dates()


# ── Helpers ─────────────────────────────────────────────

def is_market_open_ct():
    try:
        tc = TradierClient()
        state = tc.get_clock()
        if state is not None:
            return state
    except Exception:
        pass
    tz = pytz.timezone("America/Chicago")
    now = datetime.now(tz)
    if now.weekday() >= 5:
        return False
    hm = now.hour * 60 + now.minute
    return 8 * 60 + 30 <= hm < 15 * 60


def format_expiry_nice(date_str):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except Exception:
        return date_str


def render_hourly_table(df):
    if df.empty:
        st.markdown("<div style='color: #94a3b8; font-style: italic;'>No data.</div>", unsafe_allow_html=True)
        return
    html = '<div class="custom-table-container"><table class="custom-table"><thead><tr>'
    for col in df.columns:
        html += f"<th>{col}</th>"
    html += "</tr></thead><tbody>"
    for _, row in df.iterrows():
        html += "<tr>"
        for col in df.columns:
            val = str(row[col])
            if col == "Buy Score":
                html += f"<td>{val}</td>"
            elif col == "Total Cost":
                html += f'<td style="font-weight: 600; color: #60a5fa;">{val}</td>'
            elif col == "Current Value":
                html += f'<td style="font-weight: 600; color: #a78bfa;">{val}</td>'
            elif col == "IV Ratio %ile":
                try:
                    p = int(val)
                    if p >= 90:
                        g = "#10b981"
                    elif p >= 75:
                        g = "#34d399"
                    elif p >= 50:
                        g = "#fbbf24"
                    else:
                        g = "#ef4444"
                    html += f'<td style="font-weight: 700; color: {g};">{val}</td>'
                except Exception:
                    html += f"<td>{val}</td>"
            elif col == "Vol/Cost Ratio":
                html += f'<td style="font-weight: 500; color: #e2e8f0;">{val}</td>'
            elif col == "Current PnL":
                if val.startswith("-"):
                    color = "#ef4444"
                elif val.startswith("+"):
                    color = "#10b981"
                else:
                    color = "#cbd5e1"
                html += f'<td style="color: {color}; font-weight: 600;">{val}</td>'
            else:
                html += f"<td>{val}</td>"
        html += "</tr>"
    html += "</tbody></table></div>"
    st.markdown(html, unsafe_allow_html=True)


# ── Page Config ────────────────────────────────────────

st.set_page_config(
    page_title="Triple Calendar Scanner",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ─────────────────────────────────────────

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif;
    background-color: #0f172a;
}
.header {
    background: linear-gradient(90deg, #1e3a8a 0%, #3b82f6 50%, #1d4ed8 100%);
    padding: 20px 25px;
    border-radius: 12px;
    margin-bottom: 25px;
    border: 1px solid rgba(255,255,255,0.1);
    box-shadow: 0 4px 20px rgba(0,0,0,0.25);
}
.header-title {
    color: #fff;
    font-size: 1.6rem;
    font-weight: 700;
    margin: 0;
}
.header-meta {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-top: 8px;
    flex-wrap: wrap;
}
.header-time {
    color: #cbd5e1;
    font-size: 0.85rem;
}
.status-pill {
    display: inline-flex;
    align-items: center;
    padding: 4px 12px;
    border-radius: 50px;
    font-size: 0.85rem;
    font-weight: 500;
}
.status-active {
    background: rgba(16,185,129,0.15);
    color: #10b981;
    border: 1px solid rgba(16,185,129,0.3);
}
.status-closed {
    background: rgba(148,163,184,0.15);
    color: #94a3b8;
    border: 1px solid rgba(148,163,184,0.3);
}
.card {
    background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
    border: 1px solid #334155;
    border-radius: 12px;
    padding: 22px;
    margin-bottom: 20px;
    box-shadow: 0 10px 15px -3px rgba(0,0,0,0.3);
}
.card-title {
    color: #94a3b8;
    font-size: 0.85rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin: 0 0 12px 0;
}
.buy-score {
    text-align: center;
    padding: 30px 20px;
}
.buy-score-number {
    font-size: 4rem;
    font-weight: 800;
    line-height: 1;
}
.buy-score-label {
    font-size: 1.3rem;
    font-weight: 600;
    margin-top: 6px;
}
.buy-score-sub {
    display: flex;
    justify-content: center;
    gap: 24px;
    margin-top: 16px;
    font-size: 0.85rem;
    flex-wrap: wrap;
}
.buy-score-sub-item {
    text-align: center;
}
.buy-score-sub-label {
    color: #64748b;
    font-size: 0.75rem;
}
.buy-score-sub-value {
    color: #e2e8f0;
    font-weight: 600;
    font-size: 1rem;
}
.snapshot-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 6px;
}
.snapshot-item {
    padding: 8px 0;
    display: flex;
    justify-content: space-between;
    border-bottom: 1px solid #1e293b;
}
.snapshot-label {
    color: #64748b;
    font-size: 0.85rem;
}
.snapshot-value {
    color: #e2e8f0;
    font-weight: 600;
    font-size: 0.95rem;
}
.custom-table-container {
    margin-top: 15px;
    margin-bottom: 25px;
    border-radius: 8px;
    overflow-x: auto;
    border: 1px solid #334155;
}
.custom-table {
    width: 100%;
    font-size: 0.95rem;
    border-collapse: collapse;
}
.custom-table th {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 12px 14px;
    text-align: left;
    font-weight: 600;
    border-bottom: 2px solid #334155;
    white-space: nowrap;
}
.custom-table td {
    padding: 12px 14px;
    border-bottom: 1px solid #334155;
    color: #e2e8f0;
    white-space: nowrap;
}
.custom-table tr:hover {
    background-color: rgba(59,130,246,0.05);
}
@media (max-width: 768px) {
    .header { padding: 6px 10px; margin-bottom: 10px; border-radius: 8px; }
    .header-title { font-size: 0.85rem !important; font-weight: 600; }
    .header-meta { gap: 4px; margin-top: 2px; }
    .status-pill { padding: 1px 6px; font-size: 0.6rem; }
    .header-time { font-size: 0.6rem; }
    .buy-score-number { font-size: 2rem; }
    .buy-score-label { font-size: 0.9rem; }
    .buy-score-sub-value { font-size: 0.75rem; }
    .buy-score { padding: 14px 10px; }
    .card { padding: 12px; }
    .custom-table { font-size: 0.7rem; }
    .custom-table th, .custom-table td { padding: 5px 6px; }
    .snapshot-grid { grid-template-columns: 1fr; }
}
</style>
""", unsafe_allow_html=True)

# ── Session State Init ────────────────────────────────

if 'symbol' not in st.session_state:
    st.session_state.symbol = 'QQQ'

# ── Symbol Selector ────────────────────────────────────

sym_index = 0 if st.session_state.symbol == 'QQQ' else 1
symbol = st.radio("Select Symbol", ["QQQ", "SPY"], index=sym_index, horizontal=True, label_visibility="collapsed")
if symbol != st.session_state.symbol:
    st.session_state.symbol = symbol
    st.rerun()

current_symbol = st.session_state.symbol

# ── Init ───────────────────────────────────────────────

db.init_db()
tc = TradierClient()
pipeline = DataPipeline()

# ── Time Vars ──────────────────────────────────────────

tz_ct = pytz.timezone("America/Chicago")
today_ct = datetime.now(tz_ct)
today_ct_str = today_ct.strftime("%Y-%m-%d")
now_et = datetime.now(pytz.timezone("America/New_York"))
now_et_str = now_et.strftime("%Y-%m-%d %H:00")
ten_weeks_str = (today_ct + timedelta(weeks=10)).strftime("%Y-%m-%d")
vol_label = SYMBOL_CONFIG[current_symbol]["vol_label"]

# ── Pre-fetch Both Symbols' Expirations ────────────────

def fetch_and_filter_expirations(sym):
    all_exps = tc.get_option_expirations(sym)
    return sorted([
        e for e in all_exps
        if today_ct_str <= e <= ten_weeks_str
        and datetime.strptime(e, "%Y-%m-%d").weekday() == 4
    ])

if 'qqq_expirations' not in st.session_state:
    with st.spinner("Fetching QQQ expirations..."):
        st.session_state.qqq_expirations = fetch_and_filter_expirations("QQQ")

if 'spy_expirations' not in st.session_state:
    with st.spinner("Fetching SPY expirations..."):
        st.session_state.spy_expirations = fetch_and_filter_expirations("SPY")

expirations = st.session_state[f'{current_symbol.lower()}_expirations']

# ── Live Data ──────────────────────────────────────────

quote = tc.get_quote(current_symbol)
price = float(quote.get("last", 0) or 0)

vol_val = 20.0
vol_ratio = 1.0
try:
    vol_ticker = yf.Ticker(SYMBOL_CONFIG[current_symbol]["vol_ticker"])
    vol_df = vol_ticker.history(period="3mo")
    if not vol_df.empty:
        close = vol_df["Close"]
        vol_val = float(close.iloc[-1])
        dma20 = close.rolling(20, min_periods=5).mean().iloc[-1]
        vol_ratio = vol_val / dma20 if dma20 > 0 else 1.0
except Exception:
    pass


# ── Sidebar ────────────────────────────────────────────

today_date = datetime.now().date()

sell_default, buy_default = find_expiries(expirations) if expirations else (None, None)
sell_default_idx = expirations.index(sell_default) if sell_default and sell_default in expirations else 0

sell_expiry = st.sidebar.selectbox(
    "Sell Expiry",
    options=expirations,
    index=sell_default_idx if expirations else None,
)

buying_options = [e for e in expirations if e > sell_expiry] if sell_expiry else expirations
buy_default_idx = buying_options.index(buy_default) if buy_default and buy_default in buying_options else len(buying_options) - 1

buy_expiry = st.sidebar.selectbox(
    "Buy Expiry",
    options=buying_options,
    index=buy_default_idx if buying_options else None,
)

st.sidebar.markdown("---")
st.sidebar.markdown("##### 📅 Events This Week")

earnings = fetch_earnings_cached()
events = get_events_for_trade(sell_expiry, buy_expiry, buffer_days=EVENT_BUFFER_DAYS, earnings=earnings)

if not events["near_short"] and not events["during_trade"]:
    st.sidebar.markdown(
        "<div style='color: #10b981; font-size: 0.85rem;'>✓ No major events</div>",
        unsafe_allow_html=True,
    )
else:
    for ev in events["near_short"]:
        ev_dt = datetime.strptime(ev["date"], "%Y-%m-%d").date()
        sell_dt = datetime.strptime(sell_expiry, "%Y-%m-%d").date()
        d_before = (sell_dt - ev_dt).days
        st.sidebar.markdown(
            f"<div style='color: #ef4444; font-size: 0.85rem; margin-bottom: 2px;'>"
            f"🔴 {ev['detail']} ({ev['date']}, {d_before}d before short)</div>",
            unsafe_allow_html=True,
        )
    for ev in events["during_trade"]:
        st.sidebar.markdown(
            f"<div style='color: #10b981; font-size: 0.85rem; margin-bottom: 2px;'>"
            f"🟢 {ev['detail']} ({ev['date']})</div>",
            unsafe_allow_html=True,
        )

st.sidebar.markdown("---")
st.sidebar.markdown("##### Strike Configuration")

lower_cushion = int(st.sidebar.number_input(
    "Lower Cushion ($)", min_value=-100, max_value=100, value=5, step=5,
))
middle_cushion = int(st.sidebar.number_input(
    "Middle Cushion ($)", min_value=-100, max_value=100, value=0, step=5,
))
upper_cushion = int(st.sidebar.number_input(
    "Upper Cushion ($)", min_value=-100, max_value=100, value=5, step=5,
))

st.sidebar.markdown("---")

if st.sidebar.button("Refresh Data", width='stretch'):
    st.rerun()

# ── Main Header ────────────────────────────────────────

market_open = is_market_open_ct()
status_class = "status-active" if market_open else "status-closed"
status_text = "Market Open" if market_open else "Market Closed"

st.markdown(f"""
<div class="header">
    <h1 class="header-title">Triple Calendar Scanner</h1>
    <div class="header-meta">
        <span class="status-pill {status_class}">{status_text}</span>
        <span class="header-time">Last updated: {datetime.now(tz_ct).strftime('%b %d, %Y %I:%M %p CT')}</span>
    </div>
</div>
""", unsafe_allow_html=True)

sell_dte = (datetime.strptime(sell_expiry, "%Y-%m-%d").date() - today_date).days
buy_dte = (datetime.strptime(buy_expiry, "%Y-%m-%d").date() - today_date).days
st.markdown(f"""
<div style="display:flex;gap:16px;justify-content:center;margin:-8px 0 10px 0;font-size:0.8rem;color:#94a3b8;">
    <span>Sell: <b style="color:#f8fafc;">{sell_expiry}</b> ({sell_dte}d)</span>
    <span>Buy: <b style="color:#f8fafc;">{buy_expiry}</b> ({buy_dte}d)</span>
</div>
""", unsafe_allow_html=True)

if not expirations or not sell_expiry or not buy_expiry:
    st.warning("No option expirations available. Data may not be loaded yet.")
    st.stop()

# ── Compute Strikes ────────────────────────────────────

chain_sell = tc.get_option_chain(current_symbol, sell_expiry, greeks=True)
sell_map = {f"{int(o['strike'])}_{o['option_type']}": o for o in chain_sell}
sell_strikes = sorted(set(float(o["strike"]) for o in chain_sell))

multiples_5 = [s for s in sell_strikes if int(s) % 5 == 0]
atm_strike = int(min(multiples_5, key=lambda x: abs(x - price))) if multiples_5 else int(round(price / 5.0) * 5)

atm_sell_call = sell_map.get(f"{atm_strike}_call")
atm_sell_put = sell_map.get(f"{atm_strike}_put")

if atm_sell_call and atm_sell_put:
    call_mid = (float(atm_sell_call.get("bid", 0) or 0) + float(atm_sell_call.get("ask", 0) or 0)) / 2.0
    put_mid = (float(atm_sell_put.get("bid", 0) or 0) + float(atm_sell_put.get("ask", 0) or 0)) / 2.0
else:
    call_mid = put_mid = 0.0

straddle = call_mid + put_mid
rounded_cost = compute_rounded_cost(straddle)

lower_strike, middle_strike, upper_strike = compute_strikes(atm_strike, rounded_cost, lower_cushion, middle_cushion, upper_cushion)

# ── OSI Symbols ────────────────────────────────────────

def make_osi(exp, opt_type, strike):
    return utils.format_osi(current_symbol, exp, opt_type, strike)

current_legs = [
    make_osi(sell_expiry, "P", lower_strike),
    make_osi(buy_expiry, "P", lower_strike),
    make_osi(sell_expiry, "P", middle_strike),
    make_osi(buy_expiry, "P", middle_strike),
    make_osi(sell_expiry, "C", upper_strike),
    make_osi(buy_expiry, "C", upper_strike),
]

# ── Load Historical Data ──────────────────────────────

df_hist = pipeline.get_historical_strategy_data(
    symbol=current_symbol,
    sell_expiry=sell_expiry,
    buy_expiry=buy_expiry,
    lower_cushion=lower_cushion,
    middle_cushion=middle_cushion,
    upper_cushion=upper_cushion,
)

# Collect all unique OSI symbols for PnL computation
all_osi = set(current_legs)
if not df_hist.empty:
    for _, row in df_hist.iterrows():
        for exp in (sell_expiry, buy_expiry):
            all_osi.add(make_osi(exp, "P", int(row["lower_strike"])))
            all_osi.add(make_osi(exp, "P", int(row["middle_strike"])))
            all_osi.add(make_osi(exp, "C", int(row["upper_strike"])))

# ── Fetch Live Quotes ─────────────────────────────────

quotes = {}
with st.spinner("Fetching live quotes..."):
    try:
        quotes = tc.get_quotes(sorted(all_osi), greeks=True)
    except Exception:
        pass

def get_mid(sym):
    q = quotes.get(sym, {})
    bid = float(q.get("bid", 0) or 0)
    ask = float(q.get("ask", 0) or 0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return float(q.get("last", 0) or 0)

# ── Compute Current Cost & Buy Score (live) ──────────

l_cost = max(0, get_mid(current_legs[1]) - get_mid(current_legs[0]))
m_cost = max(0, get_mid(current_legs[3]) - get_mid(current_legs[2]))
u_cost = max(0, get_mid(current_legs[5]) - get_mid(current_legs[4]))
total_cost = l_cost + m_cost + u_cost

vol_cost_ratio = vol_val / total_cost if total_cost > 0 else 0.0

avg_iv_ratio = None
leg_ratios = []
for i in range(0, 6, 2):
    sq = quotes.get(current_legs[i])
    lq = quotes.get(current_legs[i + 1])
    if sq and lq:
        iv_s = sq.get("greeks", {}).get("mid_iv")
        iv_l = lq.get("greeks", {}).get("mid_iv")
        if iv_s is not None and iv_l is not None and iv_l > 0:
            leg_ratios.append(iv_s / iv_l)
if len(leg_ratios) >= 2:
    avg_iv_ratio = sum(leg_ratios) / len(leg_ratios)

score, label, score_color = calculate_score(df_hist, total_cost, vol_ratio, sell_expiry, buy_expiry, current_iv_ratio=avg_iv_ratio, current_rounded_cost=rounded_cost, symbol=current_symbol)

iv_pctile_val = None
if "iv_ratio_percentile" in df_hist.columns:
    last = df_hist["iv_ratio_percentile"].dropna()
    if not last.empty:
        iv_pctile_val = f"{int(last.iloc[-1])}%"

iv_ratio_display = f"{avg_iv_ratio:.4f}" if avg_iv_ratio is not None else "—"
iv_pctile_display = iv_pctile_val if iv_pctile_val else "—"

# ── Display: Buy Score Card ───────────────────────────

if score is None:
    st.markdown(f"""
<div class="card buy-score">
    <div class="buy-score-number" style="color: #6b7280;">—</div>
    <div class="buy-score-label" style="color: #6b7280;">Incomplete</div>
    <div class="buy-score-sub">
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">Total Cost</div>
            <div class="buy-score-sub-value">${total_cost:.2f}</div>
        </div>
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">{vol_label}</div>
            <div class="buy-score-sub-value">{vol_val:.2f}</div>
        </div>
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">IV Ratio</div>
            <div class="buy-score-sub-value">{iv_ratio_display}</div>
        </div>
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">IV %ile</div>
            <div class="buy-score-sub-value">{iv_pctile_display}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)
else:
    st.markdown(f"""
<div class="card buy-score">
    <div class="buy-score-number" style="color: {score_color};">{score:.0f}</div>
    <div class="buy-score-label" style="color: {score_color};">{label}</div>
    <div class="buy-score-sub">
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">Total Cost</div>
            <div class="buy-score-sub-value">${total_cost:.2f}</div>
        </div>
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">{vol_label}</div>
            <div class="buy-score-sub-value">{vol_val:.2f}</div>
        </div>
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">IV Ratio</div>
            <div class="buy-score-sub-value">{iv_ratio_display}</div>
        </div>
        <div class="buy-score-sub-item">
            <div class="buy-score-sub-label">IV %ile</div>
            <div class="buy-score-sub-value">{iv_pctile_display}</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Display: Market Snapshot ──────────────────────────

st.markdown("""
<div class="card">
    <div class="card-title">📈 Market Snapshot</div>
    <div class="snapshot-grid">
""", unsafe_allow_html=True)

for lbl, val in [
    (current_symbol, f"${price:.2f}"),
    (vol_label, f"{vol_val:.2f}"),
    ("ATM Strike", f"${atm_strike}"),
    ("ATM Straddle", f"${straddle:.2f}"),
    ("Rounded Cost", f"${rounded_cost}"),
]:
    st.markdown(f"<div class='snapshot-item'><span class='snapshot-label'>{lbl}</span><span class='snapshot-value'>{val}</span></div>", unsafe_allow_html=True)

st.markdown(f"""
    </div>
    <div style="margin-top:12px;padding-top:12px;border-top:1px solid #334155;">
        <span style="color:#64748b;font-size:0.85rem;">Strikes: </span>
        <span style="color:#f8fafc;font-weight:600;font-size:1rem;">${lower_strike} / ${middle_strike} / ${upper_strike}</span>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Display: Events This Week ──────────────────────────

if events["near_short"] or events["during_trade"]:
    parts = []
    for ev in events["near_short"]:
        parts.append(f"🔴 {ev['detail']} {ev['date']}")
    for ev in events["during_trade"]:
        parts.append(f"🟢 {ev['detail']} {ev['date']}")
    st.markdown(
        f"<div style='color: #94a3b8; font-size: 0.8rem; padding: 4px 0 16px 0;'>"
        f"📅 Events: {', '.join(parts)}</div>",
        unsafe_allow_html=True,
    )

# ── Display: Historical Snapshots ────────────────────

st.markdown("### 📅 Historical Snapshots")

if df_hist.empty:
    st.info("No historical data yet. Data accumulates from dashboard loads and scheduled scrapes.")
else:
    tz_et = pytz.timezone("America/New_York")
    unique_dates = sorted(set(t.split()[0] for t in df_hist["timestamp"]), reverse=True)
    last_10 = set(unique_dates[:10])
    df_recent = df_hist[df_hist["timestamp"].apply(lambda t: t.split()[0] in last_10)]
    day_records = defaultdict(list)
    df_recent_rev = df_recent.iloc[::-1]

    for _, row in df_recent_rev.iterrows():
        ts = row["timestamp"]
        ts_et = tz_et.localize(datetime.strptime(ts, "%Y-%m-%d %H:00"))
        ts_ct = ts_et.astimezone(tz_ct)
        if ts == now_et_str and datetime.now(tz_et).minute < 5:
            continue
        date_part = ts_ct.strftime("%Y-%m-%d")
        hour_part = ts_ct.strftime("%H:00")

        qv = row["qqq_close"]
        av = row["atm_strike"]
        lk = row["lower_strike"]
        mk = row["middle_strike"]
        uk = row["upper_strike"]
        cv = row["total_strategy_cost"]
        vv = row["vix_close"]

        s_val = row.get("buy_score")
        l_val = row.get("buy_label")
        if s_val is not None and not pd.isna(s_val):
            c_val = "#10b981" if s_val >= 80 else "#f59e0b" if s_val >= 40 else "#ef4444"
            l_val = l_val or "Neutral"
        else:
            s_val = None
            l_val = "Incomplete"
            c_val = "#6b7280"

        cv_valid = cv is not None and not (isinstance(cv, float) and np.isnan(cv))

        ratio = vv / cv if cv_valid and cv > 0 else 0.0

        ll_s = get_mid(make_osi(sell_expiry, "P", int(lk)))
        ll_b = get_mid(make_osi(buy_expiry, "P", int(lk)))
        mm_s = get_mid(make_osi(sell_expiry, "P", int(mk)))
        mm_b = get_mid(make_osi(buy_expiry, "P", int(mk)))
        uu_s = get_mid(make_osi(sell_expiry, "C", int(uk)))
        uu_b = get_mid(make_osi(buy_expiry, "C", int(uk)))

        cur_val = max(0, ll_b - ll_s) + max(0, mm_b - mm_s) + max(0, uu_b - uu_s)
        if cv_valid and cv > 0:
            pnl_d = cur_val - cv
            pnl_p = pnl_d / cv * 100.0
            pnl_s = f"{pnl_p:+.1f}%" if pnl_p != 0 else f"{pnl_p:.1f}%"
        else:
            pnl_s = "—"

        ivr = row.get("avg_iv_ratio")
        ivr_s = f"{ivr:.4f}" if ivr is not None and not pd.isna(ivr) else "—"
        ivp = row.get("iv_ratio_percentile")
        ivp_s = f"{int(ivp)}" if ivp is not None and not pd.isna(ivp) else "—"

        day_records[date_part].append({
            "Hour": hour_part,
            "Underlying": f"${qv:.2f}" if qv and not pd.isna(qv) else "N/A",
            "ATM Strike": f"${av:.0f}" if av and not pd.isna(av) else "N/A",
            "Strikes (L / M / U)": f"${lk:.0f} / ${mk:.0f} / ${uk:.0f}",
            "Total Cost": f"${cv:.2f}" if cv_valid else "—",
            "IV Ratio (Sell/Buy)": ivr_s,
            "IV Ratio %ile": ivp_s,
            "Current Value": f"${cur_val:.2f}",
            vol_label: f"{vv:.2f}" if vv and not pd.isna(vv) else "N/A",
            "Current PnL": pnl_s,
            "Buy Score": f"<span style='color:{c_val};font-weight:600;'>{s_val:.0f} ({l_val})</span>" if s_val is not None else f"<span style='color:#6b7280;font-weight:600;'>— ({l_val})</span>",
            "Vol/Cost Ratio": f"{ratio:.3f}" if cv_valid and cv > 0 else "—",
            "_raw_cost": cv,
            "_raw_score": s_val,
        })

    sorted_dates = sorted(day_records.keys(), reverse=True)
    for d_str in sorted_dates:
        rows = day_records[d_str]
        valid_costs = [r["_raw_cost"] for r in rows if r["_raw_cost"] > 0]
        valid_scores = [r["_raw_score"] for r in rows if r["_raw_score"] is not None]
        avg_cost = sum(valid_costs) / len(valid_costs) if valid_costs else 0.0

        if not valid_scores:
            score_emoji = "⚪"
            sl = "Incomplete"
            avg_score = None
        else:
            avg_score = sum(valid_scores) / len(valid_scores)
            if avg_score >= 80:
                score_emoji = "🟢"
                sl = "Strong Buy"
            elif avg_score >= 40:
                score_emoji = "🟡"
                sl = "Neutral"
            else:
                score_emoji = "🔴"
                sl = "Avoid"

        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            date_label = dt.strftime("%b %d, %Y (%A)")
        except Exception:
            date_label = d_str

        cost_str = f"${avg_cost:.2f}" if valid_costs else "—"
        hdr = f"📅 {date_label} | Avg Score: {score_emoji} {avg_score:.0f} ({sl}) | Avg Cost: {cost_str}" if avg_score is not None else f"📅 {date_label} | Avg Score: ⚪ Incomplete | Avg Cost: {cost_str}"
        is_today = (d_str == today_ct_str)

        with st.expander(hdr, expanded=is_today):
            clean = [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]
            cols = [
                "Hour", "Buy Score", "Total Cost",
                "IV Ratio (Sell/Buy)", "IV Ratio %ile",
                vol_label, "Underlying", "ATM Strike",
                "Strikes (L / M / U)", "Current Value",
                "Vol/Cost Ratio", "Current PnL",
            ]
            df_day = pd.DataFrame(clean, columns=cols)
            render_hourly_table(df_day)

# ── Display: Alerts ──────────────────────────────────

st.markdown("### 🔔 Alerts")
alerts = db.get_recent_alerts(limit=20, symbol=current_symbol)
if alerts:
    alert_rows = []
    for a in alerts:
        alert_rows.append({
            "Symbol": a["symbol"],
            "Date": a.get("created_at", "")[:19],
            "Score": f"{a.get('score', 0):.0f}",
            "Label": a.get("label", ""),
            "Cost": f"${a.get('total_cost', 0):.2f}",
            "Vol Index": f"{a.get('vix', 0):.2f}",
            "Underlying": f"${a.get('underlying_price', 0):.2f}",
            "IV Ratio": f"{a.get('iv_ratio', 0):.4f}",
            "Strikes": f"${a.get('lower_strike', 0):.0f} / ${a.get('middle_strike', 0):.0f} / ${a.get('upper_strike', 0):.0f}",
        })
    st.dataframe(pd.DataFrame(alert_rows), width='stretch', hide_index=True)
else:
    st.markdown("<div style='color:#94a3b8;'>No alerts yet.</div>", unsafe_allow_html=True)
