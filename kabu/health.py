"""毎朝のデータ点検と自動修復。

点検（check）：記録のつじつま・抜け・古さを調べ、問題を日本語の文で返す。朝の資料とメールの注記に載る。
修復（backfill_history）：確定が遅れた日があって成績の記録（history.csv）に抜けた営業日を、
取引履歴と株価から計算し直して埋める。
"""
import json
from datetime import date, timedelta
from pathlib import Path

from kabu.ledger import START_CASH, replay
from kabu.market_calendar import is_trading_day, previous_trading_day
from kabu.settle import HIST_FIELDS, _write_rows, read_rows


def trading_days(start: date, end: date) -> list[date]:
    out, d = [], start
    while d <= end:
        if is_trading_day(d):
            out.append(d)
        d += timedelta(days=1)
    return out


def _load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def check(root: Path, today: date, market: list[dict] | None = None) -> list[str]:
    data = Path(root) / "data"
    state = _load(data / "state.json")
    if not state:
        return []
    out = []
    trades = read_rows(data / "trades.csv")
    hist = read_rows(data / "history.csv")
    p = previous_trading_day(today)
    start = date.fromisoformat(state["start_date"])

    # 1. 取引履歴から計算し直した口座と、記録されている口座が合っているか
    r = replay(trades)
    if r["cash"] != state.get("cash"):
        out.append(f"口座の現金（{state.get('cash'):,}円）が取引履歴からの計算（{r['cash']:,}円）と合いません")
    mine = {c: h["shares"] for c, h in state.get("holdings", {}).items()}
    calc = {c: h["shares"] for c, h in r["holdings"].items()}
    if mine != calc:
        out.append("口座の持ち株が取引履歴からの計算と合いません（state.json と trades.csv の食い違い）")

    # 2. 確定されていない古い注文
    old = []
    for f in sorted((data / "orders").glob("*.json")):
        o = _load(f)
        if isinstance(o, dict) and not o.get("settled") and (o.get("date") or f.stem) < p.isoformat():
            old.append(f.stem)
    if old:
        out.append(f"確定されていない注文があります（{', '.join(old)}）。株価が取れ次第まとめて確定します")

    # 3. 前営業日の予想が作られているか（朝の担当が動かなかった日の検出）
    if p >= start and not (data / "orders" / f"{p.isoformat()}.json").exists():
        out.append(f"前営業日（{p}）の予想が作られていません（朝の自動実行が動かなかった可能性）")

    # 4. 成績の記録の抜け
    have = {r["date"] for r in hist}
    last = state.get("last_date")
    if last:
        gaps = [d.isoformat() for d in trading_days(start, date.fromisoformat(last)) if d.isoformat() not in have]
        if gaps:
            out.append(f"成績の記録に抜けた日があります（{', '.join(gaps[:5])}{' ほか' if len(gaps) > 5 else ''}）")
        if date.fromisoformat(last) < p and p >= start:
            out.append(f"成績の記録が {last} で止まっています（前営業日 {p} 分が未確定）")

    # 5. 主要指標の日付（日経平均が前営業日の値か）
    for m in market or []:
        if m.get("ticker") == "^N225" and m.get("close") is not None and m.get("date") != p.isoformat():
            out.append(f"日経平均が前営業日（{p}）の値ではありません（{m.get('date')} の値）")

    # 6. 週1回更新の資料が古くないか
    from kabu.events import last_checked, load_events
    chk = last_checked(load_events(data / "events.csv"))
    if chk and (today - date.fromisoformat(chk)).days > 10:
        out.append(f"日程表（events.csv）の最終確認が {chk} で、10日以上たっています")
    from kabu.fundamentals import load_fundamentals
    try:
        fd, _ = load_fundamentals(data / "fundamentals.csv")
        if fd and (today - date.fromisoformat(str(fd)[:10])).days > 10:
            out.append(f"財務データが {fd} 時点で、10日以上更新されていません")
    except (OSError, ValueError):
        pass
    return out


def backfill_history(root: Path, series: dict) -> list[str]:
    """history.csv に抜けた営業日を、取引履歴と株価（series）から埋める。埋めた日付を返す。"""
    data = Path(root) / "data"
    state = _load(data / "state.json")
    if not state or not state.get("last_date"):
        return []
    hp = data / "history.csv"
    hist = read_rows(hp)
    have = {r["date"] for r in hist}
    start_open = state.get("benchmark", {}).get("start_open")
    bench_start = state.get("benchmark", {}).get("start_date") or state["start_date"]
    trades = read_rows(data / "trades.csv")
    nk = {b["d"]: b["c"] for b in series.get("N225") or []}
    closes = {c: {b["d"]: b["c"] for b in bars} for c, bars in series.items() if c != "N225"}
    filled = []
    for d in trading_days(date.fromisoformat(state["start_date"]), date.fromisoformat(state["last_date"])):
        ds = d.isoformat()
        if ds in have or ds not in nk:
            continue
        st = replay([t for t in trades if t["date"] <= ds])
        if any(ds not in closes.get(c, {}) for c in st["holdings"]):
            continue   # 株価が欠けている日は埋めない（不正確な値を書かない）
        stock = sum(int(h["shares"] * closes[c][ds]) for c, h in st["holdings"].items())
        bench = int(START_CASH * nk[ds] / start_open) if start_open and ds >= bench_start else START_CASH
        hist.append({"date": ds, "total": st["cash"] + stock, "cash": st["cash"], "stock_value": stock,
                     "nikkei_close": round(nk[ds], 2), "benchmark_value": bench})
        filled.append(ds)
    if filled:
        hist.sort(key=lambda r: r["date"])
        _write_rows(hp, HIST_FIELDS, hist)
    return filled
