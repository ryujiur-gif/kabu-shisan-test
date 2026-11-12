"""仕上げ：注文を検証し、メール文面(out/email.json)と成績ページ(docs/index.html)を作る。

使い方: python -m kabu.finalize [--today 2026-11-10]（省略時は日本時間の今日）
終了コード 1 のときは表示されたエラーを直して注文ファイルを書き直し、再実行する。
"""
import argparse
import json
import sys
from pathlib import Path

from kabu.picks import (check_entry_rules, check_learning, check_note_quality, check_notes,
                        load_universe, pattern_cautions, validate_order)
from kabu.report import build_email, build_site
from kabu.settle import jst_today, read_rows


def notices_for(today: str, data: Path, briefing: dict | None) -> list[str]:
    """メール本文の先頭に付ける注記（データ未準備・取得失敗・一部欠け）をプログラムで決める。"""
    out = []
    sp = data / "daily" / today / "settle.json"
    if not sp.exists():
        out.append("本日は株価データの準備が間に合わなかったため、数値データなしで判断しています。売買の確定は次回にまとめて行います")
    else:
        try:
            if json.loads(sp.read_text(encoding="utf-8")).get("status") == "price_error":
                out.append("本日は株価データの取得に失敗したため、前回分の約定・評価は次回にまとめて反映します")
        except json.JSONDecodeError:
            pass
    missing = (briefing or {}).get("missing") or []
    if missing:
        out.append("本日は株価データの一部を取得できませんでした（" + "／".join(m[:40] for m in missing[:3]) + "）")
    for h in ((briefing or {}).get("health") or [])[:3]:
        out.append("データの点検：" + h)
    return out


def _load_json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run(today: str, root: Path, universe=None, check_note_files: bool = True, warn=None) -> tuple[int, list[str]]:
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
    if not errs and check_note_files:
        errs = check_notes(order, data / "notes", today)
        if not errs:
            errs, warns = check_note_quality(order, data / "notes")
            for w in warns:
                (warn or (lambda m: None))(w)
    # 朝の資料（その日のもの）・指標・振り返り
    b = _load_json(data / "daily" / today / "briefing.json") or _load_json(root / "out" / "briefing.json")
    if not b or b.get("today") != today:
        b = None
    indicators = _load_json(data / "daily" / today / "indicators.json") if b else None
    review = _load_json(data / "review" / "review.json")
    rd = data / "review"
    journal = (rd / "journal.md").read_text(encoding="utf-8") if (rd / "journal.md").exists() else ""
    playbook = (rd / "playbook.md").read_text(encoding="utf-8") if (rd / "playbook.md").exists() else ""
    if not errs and check_note_files:
        errs = check_entry_rules(order, indicators, (b or {}).get("imminent"))
        errs += check_learning(order, review, journal, playbook)
    if errs:
        return 1, errs
    cautions = pattern_cautions(order, indicators, review,
                                {"mood": b.get("mood"), "imminent": bool(b.get("imminent"))} if b else None)
    for c in cautions:
        (warn or (lambda m: None))(c)
    hist = read_rows(data / "history.csv")
    trades = read_rows(data / "trades.csv")
    last_date = max((t["date"] for t in trades), default=None)
    last = [t for t in trades if t["date"] == last_date]
    cfg_p = root / "config.json"
    site_url = json.loads(cfg_p.read_text(encoding="utf-8"))["site_url"] if cfg_p.exists() else ""
    (root / "out").mkdir(exist_ok=True)
    market, gap = (b.get("market"), b.get("gap")) if b else (None, None)
    notices = notices_for(today, data, b)
    (root / "out" / "email.json").write_text(
        json.dumps(build_email(order, state, hist, last, site_url, market=market, notices=notices, gap=gap,
                               review=review, cautions=cautions),
                   ensure_ascii=False, indent=2),
        encoding="utf-8")
    (root / "docs").mkdir(exist_ok=True)
    (root / "docs" / "index.html").write_text(build_site(state, hist, trades, order, review=review), encoding="utf-8")
    return 0, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    code, errs = run(a.today or jst_today().isoformat(), Path(a.root), warn=lambda m: print("警告:", m))
    for e in errs:
        print("エラー:", e)
    if code == 0:
        print("OK: out/email.json と docs/index.html を作成しました")
    sys.exit(code)


if __name__ == "__main__":
    main()
