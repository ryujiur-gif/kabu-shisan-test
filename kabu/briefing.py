"""朝の資料（out/briefing.md / out/briefing.json）を作る。

1. 主要指標（日経先物・米国株・為替・金利・原油など）の前日終値と騰落率
2. 持ち株の点検（取得からの損益・直近の値動き）
3. 日経225全銘柄の値動きスクリーニング（騰落・出来高急増・25日線乖離・RSI・移動平均線のクロス・割安度）

使い方: python -m kabu.briefing [--today 2026-11-10]
数値はプログラムで取得するので、ニュース検索より優先して使うこと。
"""
import argparse
import json
import math
from pathlib import Path

MARKET = [
    ("日経225先物（CME・円建て）", "NIY=F"),
    ("日経平均", "^N225"),
    ("NYダウ", "^DJI"),
    ("S&P500", "^GSPC"),
    ("ナスダック総合", "^IXIC"),
    ("フィラデルフィア半導体指数", "^SOX"),
    ("VIX（恐怖指数）", "^VIX"),
    ("ドル円", "JPY=X"),
    ("米10年国債利回り", "^TNX"),
    ("WTI原油", "CL=F"),
    ("金", "GC=F"),
]

RANKS = [
    ("上昇率", "chg1d", True),
    ("下落率", "chg1d", False),
    ("出来高急増", "vol_ratio", True),
    ("25日線から上方乖離", "ma25_dev", True),
    ("25日線から下方乖離", "ma25_dev", False),
]


def pct_change(prev, last):
    if prev is None or last is None or not prev:
        return None
    return round((float(last) / float(prev) - 1) * 100, 2)


def _clean(df):
    if df is None or len(df) == 0 or "Close" not in df:
        return None
    d = df.dropna(subset=["Close"])
    return d if len(d) else None


def _ma(c, n, end):
    """c[:end] の末尾 n 本の平均（end は len(c) 以下）。"""
    return sum(c[end - n:end]) / n


def detect_cross(c: list[float], short: int, long: int, within: int = 3):
    """直近 within 営業日内に短期線が長期線を上抜け→"GC"、下抜け→"DC"、なし→None。"""
    if len(c) < long + within:
        return None
    signs = []
    for k in range(within, -1, -1):
        end = len(c) - k
        diff = _ma(c, short, end) - _ma(c, long, end)
        signs.append(1 if diff > 0 else (-1 if diff < 0 else 0))
    result = None
    for a, b in zip(signs, signs[1:]):
        if a <= 0 < b:
            result = "GC"
        elif a >= 0 > b:
            result = "DC"
    return result


def indicators(df) -> dict | None:
    """Close/Volume を持つ日足 DataFrame から指標を計算。26本未満なら None。"""
    d = _clean(df)
    if d is None or len(d) < 26:
        return None
    c = [float(x) for x in d["Close"]]
    v = [float(x) if x == x else 0.0 for x in d["Volume"]] if "Volume" in d else [0.0] * len(c)
    ma25 = sum(c[-25:]) / 25
    prev_vols = v[-21:-1]
    avg_vol = sum(prev_vols) / len(prev_vols) if prev_vols else 0
    diffs = [c[i] - c[i - 1] for i in range(len(c) - 14, len(c))]
    gain = sum(x for x in diffs if x > 0) / 14
    loss = sum(-x for x in diffs if x < 0) / 14
    rsi = 100.0 if loss == 0 else round(100 - 100 / (1 + gain / loss), 1)
    return {
        "close": c[-1],
        "chg1d": pct_change(c[-2], c[-1]),
        "chg5d": pct_change(c[-6], c[-1]),
        "vol_ratio": round(v[-1] / avg_vol, 2) if avg_vol else None,
        "ma25_dev": round((c[-1] / ma25 - 1) * 100, 2),
        "rsi14": rsi,
        "cross5_25": detect_cross(c, 5, 25),
        "cross25_75": detect_cross(c, 25, 75),
    }


def rank_candidates(ind: dict, n: int = 10) -> dict:
    out = {}
    for label, key, desc in RANKS:
        items = [(c, x) for c, x in ind.items() if x and x.get(key) is not None]
        items.sort(key=lambda t: t[1][key], reverse=desc)
        out[label] = items[:n]
    return out


