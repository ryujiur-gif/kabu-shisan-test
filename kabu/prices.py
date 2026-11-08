"""株価取得。yfinance を使い、失敗したら Yahoo chart API を直接呼ぶ。"""
import urllib.request
from datetime import date, timedelta

NIKKEI = "^N225"


def fetch_yfinance(ticker: str, d: date):
    import yfinance as yf
    df = yf.Ticker(ticker).history(start=d.isoformat(), end=(d + timedelta(days=1)).isoformat(),
                                   auto_adjust=False)
    if df is None or df.empty:
        return None
    row = df.iloc[0]
    if row.name.date() != d:
        return None
    return {"open": float(row["Open"]), "close": float(row["Close"])}


def fetch_yahoo_chart(ticker: str, d: date):
    """Yahoo の chart API を直接呼ぶ予備経路（yfinance ライブラリ不調時用）。"""
    import json
    from datetime import datetime, timezone
    p1 = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()) - 9 * 3600
    p2 = p1 + 86400
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.request.quote(ticker)}"
           f"?period1={p1}&period2={p2}&interval=1d")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        res = json.load(r)["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    if not res.get("timestamp") or q["open"][0] is None:
        return None
    return {"open": float(q["open"][0]), "close": float(q["close"][0])}


def fetch_with_fallback(ticker: str, d: date, primary=fetch_yfinance, secondary=fetch_yahoo_chart):
    for f in (primary, secondary):
        try:
            got = f(ticker, d)
        except Exception:
            got = None
        if got and got.get("open") and got.get("close"):
            return got
    return None


def get_day_prices(codes: list[str], d: date, fetch=None) -> dict[str, dict]:
    fetch = fetch or fetch_with_fallback
    out = {}
    for code in dict.fromkeys(codes):
        got = fetch(f"{code}.T", d)
        if got:
            out[code] = got
    return out


def get_nikkei(d: date, fetch=None):
    fetch = fetch or fetch_with_fallback
    return fetch(NIKKEI, d)
