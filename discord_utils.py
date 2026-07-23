import config
import os
import json
import urllib.request
from datetime import datetime

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



def build_candidate_block(v):
    wr = f"{v.get('strategy_win_rate', 0):.1f}%" if v.get('strategy_win_rate') else "N/A"
    session_short = "AMC" if "AMC" in v['session'] else "BMO"
    exp_date = datetime.strptime(v['expiration_yymmdd'], '%y%m%d').strftime('%b %d')

    align = v.get('alignment', 0)
    badge = "✅ Pass" if align >= -0.1 else "⚠️ Pass (Contrarian)"

    block = (
        f"**{v['ticker']}** · {v.get('company_name', v['ticker'])} · {v['strategy']} · {session_short} {exp_date}\n"
        f"\n"
        f"  • Entry: ${v['price']:.2f}  • Credit: ${v['est_credit']:.2f}  • Risk: ${v['margin']:.0f}\n"
    )

    if v['short_put'] and v['short_call']:
        block += f"  • Sell ${v['short_put']}/{v['long_put']} put + ${v['short_call']}/{v['long_call']} call\n"
    elif v['short_put']:
        block += f"  • Sell ${v['short_put']} put / Buy ${v['long_put']} put\n"
    elif v['short_call']:
        block += f"  • Sell ${v['short_call']} call / Buy ${v['long_call']} call\n"

    block += f"  • Expected move: ±{v['implied_move']:.2f}%  • Historical: ±{v['hist_move']:.2f}%\n"
    block += f"  • {badge}  • Sim win rate: {wr}\n"

    c = v.get('consensus', {})
    upside = v.get('target_upside')
    if c.get('recommendation'):
        rec = c['recommendation'].replace('_', ' ').title()
        rm = f" ({c['recommendation_mean']:.2f})" if c.get('recommendation_mean') else ""
        pt = f"${c['target_mean']:.2f}" if c.get('target_mean') else "N/A"
        us = f" ({upside:+.1f}%)" if upside is not None else ""
        ac = f" ({int(c['analyst_count'])} analysts)" if c.get('analyst_count') else ""
        block += f"  • Street says: {rec}{rm} → {pt}{us}{ac}\n"

    vol_parts = []
    cv, coi, pv, poi = v.get('call_volume'), v.get('call_open_interest'), v.get('put_volume'), v.get('put_open_interest')
    if any(x is not None for x in [cv, coi, pv, poi]):
        fmt = lambda x: f"{x:,}" if x is not None else "?"
        vol_parts.append(f"Call Vol/OI: {fmt(cv)}/{fmt(coi)}")
        vol_parts.append(f"Put Vol/OI: {fmt(pv)}/{fmt(poi)}")
        block += f"  • {'  • '.join(vol_parts)}\n"

    analyst_calls = v.get('analyst_calls', [])
    if analyst_calls:
        c = analyst_calls[0]
        block += f"\n🔬 {c['date']}: {c['summary']}"
    return block


def send_afternoon_advisory(date_str, candidates, viable, skipped):
    def send(content):
        payload = {"username": "Earnings Trading Bot", "content": content}
        return send_discord_payload(payload)

    if not viable and not candidates:
        return send("No upcoming earnings candidates found for today AMC or tomorrow BMO.\n")

    if not viable:
        skip_summary = "\n".join(f"• {t}: {r}" for t, r in skipped[:5])
        if len(skipped) > 5:
            skip_summary += f"\n...and {len(skipped)-5} more"
        return send(f"Evaluated {len(candidates)} candidate(s), but none passed filters.\n\n**Skipped:**\n{skip_summary}")

    # Build viable blocks
    blocks = [build_candidate_block(v) for v in viable]

    # Send viable in chunks that fit Discord's 1900 char limit
    header = f"Found {len(viable)} actionable trade(s) for today AMC / tomorrow BMO:\n"
    sent = False
    chunk = []
    chunk_len = len(header)
    for block in blocks:
        block_len = len(block) + 4  # separator
        if chunk and chunk_len + block_len > 1850:
            body = header + "\n---\n".join(chunk)
            send(body)
            header = ""  # only first message gets header
            chunk = []
            chunk_len = 0
        chunk.append(block)
        chunk_len += block_len
    if chunk:
        body = header + "\n---\n".join(chunk) if header else "\n---\n".join(chunk)
        send(body)

    # Send skipped as follow-up
    if skipped:
        skip_summary = "\n".join(f"• {t}: {r}" for t, r in skipped[:10])
        if len(skipped) > 10:
            skip_summary += f"\n...and {len(skipped)-10} more"
        send(f"**Skipped:**\n{skip_summary}")

    return True


def send_weekly_preview(weekly_groups):
    parts = ["📋 **Earnings Preview — Week Ahead**\n"]
    for day_header, stocks in weekly_groups:
        parts.append(f"**{day_header}**")
        for s in stocks:
            wr = f"{s['win_rate']:.0f}%" if s['win_rate'] else "N/A"
            flag = " ⚠️" if s['win_rate'] and s['win_rate'] < 70 else ""
            trade_date = s.get('trade_date_str', '')
            trade_info = f" → Trade {trade_date}" if trade_date else ""
            parts.append(
                f"  • {s['ticker']:6s} ${s['price']:.0f}  "
                f"· ±{s['hist_abs']:.1f}% / {s['hist_net']:+.1f}%  "
                f"· {s['strategy']} {wr}{flag}{trade_info}"
            )
        parts.append("")

    body = "\n".join(parts) + (
        "🔔 **Daily advisories** at 1 PM CT Mon-Fri for edge check.\n"
        "*Strategy @ 5% OTM backtest, net for reference. ⚠️ = <70% win rate.*"
    )

    if len(body) > 1900:
        body = body[:1900] + "\n\n*(truncated)*"

    payload = {
        "username": "Earnings Trading Bot",
        "content": body
    }
    return send_discord_payload(payload)
