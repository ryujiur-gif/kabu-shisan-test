"""注文JSONの検証と対象銘柄一覧。"""
import csv
from pathlib import Path

CONFIDENCES = ("高", "中", "低")
OUTLOOKS = ("上昇", "横ばい", "下落")
OUTLOOK_WORDS = {"上昇": "まだ上がりそう", "横ばい": "横ばい", "下落": "まだ下がりそう"}


def load_universe(path="data/nikkei225.csv") -> dict[str, str]:
    with open(Path(path), encoding="utf-8") as f:
        return {r["code"]: r["name"] for r in csv.DictReader(f)}


def load_sectors(path="data/nikkei225.csv") -> dict[str, str]:
    with open(Path(path), encoding="utf-8") as f:
        return {r["code"]: r.get("sector", "") for r in csv.DictReader(f)}


PORTION_WORDS = ("全部", "半分")


def validate_order(order: dict, state: dict, universe: dict, today: str | None = None,
                   sectors: dict | None = None) -> list[str]:
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
        if s.get("portion", "全部") not in PORTION_WORDS:
            errs.append(f"売り {s.get('code')} の portion は「全部」か「半分」にしてください")
        elif s.get("portion") == "半分" and held.get(s.get("code"), {}).get("shares", 0) < 2:
            errs.append(f"売り {s.get('code')} は1株しか無いので「半分」にできません（「全部」にするか保有を続ける）")
    for x in buys + sells:
        if not str(x.get("reason", "")).strip():
            errs.append(f"{x.get('code')} の理由が空です")
    if not str(order.get("summary", "")).strip():
        errs.append("市況の要約(summary)が空です")
    errs += _check_holds(order.get("holds", []), held,
                         {s.get("code") for s in sells if s.get("portion", "全部") == "全部"})
    if not errs:
        errs += check_funds(order, state, sectors)
    return errs


def check_funds(order: dict, state: dict, sectors: dict | None = None) -> list[str]:
    """総資産に対して、買った後の現金比率・1銘柄の比率・1業種の比率が上限・下限を守っているか（前日終値で試算）。"""
    from kabu.ledger import (MAX_SECTOR_RATIO, MAX_STOCK_RATIO, MIN_CASH_RATIO, PORTIONS, amount_for, funds,
                             sell_shares)
    f = funds(state)
    total = f["total"]
    if total <= 0:
        return []
    # 売った後に残る評価額（一部売却は残りを数える）
    values = dict(f["values"])
    cash = f["cash"]
    for s in order["sells"]:
        c = s["code"]
        h = state["holdings"].get(c)
        if not h or c not in values:
            continue
        n = sell_shares(h["shares"], s.get("portion"))
        part = values[c] * n / h["shares"]
        cash += part
        values[c] -= part
    errs = []
    for b in order["buys"]:
        amt = amount_for(b["confidence"], total)
        cash -= amt
        values[b["code"]] = values.get(b["code"], 0) + amt
        after = values[b["code"]]
        if after > total * MAX_STOCK_RATIO:
            errs.append(f"買い {b['code']} の保有額が総資産の{after / total:.0%}になります（上限{MAX_STOCK_RATIO:.0%}）。期待度を下げるか見送ってください")
    if sectors and order["buys"]:
        by = {}
        for c, v in values.items():
            by[sectors.get(c) or "その他"] = by.get(sectors.get(c) or "その他", 0) + v
        for b in order["buys"]:
            sec = sectors.get(b["code"]) or "その他"
            if by.get(sec, 0) > total * MAX_SECTOR_RATIO:
                errs.append(f"買い {b['code']} で業種「{sec}」の保有額が総資産の{by[sec] / total:.0%}になります"
                            f"（上限{MAX_SECTOR_RATIO:.0%}）。別の業種を選ぶか、期待度を下げてください")
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


RSI_LIMIT = 75.0       # これ以上は飛びつき買いとして買わない（ROUTINE.md 手順4-3 b）
MA25_LIMIT = 15.0
CASES_PER_DAY = 3      # 1日に求める振り返りの件数の上限