def cross_lists(ind: dict) -> dict:
    out = {"ゴールデンクロス": [], "デッドクロス": []}
    for code, x in ind.items():
        if not x:
            continue
        for kind, label in (("GC", "ゴールデンクロス"), ("DC", "デッドクロス")):
            lines = [name for key, name in (("cross5_25", "5日/25日"), ("cross25_75", "25日/75日"))
                     if x.get(key) == kind]
            if lines:
                out[label].append((code, "・".join(lines)))
    return out


def rank_value(fund: dict, n: int = 10) -> list:
    """割安・好財務：PBR1.2倍未満・ROE8%以上を PER の低い順に。"""
    items = [(c, f) for c, f in fund.items()
             if f and f.get("per") and f.get("pbr") is not None and f.get("roe") is not None
             and f["pbr"] < 1.2 and f["roe"] >= 8]
    items.sort(key=lambda t: t[1]["per"])
    return items[:n]


def sector_medians(fund: dict, sectors: dict) -> dict:
    from statistics import median
    groups = {}
    for code, sec in sectors.items():
        groups.setdefault(sec, []).append(fund.get(code) or {})
    out = {}
    for sec, rows in groups.items():
        m = {}
        for k in ("per", "pbr", "roe"):
            vals = [r[k] for r in rows if r.get(k) is not None]
            m[k] = round(median(vals), 2) if vals else None
        m["n"] = len(rows)
        out[sec] = m
    return out


def rank_peer_value(fund: dict, sectors: dict, med: dict, n: int = 10) -> list:
    """同業他社（業種中央値）より PER・PBR が低く、ROE は中央値以上の銘柄。"""
    items = []
    for code, f in fund.items():
        m = med.get(sectors.get(code), {})
        if not f or m.get("n", 0) < 3 or None in (f.get("per"), f.get("pbr"), f.get("roe"),
                                                  m.get("per"), m.get("pbr"), m.get("roe")):
            continue
        if f["per"] < m["per"] and f["pbr"] < m["pbr"] and f["roe"] >= m["roe"]:
            items.append((code, {**f, "sector": sectors.get(code), "med": m,
                                 "per_vs_peer": (f["per"] / m["per"] - 1) * 100,
                                 "pbr_vs_peer": (f["pbr"] / m["pbr"] - 1) * 100}))
    items.sort(key=lambda t: t[1]["per_vs_peer"] + t[1]["pbr_vs_peer"])
    return items[:n]


def holding_view(code: str, h: dict, ind: dict | None, bought: str | None) -> dict:
    close = ind["close"] if ind else None
    pl_pct = pct_change(h["avg_cost"], close) if close else None
    pl_yen = int((close - h["avg_cost"]) * h["shares"]) if close else None
    g = (ind or {}).get
    return {"code": code, "name": h["name"], "shares": h["shares"], "avg_cost": h["avg_cost"],
            "close": close, "pl_pct": pl_pct, "pl_yen": pl_yen, "chg1d": g("chg1d"),
            "chg5d": g("chg5d"), "rsi14": g("rsi14"), "ma25_dev": g("ma25_dev"), "bought": bought}


def _p(x) -> str:
    return "-" if x is None else f"{'+' if x >= 0 else ''}{x:.2f}%"


def _n(x, fmt="{:,.1f}") -> str:
    return "-" if x is None else fmt.format(x)


def _x(x, fmt="{:.1f}倍") -> str:
    return "-" if x is None else fmt.format(x)


CASH_TARGETS = {"リスクオン（強気）": (0.20, 0.40), "中立": (0.30, 0.50), "リスクオフ（警戒）": (0.50, 0.80)}


def cash_target(mood: str) -> tuple[float, float]:
    """相場環境ごとの現金比率の目安（下限, 上限）。判断材料不足のときは中立扱い。"""
    return CASH_TARGETS.get(mood, CASH_TARGETS["中立"])


