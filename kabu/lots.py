"""100株単位（単元株）で売買した場合の成績を、資金別に並行して記録する。

実際の証券口座で自動発注するときは原則100株単位になるため、同じ予想を100株単位で売買したら
どうなるかを、資金 100万・300万・500万・1,000万円 の4通りで計算する（実用化の判断材料）。

毎朝、運用開始からの全部の予想を最初から計算し直す（記録を持ち越さないので、ずれが残らない）。
売買の決まりは本体と同じ：その日の始値で約定、購入額は総資産の 20%/10%/5%、始値が前日終値より
+5%以上高い買いは見送り。違いは「100株に満たない分は買えない」ことだけ。
結果は data/lots/summary.json と data/lots/history.csv に保存する。朝の担当の判断には使わない。
"""
import csv
import json
from pathlib import Path

from kabu.ledger import after_tax, apply_split, load_fee, settle

LOT = 100
SCENARIOS = [("100万円", 1_000_000), ("300万円", 3_000_000), ("500万円", 5_000_000), ("1,000万円", 10_000_000)]
HIST_FIELDS = ["date", "scenario", "total", "cash", "stock_value"]


def _bars(series: dict, code: str) -> dict:
    return {b["d"]: b for b in series.get(code) or []}


def _prev_close(bars: dict, d: str):
    days = [x for x in bars if x < d]
    return bars[max(days)]["c"] if days else None


def simulate(orders: dict, series: dict, actions: list[dict], start_cash: int, start_date: str,
             lot: int = LOT) -> dict:
    """orders: {日付: 注文}、series: {コード: 日足, "N225": 日足}、actions: 本体の取引履歴の「配当」「分割」の行。
    戻り値: {"history": [...], "trades": [...], "state": {...}}"""
    state = {"start_date": start_date, "cash": start_cash, "holdings": {}, "last_closes": {}}
    days = sorted(b["d"] for b in series.get("N225") or [] if b["d"] >= start_date)
    bars = {}
    acts_by = {}
    for a in actions:
        acts_by.setdefault(a["date"], []).append(a)
    history, trades = [], []
    for d in days:
        # その日の配当・分割（前日まで持っていた株に）
        for a in acts_by.get(d, []):
            h = state["holdings"].get(a["code"])
            if not h:
                continue
            if a["side"] == "配当":
                state["cash"] += int(h["shares"] * float(a["price"]))
            elif a["side"] == "分割":
                apply_split(h, h["shares"], float(a["price"]))
        o = orders.get(d)
        if o:
            codes = [x["code"] for x in o.get("buys", []) + o.get("sells", [])]
            for c in codes:
                bars.setdefault(c, _bars(series, c))
            opens = {c: bars[c][d]["o"] for c in codes if d in bars[c] and bars[c][d].get("o")}
            refs = {c: _prev_close(bars[c], d) for c in codes}
            state, tr = settle(state, o, opens, {c: v for c, v in refs.items() if v}, lot=lot)
            trades += tr
        stock = 0
        for c, h in state["holdings"].items():
            bars.setdefault(c, _bars(series, c))
            px = bars[c][d]["c"] if d in bars[c] else state["last_closes"].get(c, h["avg_cost"])
            state["last_closes"][c] = px
            stock += int(h["shares"] * px)
        history.append({"date": d, "total": state["cash"] + stock, "cash": state["cash"], "stock_value": stock})
    return {"history": history, "trades": trades, "state": state}


def summarize(name: str, start_cash: int, sim: dict, fee=0.0) -> dict:
    hist, tr = sim["history"], sim["trades"]
    buys = [t for t in tr if t["side"] == "買"]
    done = [t for t in buys if t["status"] == "約定"]
    short = [t for t in buys if t["status"] == "見送り" and not str(t.get("reason", "")).startswith("始値が")]
    total = hist[-1]["total"] if hist else start_cash
    wk = None
    if len(hist) >= 2:
        wk = round((hist[-1]["total"] / hist[-2]["total"] - 1) * 100, 2)
    net = after_tax(total, tr, fee, start=start_cash)
    return {"name": name, "start": start_cash, "total": total, "ret": round((total / start_cash - 1) * 100, 2),
            "fees": net["fees"], "tax": net["tax"], "net": net["net"],
            "net_ret": round((net["net"] / start_cash - 1) * 100, 2),
            "cash_ratio": round(hist[-1]["cash"] / total, 3) if hist and total else 1.0,
            "n_orders": len(buys), "n_bought": len(done), "n_short": len(short),
            "holdings": [{"code": c, "name": h["name"], "shares": h["shares"]} for c, h in sim["state"]["holdings"].items()],
            "last_day_chg": wk, "asof": hist[-1]["date"] if hist else None}


def load_orders(data: Path) -> dict:
    out = {}
    for f in sorted((Path(data) / "orders").glob("*.json")):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict) and isinstance(o.get("buys"), list) and isinstance(o.get("sells"), list):
            out[o.get("date") or f.stem] = {**o, "date": o.get("date") or f.stem}
    return out


