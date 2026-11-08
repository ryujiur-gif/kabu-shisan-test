"""朝の資料（out/briefing.md / out/briefing.json）を作る。

1. 主要指標（日経先物・米国株・為替・金利・原油など）の前日終値と騰落率
2. 持ち株の点検（取得からの損益・直近の値動き）
3. 日経225全銘柄の値動きスクリーニング（騰落・出来高急増・25日線乖離・RSI）

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
    }


def rank_candidates(ind: dict, n: int = 10) -> dict:
    out = {}
    for label, key, desc in RANKS:
        items = [(c, x) for c, x in ind.items() if x and x.get(key) is not None]
        items.sort(key=lambda t: t[1][key], reverse=desc)
        out[label] = items[:n]
    return out


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


def render_briefing(today, market, holdings, ranks, names, notes) -> str:
    L = [f"# 朝の資料 {today}", "", "数値はプログラムで取得した前営業日（米国は前夜）の終値です。ニュース検索の数値より優先してください。", ""]
    L += ["## 1. 主要指標", "", "| 指標 | 終値 | 前日比 | 日付 |", "|---|---:|---:|---|"]
    for m in market:
        L.append(f"| {m['label']} | {_n(m.get('close'), '{:,.2f}')} | {_p(m.get('chg'))} | {m.get('date', '-')} |")
    L += ["", "## 2. 持ち株の点検", ""]
    if holdings:
        L += ["| 銘柄 | 株数 | 取得単価 | 直近終値 | 損益率 | 損益額 | 前日比 | 5日 | RSI14 | 25日線乖離 | 購入日 |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
        for h in holdings:
            L.append(f"| {h['name']}({h['code']}) | {h['shares']:,} | {_n(h['avg_cost'])} | {_n(h['close'])} | "
                     f"{_p(h['pl_pct'])} | {_n(h['pl_yen'], '{:+,}円')} | {_p(h['chg1d'])} | {_p(h['chg5d'])} | "
                     f"{_n(h['rsi14'], '{:.0f}')} | {_p(h['ma25_dev'])} | {h['bought'] or '-'} |")
        L += ["", "→ 各持ち株について、個別ニュース（決算・業績修正・不祥事・格付け変更など）を必ず検索して売り判断に使うこと。"]
    else:
        L.append("持ち株はありません。")
    L += ["", "## 3. 日経225 値動きスクリーニング", "",
          "買い候補探しの出発点です（上昇・出来高急増は材料が出ている可能性、下方乖離・RSI低は売られすぎの可能性）。",
          "ここに出た銘柄は、理由となるニュースを検索で確かめてから採用すること。", ""]
    for label, items in ranks.items():
        L += [f"### {label}", "", "| 銘柄 | 終値 | 前日比 | 5日 | 出来高倍率 | 25日線乖離 | RSI14 |", "|---|---:|---:|---:|---:|---:|---:|"]
        for code, x in items:
            L.append(f"| {names.get(code, '')}({code}) | {_n(x['close'])} | {_p(x['chg1d'])} | {_p(x['chg5d'])} | "
                     f"{_n(x['vol_ratio'], '{:.1f}倍')} | {_p(x['ma25_dev'])} | {_n(x['rsi14'], '{:.0f}')} |")
        L.append("")
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
    frames = _frames([f"{c}.T" for c in codes], "3mo")
    return {c: indicators(frames.get(f"{c}.T")) for c in codes}


def _bought_dates(trades: list[dict]) -> dict:
    out = {}
    for t in trades:
        if t["side"] == "買" and t["status"] == "約定":
            out[t["code"]] = t["date"]
    return out


def main():
    from kabu.picks import load_universe
    from kabu.settle import jst_today, read_rows
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    root = Path(a.root)
    today = a.today or jst_today().isoformat()
    names = load_universe(root / "data" / "nikkei225.csv")
    state_p = root / "data" / "state.json"
    state = json.loads(state_p.read_text(encoding="utf-8")) if state_p.exists() else {"holdings": {}}
    notes = []
    try:
        market = fetch_market()
    except Exception as e:
        market, _ = [], notes.append(f"主要指標の取得に失敗: {e}")
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
    md = render_briefing(today, market, holdings, ranks, names, notes)
    (root / "out").mkdir(exist_ok=True)
    (root / "out" / "briefing.md").write_text(md, encoding="utf-8")
    (root / "out" / "briefing.json").write_text(
        json.dumps({"today": today, "market": market}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
