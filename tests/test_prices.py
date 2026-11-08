from datetime import date
from kabu import prices

D = date(2026, 11, 6)

def test_missing_code_is_omitted():
    def fake(ticker, d):
        return None if ticker == "9999.T" else {"open": 100.0, "close": 110.0}
    got = prices.get_day_prices(["7203", "9999"], D, fetch=fake)
    assert got == {"7203": {"open": 100.0, "close": 110.0}}

def test_nikkei_uses_index_ticker():
    seen = []
    def fake(ticker, d):
        seen.append(ticker)
        return {"open": 50000.0, "close": 50100.0}
    assert prices.get_nikkei(D, fetch=fake)["close"] == 50100.0
    assert seen == ["^N225"]

def test_fallback_to_secondary_when_primary_raises():
    def primary(t, d):
        raise RuntimeError("blocked")
    def secondary(t, d):
        return {"open": 1.0, "close": 2.0}
    assert prices.fetch_with_fallback("7203.T", D, primary, secondary) == {"open": 1.0, "close": 2.0}

def test_fallback_when_primary_returns_none():
    assert prices.fetch_with_fallback("7203.T", D, lambda t, d: None, lambda t, d: {"open": 3.0, "close": 4.0})["open"] == 3.0

def test_both_fail_returns_none():
    def bad(t, d):
        raise RuntimeError("x")
    assert prices.fetch_with_fallback("7203.T", D, bad, bad) is None


def test_nan_from_primary_falls_back():
    nan = float("nan")
    got = prices.fetch_with_fallback("7203.T", D, lambda t, d: {"open": nan, "close": nan},
                                     lambda t, d: {"open": 5.0, "close": 6.0})
    assert got == {"open": 5.0, "close": 6.0}

def test_nan_everywhere_is_none():
    nan = float("nan")
    assert prices.fetch_with_fallback("7203.T", D, lambda t, d: {"open": nan, "close": 1.0},
                                      lambda t, d: {"open": 0.0, "close": 1.0}) is None

def test_zero_volume_stock_bar_is_halt():
    assert prices.clean_bar("7203.T", 100.0, 100.0, 0) is None
    assert prices.clean_bar("^N225", 100.0, 101.0, 0) == {"open": 100.0, "close": 101.0}
    assert prices.clean_bar("7203.T", 100.0, 101.0, 5000) == {"open": 100.0, "close": 101.0}
