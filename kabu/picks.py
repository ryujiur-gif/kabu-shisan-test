"""注文JSONの検証と対象銘柄一覧。"""
import csv
from pathlib import Path

CONFIDENCES = ("高", "中", "低")
OUTLOOKS = ("上昇", "横ばい", "下落")
OUTLOOK_WORDS = {"上昇": "まだ上がりそう", "横ばい": "横ばい", "下落": "まだ下がりそう"}


def load_universe(path="data/nikkei225.csv") -> dict[str, str]:
    with open(Path(path), encoding="utf-8") as f:
        return {r["code"]: r["name"] for r in csv.DictReader(f)}


def validate_order(order: dict, state: dict, universe: dict, today: str | None = None) -> list[str]:
    if not isinstance(order, dict):
        return ["注文ファイルの形式が正しくありません"]
    buys, sells = order.get("buys"), order.get("sells")
    if not isinstance(buys, list) or not isinstance(sells, list) or             not all(isinstance(x, dict) for x in buys + sells):
        return ["buys と sells は銘柄({...})のリストにしてください"]
    errs = []
    if today is not None and order.get("date") != today:
        errs.append(f"date は {today} にしてください（現在 {order.get('date')}）")
    if order.get("settled", False) is not False:
        errs.append("settled は false にしてください")
    for x in buys + sells:
        if not str(x.get("name", "")).strip():
            errs.append(f"{x.get('code')} の name（銘柄名）が空です")
    held = state["holdings"]
    if len(buys) > 2:
        errs.append(f"買い銘柄は0〜2つにしてください（現在{len(buys)}）")
    if len({b.get('code') for b in buys}) != len(buys):
        errs.append("買い銘柄が重複しています")
    for b in buys:
        if b.get("code") not in universe:
            errs.append(f"買い {b.get('code')} は日経225の銘柄ではありません")
        if b.get("confidence") not in CONFIDENCES:
            errs.append(f"買い {b.get('code')} の期待度は 高/中/低 のいずれかにしてください")
    if len(sells) > 2:
        errs.append(f"売り銘柄は0〜2つにしてください（現在{len(sells)}）")
    if len({s.get('code') for s in sells}) != len(sells):
        errs.append("売り銘柄が重複しています")
    for s in sells:
        if s.get("code") not in held:
            errs.append(f"売り {s.get('code')} は持ち株にありません")
    for x in buys + sells:
        if not str(x.get("reason", "")).strip():
            errs.append(f"{x.get('code')} の理由が空です")
    if not str(order.get("summary", "")).strip():
        errs.append("市況の要約(summary)が空です")
    errs += _check_holds(order.get("holds", []), held, {s.get("code") for s in sells})
    if not errs:
        errs += check_funds(order, state)
    return errs


def check_funds(order: dict, state: dict) -> list[str]:
    """総資産に対して、買った後の現金比率と1銘柄の比率が上限・下限を守っているか（前日終値で試算）。"""
    from kabu.ledger import MAX_STOCK_RATIO, MIN_CASH_RATIO, amount_for, funds
    f = funds(state)
    total = f["total"]
    if total <= 0:
        return []
    sold = {s["code"] for s in order["sells"]}
    cash = f["cash"] + sum(f["values"][c] for c in sold if c in f["values"])
    errs = []
    for b in order["buys"]:
        amt = amount_for(b["confidence"], total)
        cash -= amt
        after = (0 if b["code"] in sold else f["values"].get(b["code"], 0)) + amt
        if after > total * MAX_STOCK_RATIO:
            errs.append(f"買い {b['code']} の保有額が総資産の{after / total:.0%}になります（上限{MAX_STOCK_RATIO:.0%}）。期待度を下げるか見送ってください")
    if order["buys"] and cash < total * MIN_CASH_RATIO:
        errs.append(f"買った後の現金比率が{max(cash, 0) / total:.0%}になります（下限{MIN_CASH_RATIO:.0%}）。"
                    "期待度を下げる・銘柄数を減らす・持ち株を入れ替える（売る）のいずれかにしてください")
    return errs


def _check_holds(holds, held: dict, sold: set) -> list[str]:
    """売らない持ち株すべてに、見通し（上昇/横ばい/下落）と理由があるかを確認する。"""
    if not isinstance(holds, list) or not all(isinstance(x, dict) for x in holds):
        return ["holds は銘柄({...})のリストにしてください"]
    errs = []
    by_code = {x.get("code"): x for x in holds}
    for code, h in held.items():
        if code in sold:
            continue
        x = by_code.get(code)
        if x is None:
            errs.append(f"持ち株 {code}（{h.get('name', '')}）の見通しが holds にありません")
            continue
        if x.get("outlook") not in OUTLOOKS:
            errs.append(f"持ち株 {code} の見通し(outlook)は 上昇/横ばい/下落 のいずれかにしてください")
        if not str(x.get("reason", "")).strip():
            errs.append(f"持ち株 {code} の見通しの理由が空です")
    for code in by_code:
        if code not in held or code in sold:
            errs.append(f"holds の {code} は売らない持ち株ではありません")
    return errs


UNKNOWN_WORDS = ("不明", "確認できず", "未確認", "調査できず", "見つからず")


def note_quality(text: str) -> tuple[int, int]:
    """企業メモの箇条書き（「- 」で始まる行）のうち、「不明」などで済ませた行の数と総数。"""
    items = [l for l in text.splitlines() if l.strip().startswith("- ")]
    unknown = [l for l in items if any(w in l for w in UNKNOWN_WORDS)]
    return len(unknown), len(items)


def check_note_quality(order: dict, notes_dir, max_ratio: float = 0.5) -> tuple[list[str], list[str]]:
    """「不明」が半数を超える企業メモは、買い銘柄ならエラー、売り銘柄なら警告。"""
    errs, warns = [], []
    for kind, items in (("買い", order.get("buys", [])), ("売り", order.get("sells", []))):
        for x in items:
            p = Path(notes_dir) / f"{x.get('code')}.md"
            if not p.exists():
                continue
            u, n = note_quality(p.read_text(encoding="utf-8"))
            if n and u / n > max_ratio:
                msg = (f"{kind} {x.get('code')} の企業メモは {n} 項目中 {u} 項目が「不明」です。"
                       "会社の IR ページ・決算説明資料・株探などを WebFetch で開いて調べ直し、埋めてください")
                (errs if kind == "買い" else warns).append(msg)
    return errs, warns


def check_notes(order: dict, notes_dir, today: str, max_age_days: int = 90) -> list[str]:
    """買い・売り銘柄の企業メモ（data/notes/<コード>.md）があり、更新日が新しいかを確認する。"""
    import re
    from datetime import date
    errs = []
    t = date.fromisoformat(today)
    for x in order.get("buys", []) + order.get("sells", []):
        code = x.get("code")
        p = Path(notes_dir) / f"{code}.md"
        if not p.exists():
            errs.append(f"{code} の企業メモ data/notes/{code}.md がありません（ROUTINE.md 手順3.5で作成してください）")
            continue
        m = re.search(r"更新日[：:]\s*(\d{4}-\d{2}-\d{2})", p.read_text(encoding="utf-8"))
        if not m:
            errs.append(f"{code} の企業メモに「更新日：YYYY-MM-DD」の形で日付を書いてください")
            continue
        age = (t - date.fromisoformat(m.group(1))).days
        if age > max_age_days:
            errs.append(f"{code} の企業メモが古いです（{age}日前）。調べ直して更新してください")
    return errs
