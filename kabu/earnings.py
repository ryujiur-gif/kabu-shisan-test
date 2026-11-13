"""決算発表日と配当の権利落ち日（data/earnings.csv）。

全銘柄は週1回（財務データ更新と同時）、持ち株は毎朝取り直す。
日付は Yahoo の予定で、会社の変更が反映されないことがあるため、買う前に検索でも確かめること。
"""
import csv
from datetime import date, timedelta
from pathlib import Path

FIELDS = ["code", "earnings", "exdiv", "asof"]
NEAR_DAYS = 2   # 決算発表が今日から2営業日以内なら「決算またぎ」とみなす


def load(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    with open(p, encoding="utf-8", newline="") as f:
        return {r["code"]: {k: (r.get(k) or "").strip() for k in FIELDS[1:]} for r in csv.DictReader(f)}


def save(path, data: dict):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for code in sorted(data):
            w.writerow({"code": code, **{k: data[code].get(k, "") for k in FIELDS[1:]}})


def _iso(x) -> str:
    try:
        return x.isoformat()[:10]
    except AttributeError:
        return ""


def parse_calendar(cal: dict | None, today: date) -> dict:
    """yfinance の calendar から、今日以降でいちばん近い決算発表日と権利落ち日を取り出す。"""
    cal = cal or {}
    eds = cal.get("Earnings Date") or []
    if not isinstance(eds, (list, tuple)):
        eds = [eds]
    future = sorted(_iso(d) for d in eds if _iso(d) >= today.isoformat())
    ex = _iso(cal.get("Ex-Dividend Date"))
    return {"earnings": future[0] if future else "", "exdiv": ex if ex >= today.isoformat() else "",
            "asof": today.isoformat()}


def fetch_calendar(code: str, today: date) -> dict:
    import yfinance as yf
    return parse_calendar(yf.Ticker(f"{code}.T").calendar, today)


def refresh(path, codes: list[str], today: date, fetch=None) -> list[str]:
    """指定した銘柄だけ取り直して保存する。取得に失敗した銘柄は前の値を残す。失敗したコードを返す。"""
    fetch = fetch or fetch_calendar
    data, failed = load(path), []
    for c in dict.fromkeys(codes):
        try:
            data[c] = fetch(c, today)
        except Exception:
            failed.append(c)
    save(path, data)
    return failed


def trading_days_until(today: date, target: date) -> int:
    """today から target までの営業日数（today 当日は0）。target が過去なら -1。"""
    from kabu.market_calendar import is_trading_day
    if target < today:
        return -1
    n, d = 0, today
    while d < target:
        d += timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return n


def near(data: dict, code: str, today: date, within: int = NEAR_DAYS) -> str | None:
    """決算発表日が今日〜within営業日以内なら、その日付を返す。"""
    e = (data.get(code) or {}).get("earnings")
    if not e:
        return None
    try:
        n = trading_days_until(today, date.fromisoformat(e))
    except ValueError:
        return None
    return e if 0 <= n <= within else None


def upcoming(data: dict, today: date, days: int = 10, key: str = "earnings") -> list[tuple[str, str]]:
    end = (today + timedelta(days=days)).isoformat()
    out = [(v[key], c) for c, v in data.items() if v.get(key) and today.isoformat() <= v[key] <= end]
    return sorted(out)


def briefing_lines(data: dict, today: date, held: dict, names: dict) -> list[str]:
    """朝の資料に載せる「決算発表・権利落ちの予定」。held は {コード: 名前}。"""
    if not data:
        return []
    L = ["", "### 決算発表・配当の権利落ちの予定（Yahoo の予定。買う前に検索でも確かめる）", ""]
    for c, name in held.items():
        v = data.get(c) or {}
        e, x = v.get("earnings"), v.get("exdiv")
        flag = "　**← 2営業日以内。決算またぎに注意**" if near(data, c, today) else ""
        L.append(f"- 持ち株 {name}({c})：決算発表 {e or '未定'}／権利落ち日 {x or '未定'}{flag}")
    if not held:
        L.append("- 持ち株はありません")
    soon = [(d, c) for d, c in upcoming(data, today, 7) if c not in held]
    if soon:
        L.append("- 1週間以内に決算発表の銘柄：" + "、".join(f"{names.get(c, c)}({c}) {d[5:]}" for d, c in soon[:40])
                 + (" ほか" if len(soon) > 40 else ""))
    L.append(f"- **決算発表が今日〜{NEAR_DAYS}営業日以内の銘柄は、原則として買わない**"
             "（結果しだいで大きく動くため。買うなら期待度「低」まで）")
    return L
