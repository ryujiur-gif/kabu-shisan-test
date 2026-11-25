"""研究（kabu.research）と、2026-11-25 の修正の確認。"""
import json

from kabu import research
from kabu.briefing import fix_nikkei, missing_market


def series(closes, start="2026-01-01"):
    from datetime import date, timedelta
    d0 = date.fromisoformat(start)
    ds = [(d0 + timedelta(days=i)).isoformat() for i in range(len(closes))]
    return {"d": ds, "o": list(closes), "c": list(closes), "v": [1000.0] * len(closes)}


def test_nikkei_note_only_when_still_missing():
    m = [{"label": "日経平均", "ticker": "^N225", "close": None, "chg": None, "date": "-"},
         {"label": "金", "ticker": "GC=F", "close": None, "chg": None, "date": "-"}]
    fixed = fix_nikkei(m, "2026-11-20", [{"d": "2026-11-19", "c": 59444.21}, {"d": "2026-11-20", "c": 56436.65}])
    assert fixed[0]["close"] == 56436.65 and fixed[0]["date"] == "2026-11-20"
    assert missing_market(fixed) == ["金（GC=F）"]          # 補えた日経平均は「取得できず」にしない
    assert missing_market(m) == ["日経平均（^N225）", "金（GC=F）"]


def test_stats_t_value_uses_days_not_rows():
    # 同じ日に100件そろって +1% の日が1日だけ → 件数は多くても日数は1日なので t は出ない
    rows = [{"date": "2026-01-05", "rel": 1.0, "ret": 1.0} for _ in range(100)]
    s = research.stats(rows)
    assert s["n"] == 100 and s["days"] == 1 and s["t"] == 0.0
    assert research.verdict(s, None) == "件数不足"


def test_stats_and_verdict_significant():
    rows = []
    for i in range(60):
        for k in range(5):
            rows.append({"date": f"d{i}", "rel": 1.0 + (0.5 if (i + k) % 2 else -0.5), "ret": 1.0})
    s = research.stats(rows)
    assert s["days"] == 60 and s["mean"] == 1.0 and s["t"] > 3
    assert research.verdict(s, None) == "有利"


def test_events_relative_to_same_day():
    up = series([100.0 + i for i in range(100)])
    flat = series([100.0] * 100)
    nk = series([1000.0] * 100)
    rows = research.events({"A": up, "B": flat}, nk, hold=5)
    day = rows[0]["date"]
    a = next(r for r in rows if r["code"] == "A" and r["date"] == day)
    b = next(r for r in rows if r["code"] == "B" and r["date"] == day)
    assert abs(a["rel"] + b["rel"]) < 1e-9 and a["rel"] > 0      # 同じ日の平均との差なので足すと0
    assert b["x"] == 0.0                                          # 日経平均が横ばいなら、日経平均との差＝騰落


def test_regime_study_avoids_fall():
    closes = [100.0] * 90 + [100.0 + i for i in range(1, 41)] + [140.0 - 2 * i for i in range(1, 41)]
    nk = series(closes)
    res = {r["name"]: r for r in research.regime_study(nk)}
    hold, filt = res["いつも持つ（買い持ち）"], res["25日線より上のときだけ持つ"]
    assert filt["mdd"] > hold["mdd"] and filt["held"] < 100     # 下げの途中で降りるので最大下落幅が小さい


def test_day_table_and_day_verdict():
    rows = [{"date": f"d{i}", "ret": (2.0 + (0.5 if i % 2 else -0.5)) if i < 40 else -1.0, "x": 0.0, "gap": 2.0 if i < 40 else 0.0, "prev": 0.0,
             "n_ma25": 1.0, "n_r5": 0.0, "ma25": 1.0} for i in range(80)]
    days = research.day_table(rows)
    base = research.day_stats(days)
    s = research.day_stats([d for d in days if d["gap"] >= 1.5], base)
    assert s["n"] == 40 and s["ret"] == 2.0 and research.day_verdict(s) == "有利（買ってよい日）"


def test_cash_core_study(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "history.csv").write_text(
        "date,total,cash,stock_value,nikkei_close,benchmark_value\n"
        "2026-04-10,1000000,500000,500000,0,1000000\n2026-04-11,1000000,500000,500000,0,1100000\n", encoding="utf-8")
    nk = series([100.0] * 100 + [110.0], start="2026-01-01")  # 04-10（100）→ 04-11（110）で日経平均 +10%
    res = research.cash_core_study(tmp_path, nk)
    assert res["actual"] == 0.0 and res["core"] == 5.0 and res["bench"] == 10.0
    assert res["core_filtered"] == 0.0                         # 横ばいだと25日線より上ではないので持たない
