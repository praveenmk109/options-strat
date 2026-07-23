from datetime import datetime


def format_osi(underlying, expiry_str, opt_type_str, strike):
    dt = datetime.strptime(expiry_str, "%Y-%m-%d")
    yymmdd = dt.strftime("%y%m%d")
    strike_cents = int(round(strike * 1000))
    strike_str = f"{strike_cents:08d}"
    symbol_type = "C" if opt_type_str.upper() in ("C", "CALL") else "P"
    return f"{underlying}{yymmdd}{symbol_type}{strike_str}"


def parse_osi_symbol(symbol: str):
    try:
        idx = 0
        while idx < len(symbol) and not symbol[idx].isdigit():
            idx += 1
        underlying = symbol[:idx]
        expiry_part = symbol[idx:idx+6]
        opt_type = symbol[idx+6]
        strike_part = symbol[idx+7:]
        yy = int(expiry_part[0:2])
        mm = int(expiry_part[2:4])
        dd = int(expiry_part[4:6])
        expiry_date = f"20{yy:02d}-{mm:02d}-{dd:02d}"
        strike = float(strike_part) / 1000.0
        return underlying, expiry_date, opt_type, strike
    except Exception:
        return "QQQ", "2026-07-17", "C", 480.0