def order_codes(data: Path) -> list[str]:
    """これまでの予想に出てきた全部の銘柄（日足を取っておくため）。"""
    codes = []
    for o in load_orders(data).values():
        codes += [x.get("code") for x in o["buys"] + o["sells"] if x.get("code")]
    return list(dict.fromkeys(codes))


def update(root: Path, series: dict) -> dict | None:
    """全部の筋書きを計算し直して保存する。日足が無ければ何もしない。"""
    from kabu.settle import read_rows
    data = Path(root) / "data"
    try:
        state = json.loads((data / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not series.get("N225"):
        return None
    orders = load_orders(data)
    acts = [t for t in read_rows(data / "trades.csv") if t["side"] in ("配当", "分割")]
    start_date = state["start_date"]
    try:
        fee = load_fee(json.loads((Path(root) / "config.json").read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        fee = 0.0
    rows, scen = [], []
    for name, cash in SCENARIOS:
        sim = simulate(orders, series, acts, cash, start_date)
        scen.append(summarize(name, cash, sim, fee))
        rows += [{"date": h["date"], "scenario": name, **{k: h[k] for k in ("total", "cash", "stock_value")}}
                 for h in sim["history"]]
    # 比較の相手：本体（1株単位）と日経平均
    hist = read_rows(data / "history.csv")
    asof = scen[0]["asof"]
    base = next((h for h in hist if h["date"] == asof), hist[-1] if hist else None)
    out = {"asof": asof, "lot": LOT, "scenarios": scen,
           "main_ret": round((int(base["total"]) / 1_000_000 - 1) * 100, 2) if base else None,
           "bench_ret": round((int(base["benchmark_value"]) / 1_000_000 - 1) * 100, 2) if base else None,
           "main_asof": base["date"] if base else None}
    d = data / "lots"
    d.mkdir(parents=True, exist_ok=True)
    (d / "summary.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(d / "history.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HIST_FIELDS)
        w.writeheader()
        w.writerows(rows)
    return out


def load(root: Path) -> dict | None:
    try:
        return json.loads((Path(root) / "data" / "lots" / "summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def lines(s: dict | None) -> list[str]:
    """メール・週末のまとめに載せる文。"""
    if not s or not s.get("scenarios"):
        return []
    L = ["", f"■ 100株単位で売買した場合（実用化の検討用・{s['asof']} 終値時点）"]
    if s.get("main_ret") is not None:
        L.append(f"1株単位（本体）：{s['main_ret']:+.2f}%／日経平均：{s['bench_ret']:+.2f}%")
    for x in s["scenarios"]:
        skip = f"・{x['n_short']}件は100株に届かず買えず" if x["n_short"] else ""
        net = f"・手数料と税を引くと {x['net_ret']:+.2f}%（手数料 {x['fees']:,}円・税 {x['tax']:,}円）" \
            if x.get("net_ret") is not None and (x.get("fees") or x.get("tax")) else ""
        L.append(f"・資金{x['name']}：{x['ret']:+.2f}%（{x['total']:,}円）　買えた予想 {x['n_bought']}/{x['n_orders']}件{skip}"
                 f"・現金 {x['cash_ratio']:.0%}{net}")
    L.append("※同じ予想を100株単位で売買した試算です。予想どおりに買えない資金では、成績が本体と大きく変わります。")
    return L


def site_section(s: dict | None) -> str:
    import html as H
    if not s or not s.get("scenarios"):
        return ""
    cls = lambda v: "up" if v >= 0 else "down"
    rows = "".join(
        f"<tr><td>資金 {H.escape(x['name'])}</td><td class='{cls(x['ret'])}'>{x['ret']:+.2f}%<small>{x['total']:,}円"
        + (f"・手数料と税を引くと {x['net_ret']:+.2f}%" if x.get('net_ret') is not None else "") + "</small></td>"
        f"<td>{x['n_bought']}/{x['n_orders']}件<small>100株に届かず {x['n_short']}件</small></td>"
        f"<td>{x['cash_ratio']:.0%}</td><td>{len(x['holdings'])}銘柄</td></tr>" for x in s["scenarios"])
    head = ""
    if s.get("main_ret") is not None:
        head = (f"<p class='summary'>1株単位（本体）：<b class='{cls(s['main_ret'])}'>{s['main_ret']:+.2f}%</b>"
                f"／日経平均：{s['bench_ret']:+.2f}%（{H.escape(s['asof'])} 終値時点）</p>")
    return ("<section class='card'><h2>100株単位で売買した場合</h2>" + head
            + "<div class='scroll'><table><tr><th>筋書き</th><th>成績</th><th>買えた予想</th><th>現金</th><th>持ち株</th></tr>"
            + rows + "</table></div><p class='sub' style='margin:8px 0 0'>実際の自動発注は原則100株単位です。"
            "同じ予想を100株単位で売買した試算で、100株に満たない分は買えません。実用化に必要な資金の目安になります。</p></section>")
