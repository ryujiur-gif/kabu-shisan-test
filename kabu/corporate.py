"""配当と株式分割（併合）の反映。

- 配当：権利落ち日に、その前日まで持っていた株数 × 1株配当 を現金に加える（税引き前。税は「税引き後の概算」で引く）。
- 分割：権利落ち日に株数を増やし、取得単価を下げる（取得額の合計は変えない）。
記録は trades.csv に「配当」「分割」の行として残す（kabu.ledger.replay がたどり直せる）。
"""
from datetime import date, timedelta


def fetch_actions(code: str, start: date, end: date) -> list[dict]:
    """start〜end（両端を含む）の権利落ち日の配当・分割を返す。[{date, type, value}]"""
    import yfinance as yf
    df = yf.Ticker(f"{code}.T").actions
    out = []
    if df is None or len(df) == 0:
        return out
    for idx, row in df.iterrows():
        d = idx.date()
        if not (start <= d <= end):
            continue
        div = float(row.get("Dividends", 0) or 0)
        sp = float(row.get("Stock Splits", 0) or 0)
        if div > 0:
            out.append({"date": d.isoformat(), "type": "配当", "value": div})
        if sp > 0 and abs(sp - 1) > 1e-9:
            out.append({"date": d.isoformat(), "type": "分割", "value": sp})
    return out


def collect(codes: list[str], start: date, end: date, fetch=None) -> tuple[dict, list[str]]:
    """銘柄ごとの配当・分割を集める。戻り値は ({日付: [(コード, 種類, 値)]}, 取得に失敗したコード)。"""
    fetch = fetch or fetch_actions
    by_date, failed = {}, []
    if start > end:
        return by_date, failed
    for code in dict.fromkeys(codes):
        try:
            acts = fetch(code, start, end)
        except Exception:
            failed.append(code)
            continue
        for a in acts or []:
            by_date.setdefault(a["date"], []).append((code, a["type"], float(a["value"])))
    return by_date, failed


def eligible_shares(trades: list[dict], code: str, ex_date: str) -> int:
    """権利落ち日の前日まで持っていた株数（権利落ち日より前の取引だけで数える）。"""
    from kabu.ledger import replay
    h = replay([t for t in trades if t["date"] < ex_date]).get("holdings", {}).get(code)
    return h["shares"] if h else 0


def apply(state: dict, trades: list[dict], ex_date: str, actions: list[tuple]) -> list[dict]:
    """ex_date の配当・分割を state に反映し、記録する行を返す（state は書き換える）。"""
    from kabu.ledger import apply_split
    rows = []
    for code, kind, value in actions:
        h = state["holdings"].get(code)
        n = min(eligible_shares(trades + rows, code, ex_date), h["shares"] if h else 0)
        if not h or n <= 0:
            continue
        if kind == "配当":
            amount = int(n * value)
            state["cash"] += amount
            rows.append({"date": ex_date, "side": "配当", "code": code, "name": h["name"], "shares": n,
                         "price": round(value, 4), "amount": amount, "status": "入金",
                         "reason": f"配当（1株 {value:g}円・権利落ち日 {ex_date}）"})
        elif kind == "分割":
            old = h["shares"]
            new = apply_split(h, n, value)
            rows.append({"date": ex_date, "side": "分割", "code": code, "name": h["name"], "shares": new,
                         "price": round(new / old, 6) if old else value, "amount": 0, "status": "調整",
                         "reason": f"株式分割・併合（1株→{value:g}株・{old:,}株→{new:,}株）"})
            if new <= 0:
                del state["holdings"][code]
            for key in ("last_closes",):   # 前回終値も新しい株数に合わせる
                if code in state.get(key, {}) and old and new:
                    state[key][code] = state[key][code] * old / new
    return rows


def day_after(d: str) -> date:
    return date.fromisoformat(d) + timedelta(days=1)