def funds_lines(f: dict, holdings: list, mood: str) -> list[str]:
    from kabu.ledger import MAX_STOCK_RATIO, MIN_CASH_RATIO, amount_for
    total = f["total"]
    lo, hi = cash_target(mood)
    ratio = f["cash_ratio"]
    state_word = "目安より少ない（買いは控えめに。入れ替えの売りも検討）" if ratio < lo else \
        "目安より多い（基準を満たす銘柄があれば買ってよい）" if ratio > hi else "目安の範囲内"
    usable = max(f["cash"] - int(total * MIN_CASH_RATIO), 0)
    names = {h["code"]: h["name"] for h in holdings}
    L = ["", "### 資金状況（前営業日終値で評価）", "",
         f"- 総資産：{total:,}円（現金 {f['cash']:,}円 ＋ 株式 {f['stock_value']:,}円）",
         f"- 現金比率：{ratio:.0%}　相場環境「{mood or '-'}」での目安 {lo:.0%}〜{hi:.0%} → **{state_word}**",
         f"- 期待度ごとの購入予定額（総資産比）：高 {amount_for('高', total):,}円（20%）／中 {amount_for('中', total):,}円（10%）／低 {amount_for('低', total):,}円（5%）",
         f"- 新しい買いに使える額（現金を総資産の{MIN_CASH_RATIO:.0%}残す）：{usable:,}円",
         f"- 1銘柄の上限：総資産の{MAX_STOCK_RATIO:.0%}（{int(total * MAX_STOCK_RATIO):,}円）"]
    if f["weights"]:
        L.append("- 銘柄ごとの比率：" + "／".join(
            f"{names.get(c, c)} {w:.0%}" for c, w in sorted(f["weights"].items(), key=lambda x: -x[1])))
    return L


