"""早朝の準備（GitHub Actions で実行）：売買の確定と朝の資料作成をまとめて行い、
data/daily/<today>/ に settle.json・briefing.md・briefing.json を保存する。

使い方: python -m kabu.prepare [--today 2026-11-10] [--root .]
"""
import argparse
import json
from datetime import date
from pathlib import Path


def run(root: Path, today: date, settle_fn=None, build_fn=None) -> dict:
    from kabu import briefing, settle
    settle_fn = settle_fn or settle.run
    build_fn = build_fn or briefing.build
    root = Path(root)
    daily = root / "data" / "daily" / today.isoformat()
    daily.mkdir(parents=True, exist_ok=True)
    res = settle_fn(today, root / "data")
    (daily / "settle.json").write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if res.get("status") != "holiday":
        md, payload = build_fn(root, today.isoformat())
        (daily / "briefing.md").write_text(md, encoding="utf-8")
        (daily / "briefing.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def main():
    from kabu.settle import jst_today
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else jst_today()
    print(json.dumps(run(Path(a.root), today), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
