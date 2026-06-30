import config
import os
import json
import urllib.request
from datetime import datetime, timezone

WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")

def send_discord_payload(payload):
    """
    Sends a JSON payload to the Discord Webhook URL.
    Falls back to console prints if the Webhook URL is not set.
    """
    if not WEBHOOK_URL:
        print("[WARNING] DISCORD_WEBHOOK_URL not configured. Message content:")
        print(json.dumps(payload, indent=2))
        return False
        
    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            WEBHOOK_URL,
            data=data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Mozilla/5.0'
            }
        )
        with urllib.request.urlopen(req) as response:
            if response.status == 204:
                return True
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")
    return False

def send_trade_execution(ticker, strategy, details):
    """
    Sends an alert when a trade is automatically entered on Alpaca.
    """
    fields = [
        {"name": "Ticker", "value": ticker, "inline": True},
        {"name": "Strategy", "value": strategy, "inline": True},
        {"name": "Order ID", "value": details.get("order_id", "N/A"), "inline": True},
        {"name": "Put Strikes", "value": details.get("put_strikes", "N/A"), "inline": True},
        {"name": "Call Strikes", "value": details.get("call_strikes", "N/A"), "inline": True},
        {"name": "Est. Credit", "value": f"${details.get('credit', 0.0):.2f}", "inline": True},
        {"name": "Implied Move", "value": f"{details.get('implied_move', 0.0):.2f}%", "inline": True},
        {"name": "Historical Move", "value": f"{details.get('hist_move', 0.0):.2f}%", "inline": True},
        {"name": "Capital Allocation", "value": f"${details.get('margin', 0.0):.2f}", "inline": True}
    ]
    
    payload = {
        "username": "Earnings Trading Bot",
        "embeds": [{
            "title": f"🚀 Trade Executed: {ticker} {strategy}",
            "description": f"Successfully placed defined-risk options credit spread order on Alpaca paper trading.",
            "color": 3066993, # Green
            "fields": fields,
            "footer": {
                "text": "Execution triggers daily at 2:00 PM CT"
            },
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }]
    }
    return send_discord_payload(payload)

def send_trade_review(date_str, results_summary, trades_detail):
    """
    Sends the next-day review Embed with closed trade details, P&L, and threshold adjustments.
    """
    # Build summary description
    total_trades = len(trades_detail)
    wins = sum(1 for t in trades_detail if t['pnl'] >= 0)
    total_pnl = sum(t['pnl'] for t in trades_detail)
    
    description = (
        f"**Closed Trades**: {total_trades}\n"
        f"**Win Rate**: {wins}/{total_trades} ({ (wins/total_trades*100) if total_trades > 0 else 0:.1f}%)\n"
        f"**Daily P&L**: **${total_pnl:+.2f}**\n\n"
        "**Trade Breakdowns:**"
    )
    
    fields = []
    for t in trades_detail:
        pnl_str = f"${t['pnl']:+.2f}"
        details_val = (
            f"**Realized Gap**: {t['realized_gap']:.2f}% (Expected: {t['implied_gap']:.2f}%)\n"
            f"**Strikes**: Put: {t['put_strikes']} | Call: {t['call_strikes']}\n"
            f"**P&L**: **{pnl_str}**\n"
            f"**Threshold**: {t['multiplier_change']}"
        )
        fields.append({
            "name": f"{'✅' if t['pnl'] >= 0 else '❌'} {t['ticker']} - {t['strategy']}",
            "value": details_val,
            "inline": False
        })
        
    payload = {
        "username": "Earnings Trading Bot",
        "embeds": [{
            "title": f"📊 Daily Earnings Performance Review - {date_str}",
            "description": description,
            "color": 8359053 if total_pnl >= 0 else 15158332, # Grey/Green if flat/up, Red if down
            "fields": fields,
            "footer": {
                "text": "Performance review runs daily at 8:45 AM CT"
            },
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }]
    }
    return send_discord_payload(payload)

