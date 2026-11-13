"""成績の集計：銘柄別の損益・最大下落幅・月別成績・業種ごとの比率・業種別の値動き。"""
from kabu.ledger import START_CASH, _order_key


def per_stock(trades: list[dict], closes: dict | None = None) -> list[dict]:
    """銘柄ごとの損益（確定分・含み分・配当）。損益の合計が大きい順。"""
    closes = closes or {}
    pos = {}
    for t in sorted(trades, key=_order_key):
        code, side = t["code"], t["side"]
        p = pos.setdefault(code, {"code": code, "name": t.get("name", ""), "shares": 0, "cost": 0.0,
                                  "realized": 0.0, "dividend": 0, "bought": 0, "trades": 0})
        if side == "配当":
            p["dividend"] += int(t["amount"])
        elif side == "分割":
            p["shares"] = int(t["shares"])
        elif t.get("status") == "約定" and side == "買":
            p["shares"] += int(t["shares"])
            p["cost"] += int(t["amount"])
            p["bought"] += int(t["amount"])
            p["trades"] += 1
        elif t.get("status") == "約定" and side == "売" and p["shares"] > 0:
            n = min(int(t["shares"]), p["shares"])
            part = p["cost"] * n / p["shares"]
            p["realized"] += int(t["amount"]) - part
            p["cost"] -= part
            p["shares"] -= n
            p["trades"] += 1
    out = []
    for code, p in pos.items():
        if not p["bought"]:
            continue
        px = closes.get(code)
        unreal = (p["shares"] * px - p["cost"]) if p["shares"] and px else 0.0
        total = p["realized"] + unreal + p["dividend"]
        out.append({**p, "realized": int(p["realized"]), "unrealized": int(unreal), "pl": int(total),
                    "pl_pct": round(total / p["bought"] * 100, 2), "holding": p["shares"] > 0})
    return sorted(out, key=lambda x: -x["pl"])


def max_drawdown(hist: list[dict], key: str = "total") -> dict | None:
    """最大下落幅：それまでの最高額からいちばん大きく下がったときの率（%）と日付。"""
    peak, peak_d, worst = None, None, None
    for r in hist:
        v = float(r[key])
        if peak is None or v > peak:
            peak, peak_d = v, r["date"]
        dd = (v / peak - 1) * 100 if peak else 0.0
        if worst is None or dd < worst["pct"]:
            worst = {"pct": round(dd, 2), "peak_date": peak_d, "date": r["date"]}
    return worst


def monthly(hist: list[dict], start: int = START_CASH) -> list[dict]:
    """月ごとの騰落率（予想どおり売買・日経平均）。"""
    out, prev_t, prev_b = [], float(start), float(start)
    months = {}
    for r in hist:
        months[r["date"][:7]] = r   # その月の最後の営業日
    for m in sorted(months):
        r = months[m]
        t, b = float(r["total"]), float(r["benchmark_value"])
        out.append({"month": m, "mine": round((t / prev_t - 1) * 100, 2),
                    "bench": round((b / prev_b - 1) * 100, 2), "total": int(t)})
        prev_t, prev_b = t, b
    return out


def period_change(hist: list[dict], since: str, start: int = START_CASH) -> dict | None:
    """since（その日を含む）以降の騰落率。基準は since の前の営業日の値（無ければ開始資金）。"""
    rows = [r for r in hist if r["date"] >= since]
    if not rows:
        return None
    before = [r for r in hist if r["date"] < since]
    t0 = float(before[-1]["total"]) if before else float(start)
    b0 = float(before[-1]["benchmark_value"]) if before else float(start)
    t1, b1 = float(rows[-1]["total"]), float(rows[-1]["benchmark_value"])
    return {"from": rows[0]["date"], "to": rows[-1]["date"], "days": len(rows),
            "mine": round((t1 / t0 - 1) * 100, 2), "bench": round((b1 / b0 - 1) * 100, 2),
            "total": int(t1), "start_total": int(t0)}


def sector_weights(values: dict, sectors: dict, total: float) -> dict:
    """業種ごとの保有額の比率（総資産比）。values は {コード: 評価額}。"""
    out = {}
    for code, v in values.items():
        s = sectors.get(code) or "その他"
        out[s] = out.get(s, 0.0) + (v / total if total else 0.0)
    return dict(sorted(out.items(), key=lambda x: -x[1]))


def _avg(xs: list[dict], k: str) -> float:
    vals = [x[k] for x in xs if x.get(k) is not None]
    return round(sum(vals) / len(vals), 2) if vals else 0.0


def sector_moves(ind: dict, sectors: dict, min_n: int = 2) -> list[dict]:
    """業種別の値動き（採用銘柄の単純平均）。前日比の大きい順。"""
    g = {}
    for code, x in ind.items():
        if not x or x.get("chg1d") is None:
            continue
        g.setdefault(sectors.get(code) or "その他", []).append(x)
    out = []
    for s, xs in g.items():
        if len(xs) < min_n:
            continue
        out.append({"sector": s, "n": len(xs), "chg1d": _avg(xs, "chg1d"), "chg5d": _avg(xs, "chg5d"),
                    "up": sum(1 for x in xs if x["chg1d"] > 0)})
    return sorted(out, key=lambda x: -x["chg1d"])


def sector_lines(moves: list[dict], top: int = 6) -> list[str]:
    if not moves:
        return []
    row = lambda m: f"| {m['sector']} | {m['chg1d']:+.2f}% | {m['chg5d']:+.2f}% | {m['up']}/{m['n']} |"
    L = ["### 業種別の値動き（日経225採用銘柄の平均。資金がどの業種に向かっているか）", "",
         "| 上昇した業種 | 前日比 | 5日 | 上昇銘柄数 |", "|---|---:|---:|---:|"]
    L += [row(m) for m in moves[:top]]
    L += ["", "| 下落した業種 | 前日比 | 5日 | 上昇銘柄数 |", "|---|---:|---:|---:|"]
    L += [row(m) for m in reversed(moves[-top:])]
    return L + [""]
