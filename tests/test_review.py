from kabu import review as R


def bars(start_day, closes, opens=None, month="2026-11"):
    """営業日を気にせず連番の日付で足を作る（テスト用）。"""
    out = []
    for i, c in enumerate(closes):
        out.append({"d": f"{month}-{start_day + i:02d}", "o": (opens or closes)[i], "c": c, "v": 1000.0})
    return out


def history(n, last):
    """26本以上の過去の足（指標計算用）。最後が last になる右肩上がり。"""
    return [{"d": f"2026-09-{i + 1:02d}" if i < 30 else f"2026-10-{i - 29:02d}", "o": last - (n - i), "c": last - (n - i - 1), "v": 1000.0}
            for i in range(n)]


def trade(d, side, code, price, shares=10, name="X"):
    return {"date": d, "side": side, "code": code, "name": name, "shares": shares, "price": price,
            "amount": int(price * shares), "status": "約定", "reason": "上方修正と自社株買い"}


def test_forward_counts_entry_day_as_day1():
    b = bars(2, [110, 120, 130])
    f = R.forward(b, "2026-11-02", 100.0)
    assert f["ret"][1] == 10.0 and f["ret"][3] == 30.0 and 5 not in f["ret"]
    assert f["days"] == 3 and f["latest"] == 30.0


def test_buy_is_pending_until_5_days_then_judged_against_nikkei():
    s = {"7203": bars(2, [101, 102, 103, 104]), "N225": bars(2, [100, 100, 100, 100])}
    buys, _ = R.build_buys([trade("2026-11-02", "買", "7203", 100.0)], s)
    assert buys[0]["verdict"] == "評価中" and buys[0]["latest"] == 4.0
    s = {"7203": bars(2, [101, 102, 103, 104, 110]), "N225": bars(2, [100, 100, 100, 100, 102], opens=[100] * 5)}
    buys, _ = R.build_buys([trade("2026-11-02", "買", "7203", 100.0)], s)
    assert buys[0]["r5"] == 10.0 and buys[0]["x5"] == 8.0 and buys[0]["verdict"] == "成功"


def test_up_but_behind_nikkei_is_not_success():
    s = {"7203": bars(2, [101] * 5), "N225": bars(2, [100, 101, 102, 103, 105], opens=[100] * 5)}
    buys, _ = R.build_buys([trade("2026-11-02", "買", "7203", 100.0)], s)
    assert buys[0]["verdict"] == "上昇したが日経平均に届かず"


def test_sell_closes_lot_with_realized_result():
    s = {"7203": bars(2, [101, 95, 94, 93, 92, 91, 90], opens=[100, 96, 95, 94, 93, 92, 91]),
         "N225": bars(2, [100] * 7)}
    t = [trade("2026-11-02", "買", "7203", 100.0), trade("2026-11-03", "売", "7203", 96.0)]
    buys, sells = R.build_buys(t, s)
    assert buys[0]["sell_date"] == "2026-11-03" and buys[0]["realized"] == -4.0
    assert buys[0]["basis"] == "売却" and buys[0]["verdict"] == "失敗"
    assert sells[0]["realized_yen"] == -40 and sells[0]["judge"] == "売って正解・妥当"


def test_early_sell_is_flagged():
    s = {"7203": bars(2, [101, 100, 104, 106, 108, 110], opens=[100] * 6), "N225": bars(2, [100] * 6)}
    t = [trade("2026-11-02", "買", "7203", 100.0), trade("2026-11-03", "売", "7203", 100.0)]
    _, sells = R.build_buys(t, s)
    assert sells[0]["after5"] == 10.0 and sells[0]["judge"].startswith("早売り")


def test_entry_features_use_only_bars_before_entry():
    past = history(40, 100.0)
    f = R.entry_features(past + bars(2, [200.0]), "2026-11-02", 103.0)
    assert f["gap_open"] == 3.0          # 前日終値100 → 始値103
    assert f["rsi14"] == 100.0           # 前日までは上がり続けていた（当日の200は見ていない）


def test_outlook_hit_rules():
    s = {"7203": [{"d": "2026-10-30", "o": 100, "c": 100.0, "v": 1}] + bars(2, [100, 100, 100, 100, 102])}
    orders = {"2026-11-02": {"holds": [{"code": "7203", "name": "X", "outlook": "上昇"},
                                       {"code": "7203", "name": "X", "outlook": "下落"},
                                       {"code": "7203", "name": "X", "outlook": "横ばい"}]}}
    o = R.build_outlooks(orders, s)
    assert [x["hit"] for x in o] == [True, False, True]
    assert R.outlook_stats(o)["全体"] == {"n": 3, "hit": 67, "avg_r5": 2.0}


