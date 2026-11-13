"""週末のまとめメール（data/weekly/latest.json）を作る。

使い方: python -m kabu.weekly [--today 2026-11-14] [--root .]
土曜の朝に GitHub Actions で動かす（その前に kabu.settle --even-if-holiday で金曜分を確定しておく）。
"""
import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from kabu.ledger import START_CASH, funds
from kabu.market_calendar import previous_trading_day


def _yen(n) -> str:
    return f"{int(n):,}円"


def _signed(n) -> str:
    return f"{'+' if n >= 0 else '-'}{abs(int(n)):,}円"


def week_start(last_day: date) -> date:
    return last_day - timedelta(days=last_day.weekday())


def build(root: Path, today: date) -> dict:
    from kabu import stats
    from kabu.events import load_events, upcoming
    from kabu.picks import load_sectors
    from kabu.report import NOTE, after_tax_line, trade_line
    from kabu.settle import read_rows
    root = Path(root)
    data = root / "data"
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))
    hist = read_rows(data / "history.csv")
    trades = read_rows(data / "trades.csv")
    cfg_p = root / "config.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    last = date.fromisoformat(hist[-1]["date"]) if hist else previous_trading_day(today)
    ws = week_start(last)
    wk = stats.period_change(hist, ws.isoformat())
    subject = f"【株予想・週まとめ】{ws.month}/{ws.day}〜{last.month}/{last.day}"
    L = [f"■ 今週のまとめ（{ws.month}/{ws.day}〜{last.month}/{last.day}）", ""]
    if wk:
        diff = wk["mine"] - wk["bench"]
        subject += f" 今週 {wk['mine']:+.2f}%（日経平均 {wk['bench']:+.2f}%）"
        L += ["【今週の成績】",
              f"予想どおり売買：{wk['mine']:+.2f}%（{_yen(wk['start_total'])} → {_yen(wk['total'])}）",
              f"日経平均：{wk['bench']:+.2f}%",
              f"差：{diff:+.2f}ポイント（{'日経平均を上回りました' if diff > 0 else '日経平均を下回りました' if diff < 0 else '同じ'}）", ""]
    else:
        L += ["今週の成績の記録はまだありません。", ""]
    if hist:
        h = hist[-1]
        total, bench = int(h["total"]), int(h["benchmark_value"])
        L += ["【運用開始からの成績】",
              f"総資産：{_yen(total)}（{h['date']} 終値時点・{len(hist)}営業日）",
              f"損益：{_signed(total - START_CASH)}（{(total / START_CASH - 1) * 100:+.2f}%）",
              f"日経平均に同額投資した場合：{_yen(bench)}（{(bench / START_CASH - 1) * 100:+.2f}%）",
              f"日経平均との差：{_signed(total - bench)}",
              after_tax_line(total, trades, float(cfg.get("fee_rate", 0.0)))]
        dd = stats.max_drawdown(hist)
        if dd and dd["pct"] < 0:
            L.append(f"最大下落幅：{dd['pct']:.2f}%（{dd['peak_date'][5:]} の最高額から {dd['date'][5:]} まで）")
        L.append("")
    week_trades = [t for t in trades if t["date"] >= ws.isoformat()]
    L.append("【今週の売買・配当】")
    L += [f"{t['date'][5:]} " + trade_line(t).lstrip("・") for t in week_trades] or ["なし"]
    L.append("")
    closes = state.get("last_closes", {})
    if state["holdings"]:
        L.append("【持ち株】")
        for c, h in state["holdings"].items():
            px = closes.get(c, h["avg_cost"])
            pl = (px - h["avg_cost"]) * h["shares"]
            L.append(f"・{h['name']}（{c}）{h['shares']:,}株 取得{h['avg_cost']:,.1f}→{px:,.1f}円 "
                     f"{_signed(pl)}（{(px / h['avg_cost'] - 1) * 100:+.2f}%）")
        f = funds(state)
        try:
            sw = stats.sector_weights(f["values"], load_sectors(data / "nikkei225.csv"), f["total"])
            L.append("業種の比率：" + "／".join(f"{k} {v:.0%}" for k, v in sw.items()) + f"／現金 {f['cash_ratio']:.0%}")
        except OSError:
            pass
        L.append("")
    rv = None
    try:
        rv = json.loads((data / "review" / "review.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    if rv and rv.get("n_buys"):
        L.append("【予想の振り返り】")
        s = rv.get("overall") or {}
        if s.get("n"):
            beat = "" if s.get("beat") is None else f"・日経平均を上回った割合 {s['beat']}%"
            L.append(f"評価済みの買い予想 {s['n']}件：上昇した割合 {s['win']}%{beat}・平均 {s['avg_ret']:+.2f}%")
        else:
            L.append("評価済みの買い予想はまだありません（買ってから5営業日後に評価します）")
        pf = rv.get("portfolio")
        if pf:
            L.append(f"日経平均との差 {pf['diff']:+.2f}ポイントの内訳（概算）：現金で持っていた分 {pf['cash_part']:+.2f}／"
                     f"銘柄選びの分 {pf['selection_part']:+.2f}")
        for p in (rv.get("patterns") or [])[:3]:
            L.append(f"・【{p['level']}・{p['kind']}】{p['bucket']}（{p['n']}件）→ {p['advice']}")
        L.append("")
    ev = upcoming(load_events(data / "events.csv"), today, days=9)
    L.append("【来週の主な予定】")
    L += [f"・{e['start'].month}/{e['start'].day} {e['event']}（重要度：{e['importance'] or '-'}）" for e in ev] or ["・登録された予定はありません"]
    L += ["", f"成績ページ：{cfg.get('site_url', '')}", "", NOTE]
    return {"made": today.isoformat(), "through": hist[-1]["date"] if hist else None,
            "subject": subject, "body": "\n".join(L) + "\n"}


def main():
    from kabu.settle import jst_today
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else jst_today()
    out = build(Path(a.root), today)
    d = Path(a.root) / "data" / "weekly"
    d.mkdir(parents=True, exist_ok=True)
    text = json.dumps(out, ensure_ascii=False, indent=2)
    (d / "latest.json").write_text(text, encoding="utf-8")
    (d / f"{today.isoformat()}.json").write_text(text, encoding="utf-8")
    print(out["subject"])
    print(out["body"])


if __name__ == "__main__":
    main()
