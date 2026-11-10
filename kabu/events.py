"""経済イベントの日程表（data/events.csv）。

検索に頼らず、FOMC・日銀会合・SQ・休場日など日程が公表済みのものを資料に載せる。
列：date, end_date, event, importance（高/中/低）, note, checked（検索で確認した日。空なら要確認）
"""
import csv
from datetime import date, timedelta
from pathlib import Path

FIELDS = ["date", "end_date", "event", "importance", "note", "checked"]


def load_events(path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        return []
    with open(p, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        try:
            s = date.fromisoformat((r.get("date") or "").strip())
            e = date.fromisoformat((r.get("end_date") or "").strip() or r["date"].strip())
        except ValueError:
            continue
        out.append({**{k: (r.get(k) or "").strip() for k in FIELDS}, "start": s, "end": e})
    return sorted(out, key=lambda r: (r["start"], r["end"]))


def upcoming(events: list[dict], today: date, days: int = 14) -> list[dict]:
    end = today + timedelta(days=days)
    return [e for e in events if e["end"] >= today and e["start"] <= end]


def imminent_high(events: list[dict], today: date) -> list[dict]:
    """今日〜明日に重なる重要度「高」のイベント（買いを控える目安）。"""
    tomorrow = today + timedelta(days=1)
    return [e for e in events if e["importance"] == "高" and e["start"] <= tomorrow and e["end"] >= today]


def last_checked(events: list[dict]) -> str | None:
    ds = [e["checked"] for e in events if e["checked"]]
    return max(ds) if ds else None


def needs_review(events: list[dict], today: date, max_age_days: int = 7) -> bool:
    chk = last_checked(events)
    if not chk:
        return True
    try:
        return (today - date.fromisoformat(chk)).days >= max_age_days
    except ValueError:
        return True


def _span(e: dict) -> str:
    s = e["start"].strftime("%m/%d")
    return s if e["end"] == e["start"] else f"{s}〜{e['end'].strftime('%m/%d')}"


def events_lines(events: list[dict], today: date) -> list[str]:
    L = ["", "### 今週・来週の主な予定（data/events.csv より）", ""]
    up = upcoming(events, today)
    if not up:
        L.append("- 2週間以内に登録されたイベントはありません")
    for e in up:
        flag = "" if e["checked"] else "【要確認：検索で日付を確かめる】"
        L.append(f"- {_span(e)} {e['event']}（重要度：{e['importance'] or '-'}）{flag} {e['note']}".rstrip())
    hi = imminent_high(events, today)
    if hi:
        L.append(f"- **今日〜明日に重要イベント（{'・'.join(e['event'] for e in hi)}）→ 買いは原則見送り。買うなら期待度「低」まで**")
    chk = last_checked(events)
    tail = "7日以上たっているので、手順3で今後3週間の予定を調べて data/events.csv を更新すること" \
        if needs_review(events, today) else "更新は不要"
    L.append(f"- 日程表の最終確認日：{chk or '未確認'}（{tail}）")
    return L
