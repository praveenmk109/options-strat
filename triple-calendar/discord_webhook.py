import os
from datetime import datetime
import pytz

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")


def send_embed(title: str, fields: list, color: int = 0x00ff00):
    if not WEBHOOK_URL:
        return
    try:
        import requests
        payload = {
            "embeds": [{
                "title": title,
                "color": color,
                "fields": fields,
                "footer": {"text": f"Triple Calendar Agent \u2022 {datetime.now(pytz.timezone('America/New_York')).strftime('%b %d, %I:%M %p ET')}"}
            }]
        }
        requests.post(WEBHOOK_URL, json=payload, timeout=5)
    except Exception as e:
        print(f"Discord embed failed: {e}")


def send_entry_alert(symbol: str, score: float, label: str, cost: float, vol_index: float,
                     underlying_price: float, ratio: float, sell_expiry: str, buy_expiry: str,
                     lower: float, middle: float, upper: float,
                     iv_ratio: float = None, iv_percentile: float = None,
                     events_summary: str = None):
    vol_label = {"QQQ": "VXN", "SPY": "VIX"}.get(symbol, "VIX")
    color = 0x10b981 if score >= 80 else (0xf59e0b if score >= 40 else 0xef4444)

    lines = [
        f"Score:        {score:.0f}/100 ({label})",
        f"Cost:         ${cost:.2f}",
        f"{vol_label}:         {vol_index:.2f}%",
        f"{symbol}:       ${underlying_price:.2f}",
        f"Strikes:      ${lower:.0f} / ${middle:.0f} / ${upper:.0f}",
        f"Expiries:     Sell {sell_expiry} | Buy {buy_expiry}",
    ]
    if iv_ratio is not None:
        lines.insert(3, f"IV Ratio:     {iv_ratio:.4f}")
    if iv_percentile is not None:
        lines.insert(4, f"IV %ile:      {iv_percentile:.0f}%")
    if events_summary:
        lines.append(f"Events:       {events_summary}")

    send_embed(
        f"{symbol} Triple Calendar Entry Signal (Score: {score:.0f}/100 \u2014 {label})",
        fields=[{"name": "Details", "value": "```\n" + "\n".join(lines) + "\n```"}],
        color=color
    )