def _done(ret, x, **kw):
    return {"ret": ret, "x": x, "confidence": "低", "tags": [], **kw}


def test_patterns_need_min_samples_and_edge():
    weak = [_done(-3.0, -4.0, chg1d=7.0) for _ in range(5)]
    few = [_done(-3.0, -4.0, rsi14=80.0) for _ in range(2)]
    flat = [_done(0.2, 0.1, chg1d=1.0) for _ in range(6)]
    pats = R.find_patterns(R.group_stats(weak + few + flat))
    by = {p["bucket"]: p for p in pats}
    assert by["前日+5%以上の急騰後"]["level"] == "傾向" and by["前日+5%以上の急騰後"]["kind"] == "弱み"
    assert "押し" in by["前日+5%以上の急騰後"]["advice"]
    assert by["RSI70以上"]["level"] == "仮説"
    assert "前日プラス（+5%未満）" not in by            # 差が小さいものは載せない
    assert "期待度 低" not in by                         # 全部の事例に共通する条件は載せない
    assert pats[0]["level"] == "傾向"                    # 傾向が先


def test_all_losers_do_not_make_every_condition_a_weakness():
    # 全部負けているとき、共通の条件はどれも「弱み」にしない（相場全体の結果と区別できない）
    assert R.find_patterns(R.group_stats([_done(-3.0, -4.0, chg1d=7.0) for _ in range(6)])) == []


def test_matching_patterns_for_todays_candidate():
    pats = R.find_patterns(R.group_stats([_done(-3.0, -4.0, chg1d=7.0) for _ in range(5)]
                                         + [_done(0.2, 0.1, chg1d=1.0) for _ in range(6)]))
    assert [p["bucket"] for p in R.matching_patterns({"chg1d": 8.0, "confidence": "中", "tags": []}, pats)] \
        == ["前日+5%以上の急騰後"]
    assert R.matching_patterns({"chg1d": 1.0, "confidence": "中", "tags": []}, pats) == []


def test_cases_due_until_written_in_journal():
    s = {"7203": bars(2, [101, 102, 103, 104, 110]), "N225": bars(2, [100] * 5)}
    buys, sells = R.build_buys([trade("2026-11-02", "買", "7203", 100.0)], s)
    due = R.cases_due(buys, sells, "")
    assert [c["key"] for c in due] == ["## 2026-11-02 買 7203"]
    assert R.cases_due(buys, sells, "# x\n\n## 2026-11-02 買 7203 トヨタ（5日後…）\n- 教訓：…\n") == []


def test_attribution_splits_cash_drag_and_selection():
    # 現金100%のまま日経平均が+10% → 差 -10ポイントはすべて現金の分
    hist = [{"date": "2026-11-09", "total": "1000000", "cash": "1000000", "benchmark_value": "1100000"}]
    a = R.attribution(hist)
    assert a["diff"] == -10.0 and a["cash_part"] == -10.0 and a["selection_part"] == 0.0
    assert a["days_cash_over"] == 1
    assert any("現金の持ちすぎ" in l for l in R.portfolio_lines({**a, "days": 3, "days_cash_over": 3}))


def test_render_and_briefing_lines_smoke():
    s = {"7203": bars(2, [101, 102, 103, 104, 110]), "N225": bars(2, [100] * 5)}
    rv = R.build_review("2026-11-09", [trade("2026-11-02", "買", "7203", 100.0)],
                        {"2026-11-02": {"buys": [{"code": "7203", "confidence": "高"}], "holds": []}}, s,
                        hist=[{"date": "2026-11-06", "total": "1010000", "cash": "900000", "benchmark_value": "1000000"}])
    assert rv["overall"]["n"] == 1 and rv["buys"][0]["confidence"] == "高"
    md = R.render_lessons(rv)
    assert "## 5. 傾向と対策" in md and "## 2026-11-02 買 7203" in md
    lines = "\n".join(R.briefing_lines(rv, "1. ルール"))
    assert "今朝、振り返りを書く事例" in lines and "1. ルール" in lines
    assert any("評価済み1件" in l for l in R.email_lines(rv))
