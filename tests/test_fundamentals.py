import pandas as pd
from kabu.fundamentals import parse_fundamentals, equity_ratio_from, save_fundamentals, load_fundamentals


def test_parse_fundamentals():
    info = {"trailingPE": 12.345, "forwardPE": 11.0, "priceToBook": 1.234, "returnOnEquity": 0.105,
            "trailingAnnualDividendYield": 0.0312, "marketCap": 4.5e12, "operatingMargins": 0.11,
            "revenueGrowth": -0.02}
    f = parse_fundamentals(info, 41.26)
    assert f == {"per": 12.35, "fper": 11.0, "pbr": 1.23, "roe": 10.5, "div_yield": 3.12,
                 "mcap_oku": 45000, "op_margin": 11.0, "rev_growth": -2.0, "equity_ratio": 41.3,
                 "div_streak": None}


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


from kabu.fundamentals import div_growth_years


def _divs(pairs):
    """[(年度, 中間, 期末)] → 9月中間・翌3月期末の配当系列"""
    idx, val = [], []
    for fy, mid, end in pairs:
        idx += [f"{fy}-09-29", f"{fy + 1}-03-30"]
        val += [mid, end]
    return pd.Series(val, index=pd.to_datetime(idx))


def test_div_growth_years():
    # 年度合計 60, 62.5, 67.5, 70, 72.5, 80 → 5年連続増配（KDDI型）
    s = _divs([(2020, 30, 30), (2021, 30, 32.5), (2022, 32.5, 35), (2023, 35, 35), (2024, 35, 37.5), (2025, 40, 40)])
    assert div_growth_years(s, current_fy=2026) == 5
    # 途中で据え置き → 据え置き以降のみ数える
    s2 = _divs([(2021, 10, 10), (2022, 11, 11), (2023, 11, 11), (2024, 12, 12)])
    assert div_growth_years(s2, current_fy=2025) == 1
    # 進行中の年度（2026年度）は数えない
    s3 = _divs([(2024, 10, 10), (2025, 9, 9)]).copy()
    s3[pd.Timestamp("2026-09-29")] = 50
    assert div_growth_years(s3, current_fy=2026) == 0


def test_div_growth_years_empty():
    assert div_growth_years(None, current_fy=2026) is None
    assert div_growth_years(pd.Series(dtype=float), current_fy=2026) == 0