def render_briefing(today, market, holdings, ranks, names, notes, fund=None, fund_date=None,
                    crosses=None, value=None, peer=None, regime=None, funds_info=None) -> str:
    fund = fund or {}
    fg = lambda code, k: (fund.get(code) or {}).get(k)
    L = [f"# 朝の資料 {today}", "", "数値はプログラムで取得した前営業日（米国は前夜）の終値です。ニュース検索の数値より優先してください。", ""]
    L += ["## 1. 主要指標", "", "| 指標 | 終値 | 前日比 | 日付 |", "|---|---:|---:|---|"]
    for m in market:
        L.append(f"| {m['label']} | {_n(m.get('close'), '{:,.2f}')} | {_p(m.get('chg'))} | {m.get('date', '-')} |")
    if regime:
        from kabu.business_types import TYPE_GUIDE, TYPE_LABELS
        fmt = lambda xs: "・".join(f"{t}{TYPE_LABELS[t]}" for t in xs) or "特になし"
        L += ["", f"### 相場環境の目安：{regime['mood']}", "",
              f"- 有利な型：{fmt(regime['favor'])}", f"- 不利な型：{fmt(regime['avoid'])}"]
        L += [f"- {n}" for n in regime["notes"]]
        L += ["", "銘柄名の〔 〕はビジネスモデルの型（業種からの目安。企業メモで見直し可）。", "",
              "| 型 | 特徴と判断のポイント |", "|---|---|"]
        L += [f"| {t}{TYPE_LABELS[t]} | {g} |" for t, g in TYPE_GUIDE.items()]
    if funds_info:
        L += funds_lines(funds_info, holdings, (regime or {}).get("mood", ""))
    L += ["", "## 2. 持ち株の点検", ""]
    if holdings:
        L += ["| 銘柄 | 株数 | 取得単価 | 直近終値 | 損益率 | 損益額 | 前日比 | 5日 | RSI14 | 25日線乖離 | PER | PBR | 購入日 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for h in holdings:
            L.append(f"| {h['name']}({h['code']}) | {h['shares']:,} | {_n(h['avg_cost'])} | {_n(h['close'])} | "
                     f"{_p(h['pl_pct'])} | {_n(h['pl_yen'], '{:+,}円')} | {_p(h['chg1d'])} | {_p(h['chg5d'])} | "
                     f"{_n(h['rsi14'], '{:.0f}')} | {_p(h['ma25_dev'])} | {_x(fg(h['code'], 'per'))} | "
                     f"{_x(fg(h['code'], 'pbr'), '{:.2f}倍')} | {h['bought'] or '-'} |")
        L += ["", "→ 各持ち株について、個別ニュース（決算・業績修正・不祥事・格付け変更など）を必ず検索して売り判断に使うこと。"]
    else:
        L.append("持ち株はありません。")
    L += ["", "## 3. 日経225 値動きスクリーニング", "",
          "買い候補探しの出発点です（上昇・出来高急増は材料が出ている可能性、下方乖離・RSI低は売られすぎの可能性）。",
          "ここに出た銘柄は、理由となるニュースを検索で確かめてから採用すること。", ""]
    for label, items in ranks.items():
        L += [f"### {label}", "", "| 銘柄 | 終値 | 前日比 | 5日 | 出来高倍率 | 25日線乖離 | RSI14 | PER | PBR |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for code, x in items:
            L.append(f"| {names.get(code, '')}({code}) | {_n(x['close'])} | {_p(x['chg1d'])} | {_p(x['chg5d'])} | "
                     f"{_n(x['vol_ratio'], '{:.1f}倍')} | {_p(x['ma25_dev'])} | {_n(x['rsi14'], '{:.0f}')} | "
                     f"{_x(fg(code, 'per'))} | {_x(fg(code, 'pbr'), '{:.2f}倍')} |")
        L.append("")
    if crosses:
        for label in ("ゴールデンクロス", "デッドクロス"):
            items = crosses.get(label, [])
            L += [f"### {label}（直近3営業日・移動平均線）", ""]
            L += [f"- {names.get(c, '')}({c})：{lines}" for c, lines in items] or ["- なし"]
            L.append("")
    if value is not None:
        L += [f"### 割安・好財務候補（PBR1.2倍未満・ROE8%以上、PER低い順。財務データ {fund_date or '未取得'} 時点）", "",
              "| 銘柄 | PER | PBR | ROE | 自己資本比率 | 配当利回り | 連続増配 |", "|---|---:|---:|---:|---:|---:|---:|"]
        for code, f in value:
            L.append(f"| {names.get(code, '')}({code}) | {_x(f.get('per'))} | {_x(f.get('pbr'), '{:.2f}倍')} | "
                     f"{_x(f.get('roe'), '{:.1f}%')} | {_x(f.get('equity_ratio'), '{:.1f}%')} | "
                     f"{_x(f.get('div_yield'), '{:.2f}%')} | {_x(f.get('div_streak'), '{:.0f}年')} |")
        if not value:
            L.append("| 該当なし | | | | | | |")
        if peer is not None:
            L += ["", "### 同業他社より割安（業種の中央値と比べて PER・PBR が低く、ROE は中央値以上）", "",
                  "| 銘柄 | 業種 | PER（業種比） | PBR（業種比） | ROE（業種中央値） | 配当利回り | 連続増配 |",
                  "|---|---|---:|---:|---:|---:|---:|"]
            for code, f in peer:
                m = f["med"]
                L.append(f"| {names.get(code, '')}({code}) | {f['sector']} | {_x(f['per'])}（{f['per_vs_peer']:+.0f}%） | "
                         f"{_x(f['pbr'], '{:.2f}倍')}（{f['pbr_vs_peer']:+.0f}%） | {_x(f['roe'], '{:.1f}%')}（{_x(m['roe'], '{:.1f}%')}） | "
                         f"{_x(f.get('div_yield'), '{:.2f}%')} | {_x(f.get('div_streak'), '{:.0f}年')} |")
            if not peer:
                L.append("| 該当なし | | | | | | |")
        L += ["", "→ 割安でも業績悪化中の「割安のわな」に注意。業績予想・進捗率・信用残は、候補に挙げる銘柄だけ株探などで確認すること。", ""]
    if notes:
        L += ["## 取得できなかったデータ", ""] + [f"- {n}" for n in notes]
    return "\n".join(L) + "\n"


# ---- データ取得（yfinance） ----

def _frames(tickers: list[str], period: str) -> dict:
    import yfinance as yf
    raw = yf.download(tickers, period=period, group_by="ticker", auto_adjust=False,
                      progress=False, threads=True)
    out = {}
    for t in tickers:
        try:
            out[t] = raw[t] if len(tickers) > 1 else raw
        except KeyError:
            out[t] = None
    return out


def fetch_market() -> list[dict]:
    frames = _frames([t for _, t in MARKET], "10d")
    out = []
    for label, t in MARKET:
        d = _clean(frames.get(t))
        if d is None or len(d) < 2:
            out.append({"label": label, "ticker": t, "close": None, "chg": None, "date": "-"})
            continue
        last, prev = float(d["Close"].iloc[-1]), float(d["Close"].iloc[-2])
        out.append({"label": label, "ticker": t, "close": round(last, 2), "chg": pct_change(prev, last),
                    "date": d.index[-1].strftime("%Y-%m-%d")})
    return out


def fetch_indicators(codes: list[str]) -> dict:
    frames = _frames([f"{c}.T" for c in codes], "6mo")
    return {c: indicators(frames.get(f"{c}.T")) for c in codes}


def _bought_dates(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        if t["side"] == "買" and t["status"] == "約定":
            out[t["code"]] = t["date"]
    return out


def build(root: Path, today: str) -> tuple[str, dict]:
    """朝の資料を作る。戻り値は (Markdown, {"today", "market"})。"""
    from kabu.picks import load_universe
    from kabu.settle import read_rows
    root = Path(root)
    from kabu.business_types import TYPE_LABELS, classify, market_regime
    names = load_universe(root / "data" / "nikkei225.csv")
    state_p = root / "data" / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {"holdings": {}}
    notes = []
    try:
        market = fetch_market()
    except Exception as e:
        market = []
        notes.append(f"主要指標の取得に失敗: {e}")
    notes += [f"{m['label']}（{m['ticker']}）" for m in market if m["close"] is None]
    codes = list(dict.fromkeys(list(names) + list(state["holdings"])))
    try:
        ind = fetch_indicators(codes)
    except Exception as e:
        ind = {}
        notes.append(f"日経225の株価取得に失敗: {e}")
    missing = [c for c in names if not ind.get(c)]
    if missing:
        notes.append(f"株価が取れなかった銘柄 {len(missing)} 件: {', '.join(missing[:20])}{' ほか' if len(missing) > 20 else ''}")
    bought = _bought_dates(read_rows(root / "data" / "trades.csv"))
    holdings = [holding_view(c, h, ind.get(c), bought.get(c)) for c, h in state["holdings"].items()]
    ranks = rank_candidates({c: ind.get(c) for c in names})
    import csv as _csv
    from kabu.fundamentals import load_fundamentals
    with open(root / "data" / "nikkei225.csv", encoding="utf-8") as fh:
        sectors = {r["code"]: r["sector"] for r in _csv.DictReader(fh)}
    fund_date, fund = load_fundamentals(root / "data" / "fundamentals.csv")
    if not fund:
        notes.append("財務データ（data/fundamentals.csv）がまだありません")
    types = {c: classify(c, sectors.get(c, "")) for c in names}
    names = {c: f"{n}〔{types[c]}{TYPE_LABELS[types[c]]}〕" for c, n in names.items()}
    for h in holdings:
        t = classify(h["code"], sectors.get(h["code"], ""))
        h["name"] = f"{h['name']}〔{t}{TYPE_LABELS[t]}〕"
    from kabu.ledger import funds
    funds_info = funds(state, {h["code"]: h["close"] for h in holdings if h.get("close")}) \
        if "cash" in state else None
    md = render_briefing(today, market, holdings, ranks, names, notes, fund=fund, fund_date=fund_date,
                         regime=market_regime(market), funds_info=funds_info,
                         crosses=cross_lists({c: ind.get(c) for c in names}),
                         value=rank_value({c: fund.get(c) for c in names}),
                         peer=rank_peer_value({c: fund.get(c) for c in names}, sectors,
                                              sector_medians(fund, sectors)))
    return md, {"today": today, "market": market, "missing": notes}


def main():
    from kabu.settle import jst_today
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    root = Path(a.root)
    today = a.today or jst_today().isoformat()
    md, payload = build(root, today)
    (root / "out").mkdir(exist_ok=True)
    (root / "out" / "briefing.md").write_text(md, encoding="utf-8")
    (root / "out" / "briefing.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