def send_error_alert(error_message):
    """
    Sends an error notification if the automated system encounters a problem.
    """
    payload = {
        "username": "Earnings Trading Bot",
        "embeds": [{
            "title": "⚠️ System Error Encountered",
            "description": f"The automated earnings system encountered an execution error:\n```\n{error_message}\n```",
            "color": 15158332, # Red
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }]
    }
    return send_discord_payload(payload)

def send_afternoon_advisory(date_str, candidates, viable, skipped):
    if viable:
        description = f"Found {len(viable)} actionable trade(s) for today AMC / tomorrow BMO:"
        color = 3066993
    elif candidates:
        description = f"Evaluated {len(candidates)} candidate(s), but none passed filters. See skipped details below."
        color = 15158332
    else:
        description = "No upcoming earnings candidates found for today AMC or tomorrow BMO."
        color = 3447003

    fields = []
    for v in viable:
        put_str = f"${v['short_put']}/{v['long_put']}" if v['short_put'] else "None"
        call_str = f"${v['short_call']}/{v['long_call']}" if v['short_call'] else "None"
        eps_line = ""
        if v['eps_estimate'] is not None and v['eps_reported'] is not None:
            s = v['eps_surprise']
            surprise_str = f"({s:+.1f}%)" if s is not None else ""
            eps_line = f"\n**Last EPS**: Est ${v['eps_estimate']:.2f} vs ${v['eps_reported']:.2f} {surprise_str}"
        vol_line = ""
        cv, coi, pv, poi = v['call_volume'], v['call_open_interest'], v['put_volume'], v['put_open_interest']
        if any(x is not None for x in [cv, coi, pv, poi]):
            cv_s = f"{cv:,}" if cv is not None else "?"
            coi_s = f"{coi:,}" if coi is not None else "?"
            pv_s = f"{pv:,}" if pv is not None else "?"
            poi_s = f"{poi:,}" if poi is not None else "?"
            vol_line = f"\n**Call Vol/OI**: {cv_s}/{coi_s}  **Put Vol/OI**: {pv_s}/{poi_s}"
        val = (
            f"**Price**: ${v['price']:.2f} | **Straddle**: ${v['straddle_price']:.2f} (±{v['implied_move']:.2f}%) | **Hist**: {v['hist_move']:.2f}%\n"
            f"**Go/No-Go**: ✅ {v['strategy']} | **Expiry**: {v['expiration_yymmdd']}\n"
            f"**Credit**: ${v['est_credit']:.2f} | **Risk**: ${v['margin']:.2f}\n"
            f"**Strikes**: Put {put_str}  Call {call_str}{vol_line}{eps_line}"
        )
        news_items = v.get('news', [])
        if news_items:
            news_lines = "\n".join(
                f"📰 {n['title']}" + (f" — {n['publisher']}" if n.get('publisher') else "")
                for n in news_items
            )
            val += f"\n{news_lines}"
        fields.append({
            "name": f"✅ {v['ticker']} - {v['strategy']}",
            "value": val,
            "inline": False
        })

    if skipped and viable:
        skip_summary = "\n".join(f"• {t}: {r}" for t, r in skipped[:5])
        if len(skipped) > 5:
            skip_summary += f"\n...and {len(skipped)-5} more"
        fields.append({
            "name": "Skipped",
            "value": skip_summary,
            "inline": False
        })
    elif skipped:
        skip_summary = "\n".join(f"• {t}: {r}" for t, r in skipped[:5])
        if len(skipped) > 5:
            skip_summary += f"\n...and {len(skipped)-5} more"
        fields.append({
            "name": "Evaluated (all skipped)",
            "value": skip_summary,
            "inline": False
        })

    payload = {
        "username": "Earnings Trading Bot",
        "embeds": [{
            "title": "📋 Afternoon Trade Advisory",
            "description": description,
            "color": color,
            "fields": fields,
            "footer": {
                "text": "Advisory runs daily at 2:00 PM CT"
            },
            "timestamp": datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        }]
    }
    return send_discord_payload(payload)
