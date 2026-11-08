"""株価取得。yfinance を使い、失敗したら Yahoo chart API を直接呼ぶ。"""
import math
import urllib.request
from datetime import date, timedelta

NIKKEI = "^N225"


def _ok(x) -> bool:
    try:
        return x is not None and math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def clean_bar(ticker: str, open_, close, volume):
    """欠損(NaN/0)や売買停止(出来高0)の足を None にする。指数は出来高を見ない。"""
    if not (_ok(open_) and _ok(close)):
        return None
    if ticker != NIKKEI and not (volume and volume > 0):
        return None
    return {"open": float(open_), "close": float(close)}


def fetch_yfinance(ticker: str, d: date):
    import yfinance as yf
    df = yf.Ticker(ticker).history(start=d.isoformat(), end=(d + timedelta(days=1)).isoformat(),
                                   auto_adjust=False)
    if df is None or df.empty:
        return None
    row = df.iloc[0]
    if row.name.date() != d:
        return None
    return clean_bar(ticker, row["Open"], row["Close"], row.get("Volume"))


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
    if not res.get("timestamp"):
        return None
    return clean_bar(ticker, q["open"][0], q["close"][0], (q.get("volume") or [None])[0])


def fetch_with_fallback(ticker: str, d: date, primary=fetch_yfinance, secondary=fetch_yahoo_chart):
    for f in (primary, secondary):
        try:
            got = f(ticker, d)
        except Exception:
            got = None
        if got and _ok(got.get("open")) and _ok(got.get("close")):
            return {"open": float(got["open"]), "close": float(got["close"])}
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
