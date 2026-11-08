"""仕上げ：注文を検証し、メール文面(out/email.json)と成績ページ(docs/index.html)を作る。

使い方: python -m kabu.finalize [--today 2026-11-10]（省略時は日本時間の今日）
終了コード 1 のときは表示されたエラーを直して注文ファイルを書き直し、再実行する。
"""
import argparse
import json
import sys
from pathlib import Path

from kabu.picks import load_universe, validate_order
from kabu.report import build_email, build_site
from kabu.settle import jst_today, read_rows


def run(today: str, root: Path, universe=None) -> tuple[int, list[str]]:
    root = Path(root)
    data = root / "data"
    state = json.loads((data / "state.json").read_text(encoding="utf-8"))
    order_p = data / "orders" / f"{today}.json"
    if not order_p.exists():
        return 1, [f"{order_p} がありません"]
    try:
        order = json.loads(order_p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return 1, [f"注文ファイルが JSON として読めません: {e}"]
    universe = universe if universe is not None else load_universe(data / "nikkei225.csv")
    errs = validate_order(order, state, universe, today=today)
    if errs:
        return 1, errs
    hist = read_rows(data / "history.csv")
    trades = read_rows(data / "trades.csv")
    last_date = max((t["date"] for t in trades), default=None)
    last = [t for t in trades if t["date"] == last_date]
    cfg_p = root / "config.json"
    site_url = json.loads(cfg_p.read_text(encoding="utf-8"))["site_url"] if cfg_p.exists() else ""
    (root / "out").mkdir(exist_ok=True)
    (root / "out" / "email.json").write_text(
        json.dumps(build_email(order, state, hist, last, site_url), ensure_ascii=False, indent=2),
        encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "index.html").write_text(build_site(state, hist, trades, order), encoding="utf-8")
    return 0, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    code, errs = run(a.today or jst_today().isoformat(), Path(a.root))
    for e in errs:
        print("エラー:", e)
    if code == 0:
        print("OK: out/email.json と docs/index.html を作成しました")
    sys.exit(code)


if __name__ == "__main__":
    main()
