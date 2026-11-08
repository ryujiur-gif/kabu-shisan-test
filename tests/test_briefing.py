import pandas as pd
from kabu.briefing import pct_change, indicators, rank_candidates, holding_view, render_briefing


def df(closes, vols=None):
    vols = vols or [1000] * len(closes)
    idx = pd.date_range("2026-08-01", periods=len(closes), freq="B")
    return pd.DataFrame({"Close": closes, "Volume": vols}, index=idx)


def test_pct_change():
    assert pct_change(100, 110) == 10.0
    assert pct_change(0, 110) is None
    assert pct_change(None, 1) is None


def test_indicators_basic():
    closes = [100.0] * 29 + [110.0]
    vols = [1000] * 29 + [3000]
    ind = indicators(df(closes, vols))
    assert ind["close"] == 110.0
    assert ind["chg1d"] == 10.0
    assert ind["vol_ratio"] == 3.0
    assert round(ind["ma25_dev"], 1) == round((110 / ((100 * 24 + 110) / 25) - 1) * 100, 1)
    assert ind["rsi14"] == 100.0


def test_indicators_short_or_nan_is_none():
    assert indicators(df([100.0] * 10)) is None
    d = df([100.0] * 29 + [float("nan")])
    assert indicators(d)["close"] == 100.0   # NaN rows are dropped


def test_rank_candidates():
    ind = {"A": {"chg1d": 5, "chg5d": 1, "vol_ratio": 1.0, "ma25_dev": 2, "rsi14": 50, "close": 1},
           "B": {"chg1d": -4, "chg5d": -9, "vol_ratio": 4.0, "ma25_dev": -12, "rsi14": 20, "close": 1},
           "C": {"chg1d": 1, "chg5d": 8, "vol_ratio": 2.0, "ma25_dev": 9, "rsi14": 75, "close": 1}}
    r = rank_candidates(ind, n=2)
    assert [c for c, _ in r["上昇率"]] == ["A", "C"]
    assert [c for c, _ in r["下落率"]] == ["B", "C"]
    assert [c for c, _ in r["出来高急増"]] == ["B", "C"]
    assert [c for c, _ in r["25日線から下方乖離"]] == ["B", "A"]


def test_holding_view():
    h = {"name": "トヨタ", "shares": 100, "avg_cost": 2000.0}
    v = holding_view("7203", h, {"close": 2200.0, "chg1d": 1.0, "chg5d": -2.0, "rsi14": 60, "ma25_dev": 3},
                     bought="2026-11-09")
    assert v["pl_pct"] == 10.0 and v["pl_yen"] == 20000 and v["bought"] == "2026-11-09"


def test_render_contains_sections():
    md = render_briefing("2026-11-10",
                         [{"label": "ダウ", "close": 51000.0, "chg": -0.5, "date": "2026-11-07"}],
                         [{"code": "7203", "name": "トヨタ", "shares": 100, "avg_cost": 2000.0, "close": 2200.0,
                           "pl_pct": 10.0, "pl_yen": 20000, "chg1d": 1.0, "chg5d": -2.0, "rsi14": 60,
                           "ma25_dev": 3, "bought": "2026-11-09"}],
                         {"上昇率": [("7203", {"chg1d": 5, "chg5d": 1, "vol_ratio": 1, "ma25_dev": 2, "rsi14": 50,
                                               "close": 1})]},
                         {"7203": "トヨタ"}, notes=[])
    assert "## 1. 主要指標" in md and "ダウ" in md and "-0.50%" in md
    assert "## 2. 持ち株の点検" in md and "+10.00%" in md
    assert "## 3. 日経225 値動きスクリーニング" in md and "トヨタ" in md
