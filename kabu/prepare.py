"""早朝の準備（GitHub Actions で実行）：売買の確定と朝の資料作成をまとめて行い、
data/daily/<today>/ に settle.json・briefing.md・briefing.json を保存する。

使い方: python -m kabu.prepare [--today 2026-11-10] [--root .] [--force]

同じ日に何度動いても安全にしてある：
- 確定が済んでいる日は、確定結果（settle.json）を「失敗」で上書きしない。
- 朝の資料は、取引開始（8:50）より後には作り直さない（7時の判断に使った資料を残す。
  GitHub の定時実行が数時間遅れて取引時間中に動くことがあるため）。--force で作り直せる。
"""
import argparse
import json
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

DONE = ("ok", "nothing", "holiday")
MARKET_OPEN = time(8, 50)


def jst_now(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.astimezone(timezone.utc) + timedelta(hours=9)


def _read(p: Path) -> dict | None:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run(root: Path, today: date, settle_fn=None, build_fn=None, now: datetime | None = None,
        force: bool = False) -> dict:
    from kabu import briefing, settle
    settle_fn = settle_fn or settle.run
    build_fn = build_fn or briefing.build
    root = Path(root)
    daily = root / "data" / "daily" / today.isoformat()
    daily.mkdir(parents=True, exist_ok=True)
    sp, bp = daily / "settle.json", daily / "briefing.md"
    before = _read(sp) if sp.exists() else None

    res = settle_fn(today, root / "data")
    if before and before.get("status") in DONE and res.get("status") not in DONE and not force:
        res = before   # 済んでいる日を失敗で上書きしない
    else:
        sp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    if res.get("status") == "holiday":
        return res

    j = jst_now(now)
    late = j.date() > today or (j.date() == today and j.time() >= MARKET_OPEN)
    if bp.exists() and late and not force:
        return {**res, "briefing": "kept"}
    md, payload = build_fn(root, today.isoformat())
    bp.write_text(md, encoding="utf-8")
    ind = payload.pop("indicators", None)   # 全銘柄の指標は別ファイル（仕上げの点検で使う）
    if ind is not None:
        (daily / "indicators.json").write_text(json.dumps(ind, ensure_ascii=False), encoding="utf-8")
    (daily / "briefing.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return res


def main():
    from kabu.settle import jst_today
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    ap.add_argument("--force", action="store_true", help="確定結果と朝の資料を必ず作り直す")
    a = ap.parse_args()
    today = date.fromisoformat(a.today) if a.today else jst_today()
    print(json.dumps(run(Path(a.root), today, force=a.force), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
