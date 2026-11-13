"""見張り：今日の予想が作られたかを確かめる（朝の担当が動かなかった日の検出）。

使い方: python -m kabu.watchdog [--today 2026-11-13] [--root .]
終了コード 0 = 問題なし（休場日、または今日の予想が保存済み）。1 = 今日の予想が無い。
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

from kabu.market_calendar import is_trading_day


def check(root: Path, today: date) -> tuple[bool, str]:
    if not is_trading_day(today):
        return True, f"{today} は休場日です（予想は不要）"
    p = Path(root) / "data" / "orders" / f"{today.isoformat()}.json"
    if not p.exists():
        return False, f"{today} の予想（{p.name}）がまだ保存されていません"
    try:
        o = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False, f"{today} の予想ファイルが壊れています（JSON として読めません）"
    if o.get("date") != today.isoformat() or not str(o.get("summary", "")).strip():
        return False, f"{today} の予想ファイルの中身が不完全です"
    return True, f"{today} の予想は保存済みです（買い {len(o.get('buys', []))}・売り {len(o.get('sells', []))}）"


def main():
    from kabu.settle import jst_today
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    ok, msg = check(Path(a.root), date.fromisoformat(a.today) if a.today else jst_today())
    print(("OK: " if ok else "NG: ") + msg)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