def check_entry_rules(order: dict, indicators: dict | None, imminent: list | None,
                      earnings: dict | None = None, today: str | None = None) -> list[str]:
    """手順書で「買わない」と決めている条件を、数値で確かめる（朝の資料の指標がある日だけ）。"""
    errs = []
    for b in order.get("buys", []):
        if earnings and today:
            from datetime import date
            from kabu.earnings import near
            e = near(earnings, b.get("code"), date.fromisoformat(today))
            if e and b.get("confidence") in ("高", "中"):
                errs.append(f"買い {b.get('code')} は決算発表（{e}）が2営業日以内です。"
                            "決算またぎになるので見送るか、期待度を「低」にしてください"
                            "（日付が違っていると確認できた場合は、理由にその旨を書いて「低」で）")
        x = (indicators or {}).get(b.get("code")) or {}
        rsi, dev = x.get("rsi14"), x.get("ma25_dev")
        if rsi is not None and rsi >= RSI_LIMIT:
            errs.append(f"買い {b.get('code')} は RSI {rsi:.0f}（{RSI_LIMIT:.0f}以上）で過熱しています。見送ってください")
        if dev is not None and dev >= MA25_LIMIT:
            errs.append(f"買い {b.get('code')} は25日線から +{dev:.1f}%（+{MA25_LIMIT:.0f}%以上）離れています。見送ってください")
        if imminent and b.get("confidence") in ("高", "中"):
            errs.append(f"今日〜明日に重要イベント（{'・'.join(imminent[:2])}）があります。"
                        f"買い {b.get('code')} は見送るか、期待度を「低」にしてください")
    return errs


def check_learning(order: dict, review: dict | None, journal_text: str, playbook_text: str) -> list[str]:
    """振り返り（journal.md）・ルール集（playbook.md）・今日の反映（learned）が書かれているか。"""
    import re
    if not review or not review.get("n_buys"):
        return []
    errs = []
    due = [c for c in review.get("cases_due") or []
           if not re.search(r"^" + re.escape(c["key"]) + r"\b", journal_text or "", re.M)][:CASES_PER_DAY]
    for c in due:
        errs.append(f"振り返りが未記入です。data/review/journal.md に「{c['key']} …」の見出しで書いてください（{c['title']}）")
    if (review.get("cases_due") or review.get("overall", {}).get("n")) and not (playbook_text or "").strip():
        errs.append("data/review/playbook.md（傾向と対策のルール集）がありません。ROUTINE.md 手順2.5で作成してください")
    if len(str(order.get("learned", "")).strip()) < 10:
        errs.append("注文ファイルに learned（過去の振り返りを今日の判断にどう反映したか。1〜2文）を書いてください")
    return errs


def pattern_cautions(order: dict, indicators: dict | None, review: dict | None, context: dict | None,
                     meta: dict | None = None) -> list[str]:
    """今日の買いが、過去に成績の悪かった条件（弱み）に当てはまる場合の注意文。"""
    from kabu.review import matching_patterns, tags_of
    out = []
    pats = (review or {}).get("patterns") or []
    for b in order.get("buys", []):
        x = (indicators or {}).get(b.get("code")) or {}
        feat = {"confidence": b.get("confidence"), "tags": tags_of(b.get("reason", "")),
                "rsi14": x.get("rsi14"), "ma25_dev": x.get("ma25_dev"), "chg1d": x.get("chg1d"),
                "vol_ratio": x.get("vol_ratio"), **(context or {}), **((meta or {}).get(b.get("code")) or {})}
        for p in matching_patterns(feat, pats):
            out.append(f"{b.get('name')}（{b.get('code')}）は過去の弱みの条件「{p['bucket']}」に当てはまります"
                       f"（{p['level']}・{p['n']}件・日経平均との差 {p.get('avg_x') if p.get('avg_x') is not None else p['avg_ret']:+.2f}%）。"
                       f"対策：{p['advice']}")
    return out
