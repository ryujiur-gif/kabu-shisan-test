"""毎朝の確定処理：前営業日までの未確定注文を始値で約定し、前営業日の終値で評価を記録する。

使い方: python -m kabu.settle [--today 2026-11-10] [--data data]
--today を省略すると日本時間の今日になる。
"""
import argparse
import csv
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from kabu.ledger import START_CASH, new_state, settle, valuation
from kabu.market_calendar import is_trading_day, previous_trading_day
from kabu.prices import get_day_prices, get_nikkei

TRADE_FIELDS = ["date", "side", "code", "name", "shares", "price", "amount", "status", "reason"]
HIST_FIELDS = ["date", "total", "cash", "stock_value", "nikkei_close", "benchmark_value"]


def jst_today(now: datetime | None = None) -> date:
    now = now or datetime.now(timezone.utc)
    return (now.astimezone(timezone.utc) + timedelta(hours=9)).date()


def _read_json(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _write_json(p: Path, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_rows(p: Path) -> list[dict]:
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _write_rows(p: Path, fields, rows):
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _holdings_view(state, closes):
    return [{"code": c, "name": h["name"], "shares": h["shares"], "avg_cost": round(h["avg_cost"], 2),
             "close": closes.get(c)} for c, h in state["holdings"].items()]


def _valid_date(s) -> bool:
    try:
        date.fromisoformat(str(s))
        return True
    except ValueError:
        return False


def _ref_closes(data_dir: Path, d: str) -> dict:
    """その日の朝の資料に保存した前日終値（始値が高すぎる買いの見送り判定に使う）。"""
    try:
        ind = _read_json(data_dir / "daily" / d / "indicators.json")
    except (OSError, json.JSONDecodeError):
        return {}
    return {c: x["close"] for c, x in ind.items() if isinstance(x, dict) and x.get("close")}


def run(today: date, data_dir: Path, fetch=None, actions_fetch=None, even_if_holiday: bool = False) -> dict:
    """fetch を差し替えたとき（テスト）は、actions_fetch を渡さない限り配当・分割の取得をしない。
    even_if_holiday：休場日（土曜の週次まとめなど）でも、前営業日分の確定と評価を行う。"""
    data_dir = Path(data_dir)
    base = {"today": today.isoformat()}
    use_actions = actions_fetch is not None or fetch is None
    if not is_trading_day(today) and not even_if_holiday:
        return {**base, "status": "holiday", "message": f"{today} は休場日です"}
    state_p = data_dir / "state.json"
    if not state_p.exists():
        state = new_state(today.isoformat())
        _write_json(state_p, state)
        return {**base, "status": "nothing", "holdings": [], "total": START_CASH,
                "message": "初回：仮想口座(100万円)を作成しました"}
    state = _read_json(state_p)
    last_closes = state.get("last_closes", {})
    p = previous_trading_day(today)
    if p.isoformat() < state["start_date"]:
        return {**base, "status": "nothing", "holdings": _holdings_view(state, last_closes),
                "total": valuation(state, last_closes)["total"], "message": "確定対象の営業日はまだありません"}

    def error(msg):
        return {**base, "status": "price_error", "holdings": _holdings_view(state, last_closes),
                "total": valuation(state, last_closes)["total"], "message": msg}

    pending = []
    for f in sorted((data_dir / "orders").glob("*.json")):
        o = _read_json(f)
        if o.get("settled"):
            continue
        od = o.get("date") if _valid_date(o.get("date")) else f.stem
        if not _valid_date(od) or od > p.isoformat():
            continue
        pending.append((f, {**o, "date": od}))

    # すでに前営業日分まで確定・評価済みなら、株価を取り直さずそのまま返す
    # （同じ日に2回目以降の実行があっても、取得の不調で「失敗」に書き換わらないようにする）
    actions_done = not use_actions or state.get("actions_through", "") >= p.isoformat()
    if not pending and actions_done and state.get("last_date") == p.isoformat() and             any(r["date"] == p.isoformat() for r in read_rows(data_dir / "history.csv")):
        return {**base, "status": "ok", "holdings": _holdings_view(state, last_closes),
                "total": valuation(state, last_closes)["total"],
                "message": f"{p} 分は確定済みです"}

    # 価格をすべて先に集める（失敗したら何も書かない）
    opens_by_date, notes = {}, []
    for f, o in pending:
        d = date.fromisoformat(o["date"])
        codes = [x["code"] for x in o.get("buys", []) + o.get("sells", [])]
        got = get_day_prices(codes, d, fetch=fetch) if is_trading_day(d) else {}
        missing = [c for c in dict.fromkeys(codes) if c not in got]
        if missing:
            if d == p:
                # 直近分は一部でも欠けたら何も書かず、次回に取り直す（黙って取消にしない）
                return error(f"{d} の株価を取得できませんでした（{f.name}：{', '.join(missing)}）。次回に取り直します")
            notes.append(f"{f.name} の {', '.join(missing)} は株価が取得できないため取消にしました")
        opens_by_date[o["date"]] = {c: v["open"] for c, v in got.items()}
    nikkei = get_nikkei(p, fetch=fetch)
    if not nikkei:
        return error(f"{p} の日経平均を取得できませんでした")
    bench_open = None
    if not state.get("benchmark", {}).get("start_open"):
        first = next((o["date"] for _, o in pending if opens_by_date[o["date"]]), None)
        if first:
            bm = get_nikkei(date.fromisoformat(first), fetch=fetch)
            if not bm:
                return error(f"{first} の日経平均を取得できませんでした")
            bench_open = {"start_open": bm["open"], "start_date": first}

    # 配当・分割（権利落ち日がまだ反映していない日〜前営業日のもの）
    from kabu import corporate
    acts, act_failed = {}, []
    if use_actions:
        since = corporate.day_after(state["actions_through"]) if state.get("actions_through")             else date.fromisoformat(state["start_date"])
        codes = list(state["holdings"]) + [x["code"] for _, o in pending for x in o.get("buys", [])]
        acts, act_failed = corporate.collect(codes, since, p, fetch=actions_fetch)
        if act_failed:
            notes.append(f"配当・分割の確認ができませんでした（{', '.join(act_failed)}）。次回に確認します")

    # 日付順に、その日の配当・分割 → その日の注文、の順で反映する
    old_trades = read_rows(data_dir / "trades.csv")
    new_trades = []
    for d in sorted(set(acts) | {o["date"] for _, o in pending}):
        if d in acts:
            new_trades += corporate.apply(state, old_trades + new_trades, d, acts[d])
        for f, o in pending:
            if o["date"] == d:
                state, tr = settle(state, o, opens_by_date[d], _ref_closes(data_dir, d))
                new_trades += tr
    last_closes = state.get("last_closes", {})   # 分割で調整された場合に備えて取り直す
    if bench_open:
        state["benchmark"] = bench_open

    held = list(state["holdings"])
    closes_raw = get_day_prices(held, p, fetch=fetch) if held else {}
    if held and not closes_raw:
        return error(f"{p} の終値を取得できませんでした")
    closes = {**{c: v for c, v in last_closes.items() if c in state["holdings"]},
              **{c: v["close"] for c, v in closes_raw.items()}}
    v = valuation(state, closes)
    start_open = state.get("benchmark", {}).get("start_open")
    bench = int(START_CASH * nikkei["close"] / start_open) if start_open else START_CASH

    # ここから書き込み
    if new_trades:
        _write_rows(data_dir / "trades.csv", TRADE_FIELDS, old_trades + new_trades)
    if use_actions and not act_failed:
        state["actions_through"] = p.isoformat()
    for f, o in pending:
        o["settled"] = True
        _write_json(f, o)
    hp = data_dir / "history.csv"
    hist = [r for r in read_rows(hp) if r["date"] != p.isoformat()]
    hist.append({"date": p.isoformat(), **v, "nikkei_close": round(nikkei["close"], 2),
                 "benchmark_value": bench})
    hist.sort(key=lambda r: r["date"])
    _write_rows(hp, HIST_FIELDS, hist)
    state["last_closes"] = closes
    state["last_date"] = p.isoformat()
    _write_json(state_p, state)
    msg = f"{p} 分を確定しました（約定等 {len(new_trades)} 件）"
    for t in new_trades:
        if t["side"] in ("配当", "分割"):
            notes.append(f"{t['name']}：{t['reason']}" + (f" {t['amount']:,}円を入金" if t["side"] == "配当" else ""))
        elif t["status"] == "見送り" and str(t.get("reason", "")).startswith("始値が"):
            notes.append(f"{t['name']} の買いは見送り（{t['reason'].split('。')[0]}）")
    if notes:
        msg += "。" + "。".join(notes)
    return {**base, "status": "ok", "holdings": _holdings_view(state, closes), "total": v["total"],
            "message": msg}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--data", default="data")
    ap.add_argument("--even-if-holiday", action="store_true", help="休場日でも前営業日分を確定・評価する（週次まとめ用）")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else jst_today()
    print(json.dumps(run(today, Path(a.data), even_if_holiday=a.even_if_holiday), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
