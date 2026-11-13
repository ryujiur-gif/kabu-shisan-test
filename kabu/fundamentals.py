"""財務・割安度データ（週1回更新）：PER・PBR・ROE・自己資本比率・配当利回りなど。

使い方: python -m kabu.fundamentals   → data/fundamentals.csv を更新
"""
import csv
import math
from pathlib import Path

FIELDS = ["per", "fper", "pbr", "roe", "div_yield", "mcap_oku", "op_margin", "rev_growth", "equity_ratio",
          "div_streak"]


def _num(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def parse_fundamentals(info: dict, equity_ratio: float | None, div_streak: int | None = None) -> dict:
    g = lambda k: _num(info.get(k))
    per = g("trailingPE")
    fper = g("forwardPE")
    pct = lambda k: _r(g(k) * 100, 2) if g(k) is not None else None
    mcap = g("marketCap")
    return {
        "per": _r(per) if per and per > 0 else None,
        "fper": _r(fper) if fper and fper > 0 else None,
        "pbr": _r(g("priceToBook")),
        "roe": pct("returnOnEquity"),
        "div_yield": pct("trailingAnnualDividendYield"),
        "mcap_oku": int(mcap / 1e8) if mcap else None,
        "op_margin": pct("operatingMargins"),
        "rev_growth": pct("revenueGrowth"),
        "equity_ratio": _r(equity_ratio, 1),
        "div_streak": div_streak,
    }


def div_growth_years(divs, current_fy: int) -> int | None:
    """年度（4月〜翌3月）ごとの配当合計が何年連続で増えているか。進行中の年度は除く。データ無しは None。"""
    if divs is None:
        return None
    if len(divs) == 0:
        return 0
    fy = [d.year if d.month >= 4 else d.year - 1 for d in divs.index]
    yearly = divs.groupby(fy).sum()
    yearly = yearly[yearly.index < current_fy]
    vals = [float(v) for v in yearly.values]
    n = 0
    for i in range(len(vals) - 1, 0, -1):
        if vals[i] > vals[i - 1] * 1.0001:
            n += 1
        else:
            break
    return n


def equity_ratio_from(bs) -> float | None:
    """直近の貸借対照表から自己資本比率(%)を計算。"""
    try:
        if bs is None or bs.empty:
            return None
        col = bs.columns[0]
        eq = _num(bs.loc["Stockholders Equity", col])
        ta = _num(bs.loc["Total Assets", col])
        return round(eq / ta * 100, 2) if eq is not None and ta else None
    except (KeyError, IndexError):
        return None


def save_fundamentals(path: Path, date: str, data: dict):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "code"] + FIELDS)
        for code, d in sorted(data.items()):
            w.writerow([date, code] + ["" if d.get(k) is None else d.get(k) for k in FIELDS])


def load_fundamentals(path: Path) -> tuple[str | None, dict]:
    path = Path(path)
    if not path.exists():
        return None, {}
    out, date = {}, None
    with open(path, encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            date = row["date"]
            out[row["code"]] = {k: _num(row.get(k)) if row.get(k) not in ("", None) else None for k in FIELDS}
    return date, out


def fetch_one(code: str) -> dict | None:
    import yfinance as yf
    t = yf.Ticker(f"{code}.T")
    try:
        info = t.info or {}
    except Exception:
        info = {}
    try:
        er = equity_ratio_from(t.quarterly_balance_sheet)
    except Exception:
        er = None
    try:
        from datetime import date
        today = date.today()
        streak = div_growth_years(t.dividends, today.year if today.month >= 4 else today.year - 1)
    except Exception:
        streak = None
    if not info and er is None:
        return None
    out = parse_fundamentals(info, er, streak)
    try:   # 決算発表日・権利落ち日（data/earnings.csv に保存する）
        from datetime import date
        from kabu.earnings import parse_calendar
        out["_calendar"] = parse_calendar(t.calendar, date.today())
    except Exception:
        pass
    return out


def main():
    import time
    from kabu.picks import load_universe
    from kabu.settle import jst_today
    codes = list(load_universe())
    data, failed = {}, []
    for c in codes:
        got = None
        for attempt in range(2):
            try:
                got = fetch_one(c)
                break
            except Exception:
                time.sleep(2)
        if got:
            data[c] = got
        else:
            failed.append(c)
    save_fundamentals(Path("data/fundamentals.csv"), jst_today().isoformat(), data)
    from kabu import earnings
    cal = earnings.load("data/earnings.csv")
    cal.update({c: d["_calendar"] for c, d in data.items() if d.get("_calendar")})
    earnings.save("data/earnings.csv", cal)
    print(f"取得 {len(data)} / {len(codes)} 銘柄。失敗: {', '.join(failed) or 'なし'}")
    if len(data) < len(codes) * 0.8:
        raise SystemExit("取得できた銘柄が少なすぎます")


if __name__ == "__main__":
    main()
