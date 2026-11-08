import pandas as pd
from kabu.fundamentals import parse_fundamentals, equity_ratio_from, save_fundamentals, load_fundamentals


def test_parse_fundamentals():
    info = {"trailingPE": 12.345, "forwardPE": 11.0, "priceToBook": 1.234, "returnOnEquity": 0.105,
            "trailingAnnualDividendYield": 0.0312, "marketCap": 4.5e12, "operatingMargins": 0.11,
            "revenueGrowth": -0.02}
    f = parse_fundamentals(info, 41.26)
    assert f == {"per": 12.35, "fper": 11.0, "pbr": 1.23, "roe": 10.5, "div_yield": 3.12,
                 "mcap_oku": 45000, "op_margin": 11.0, "rev_growth": -2.0, "equity_ratio": 41.3}


def test_parse_handles_missing_and_negative_per():
    f = parse_fundamentals({"trailingPE": -5.0}, None)
    assert f["per"] is None and f["pbr"] is None and f["equity_ratio"] is None


def test_equity_ratio_from_balance_sheet():
    bs = pd.DataFrame({"2026-09-30": [400.0, 1000.0], "2026-06-30": [1.0, 1.0]},
                      index=["Stockholders Equity", "Total Assets"])
    assert equity_ratio_from(bs) == 40.0
    assert equity_ratio_from(None) is None
    assert equity_ratio_from(pd.DataFrame()) is None


def test_save_and_load(tmp_path):
    p = tmp_path / "f.csv"
    save_fundamentals(p, "2026-11-07", {"7203": {"per": 9.5, "pbr": None}})
    date, f = load_fundamentals(p)
    assert date == "2026-11-07" and f["7203"]["per"] == 9.5 and f["7203"]["pbr"] is None
    assert load_fundamentals(tmp_path / "none.csv") == (None, {})
