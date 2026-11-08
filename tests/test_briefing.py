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


from kabu.briefing import detect_cross, cross_lists, rank_value


def test_detect_golden_cross():
    c = [100.0] * 30 + [90.0] * 5 + [130.0, 140.0]   # 短期線が長期線を上抜け
    assert detect_cross(c, 5, 25) == "GC"


def test_detect_dead_cross():
    c = [100.0] * 30 + [110.0] * 5 + [70.0, 60.0]
    assert detect_cross(c, 5, 25) == "DC"


def test_no_cross_or_too_short():
    assert detect_cross([100.0 + i for i in range(40)], 5, 25) is None
    assert detect_cross([100.0] * 20, 5, 25) is None


def test_indicators_include_crosses():
    ind = indicators(df([100.0] * 30 + [90.0] * 5 + [130.0, 140.0]))
    assert ind["cross5_25"] == "GC" and ind["cross25_75"] is None


def test_cross_lists():
    ind = {"A": {"cross5_25": "GC", "cross25_75": None}, "B": {"cross5_25": None, "cross25_75": "DC"},
           "C": {"cross5_25": "GC", "cross25_75": "GC"}, "D": None}
    g = cross_lists(ind)
    assert g["ゴールデンクロス"] == [("A", "5日/25日"), ("C", "5日/25日・25日/75日")]
    assert g["デッドクロス"] == [("B", "25日/75日")]


def test_rank_value():
    f = {"A": {"per": 10.0, "pbr": 0.8, "roe": 9.0}, "B": {"per": 8.0, "pbr": 1.5, "roe": 12.0},
         "C": {"per": 7.0, "pbr": 1.0, "roe": 10.0}, "D": {"per": 5.0, "pbr": 0.5, "roe": 3.0},
         "E": {"per": None, "pbr": 0.7, "roe": 9.0}}
    assert [c for c, _ in rank_value(f)] == ["C", "A"]


def test_render_with_fundamentals_and_crosses():
    x = {"chg1d": 5, "chg5d": 1, "vol_ratio": 1, "ma25_dev": 2, "rsi14": 50, "close": 1}
    md = render_briefing("2026-11-10", [], [], {"上昇率": [("7203", x)]}, {"7203": "トヨタ"}, notes=[],
                         fund={"7203": {"per": 9.5, "pbr": 0.9, "roe": 10.2, "equity_ratio": 38.0,
                                        "div_yield": 3.1}},
                         fund_date="2026-11-07",
                         crosses={"ゴールデンクロス": [("7203", "5日/25日")], "デッドクロス": []},
                         value=[("7203", {"per": 9.5, "pbr": 0.9, "roe": 10.2, "equity_ratio": 38.0,
                                          "div_yield": 3.1})])
    assert "9.5倍" in md and "0.90倍" in md
    assert "### ゴールデンクロス" in md and "5日/25日" in md
    assert "### 割安・好財務" in md and "38.0%" in md and "2026-11-07" in md


from kabu.briefing import sector_medians, rank_peer_value


def test_sector_medians_and_peer_rank():
    sectors = {"A": "自動車", "B": "自動車", "C": "自動車", "D": "銀行"}
    fund = {"A": {"per": 8.0, "pbr": 0.8, "roe": 12.0}, "B": {"per": 12.0, "pbr": 1.2, "roe": 10.0},
            "C": {"per": 16.0, "pbr": 1.6, "roe": 8.0}, "D": {"per": 10.0, "pbr": 0.5, "roe": 7.0}}
    med = sector_medians(fund, sectors)
    assert med["自動車"] == {"per": 12.0, "pbr": 1.2, "roe": 10.0, "n": 3}
    r = rank_peer_value(fund, sectors, med)
    assert [c for c, _ in r] == ["A"]          # 同業比で PER・PBR が低く ROE が中央値以上
    assert round(r[0][1]["per_vs_peer"], 1) == -33.3
