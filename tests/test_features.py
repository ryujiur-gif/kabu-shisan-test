"""2026-11-13 追加分：配当・分割、一部売却、寄り付き高の見送り、税引き後、決算日、業種の上限、
成績の集計、見張り、週末のまとめ。"""
import json
from datetime import date

from kabu import corporate, earnings, stats, watchdog, weekly
from kabu.ledger import after_tax, new_state, replay, sell_shares, settle
from kabu.picks import check_entry_rules, validate_order
from kabu.report import build_email, build_site
from kabu.settle import run as settle_run

MON, TUE, WED, SAT = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 14)


def held(code="7203", shares=100, cost=1000.0, cash=500_000):
    st = new_state("2026-11-09")
    st["cash"] = cash
    st["holdings"] = {code: {"name": "N" + code, "shares": shares, "avg_cost": cost}}
    return st


def buy(code, conf="低", **kw):
    return {"code": code, "name": "N" + code, "confidence": conf, "reason": "r", **kw}


# ---- 一部売却 ----

def test_sell_shares():
    assert sell_shares(100, None) == 100 and sell_shares(100, "全部") == 100
    assert sell_shares(100, "半分") == 50 and sell_shares(11, "半分") == 5 and sell_shares(1, "半分") == 1


def test_partial_sell_keeps_rest():
    st, tr = settle(held(), {"date": "2026-11-10", "buys": [],
                             "sells": [{"code": "7203", "name": "N", "reason": "r", "portion": "半分"}]},
                    {"7203": 1200.0})
    assert st["holdings"]["7203"] == {"name": "N7203", "shares": 50, "avg_cost": 1000.0}
    assert st["cash"] == 500_000 + 60_000 and tr[0]["shares"] == 50 and tr[0]["status"] == "約定"


def test_replay_handles_partial_sell_dividend_and_split():
    trades = [
        {"date": "2026-11-09", "side": "買", "code": "A", "name": "a", "shares": "100", "price": "1000", "amount": "100000", "status": "約定"},
        {"date": "2026-11-10", "side": "売", "code": "A", "name": "a", "shares": "40", "price": "1100", "amount": "44000", "status": "約定"},
        {"date": "2026-11-11", "side": "配当", "code": "A", "name": "a", "shares": "60", "price": "50", "amount": "3000", "status": "入金"},
        {"date": "2026-11-12", "side": "分割", "code": "A", "name": "a", "shares": "120", "price": "2.0", "amount": "0", "status": "調整"},
        {"date": "2026-11-12", "side": "買", "code": "B", "name": "b", "shares": "1", "price": "500", "amount": "500", "status": "見送り"},
    ]
    r = replay(trades)
    assert r["cash"] == 1_000_000 - 100_000 + 44_000 + 3_000
    assert r["holdings"]["A"]["shares"] == 120 and r["holdings"]["A"]["avg_cost"] == 500.0
    assert "B" not in r["holdings"]


def test_second_buy_uses_total_assets_not_share_count():
    """買い増しの直後の買いで、購入額の基準（総資産）が株数に化けない。"""
    st = held("7203", 100, 1000.0, cash=900_000)   # 総資産100万円
    st, tr = settle(st, {"date": "2026-11-10", "sells": [], "buys": [buy("7203"), buy("6758")]},
                    {"7203": 1000.0, "6758": 1000.0})
    assert [t["shares"] for t in tr] == [50, 50]


# ---- 寄り付きが高すぎる買いの見送り ----

def test_buy_skipped_when_open_gaps_up():
    order = {"date": "2026-11-10", "sells": [], "buys": [buy("7203"), buy("6758")]}
    st, tr = settle(new_state("x"), order, {"7203": 1060.0, "6758": 1040.0}, {"7203": 1000.0, "6758": 1000.0})
    assert tr[0]["status"] == "見送り" and tr[0]["reason"].startswith("始値が前日終値より+6.0%高く")
    assert tr[1]["status"] == "約定" and "7203" not in st["holdings"]


def test_gap_limit_can_be_raised_per_order_and_ignored_without_ref():
    order = {"date": "2026-11-10", "sells": [], "buys": [buy("7203", max_open_gap=10)]}
    assert settle(new_state("x"), order, {"7203": 1060.0}, {"7203": 1000.0})[1][0]["status"] == "約定"
    order = {"date": "2026-11-10", "sells": [], "buys": [buy("7203")]}
    assert settle(new_state("x"), order, {"7203": 1060.0})[1][0]["status"] == "約定"


# ---- 配当・分割 ----

def test_corporate_apply_dividend_and_split():
    st = held("A", 100, 1000.0, cash=0)
    st["last_closes"] = {"A": 1200.0}
    trades = [{"date": "2026-11-09", "side": "買", "code": "A", "name": "NA", "shares": 100, "price": 1000.0,
               "amount": 100000, "status": "約定"}]
    rows = corporate.apply(st, trades, "2026-11-11", [("A", "配当", 50.0), ("A", "分割", 2.0)])
    assert st["cash"] == 5000 and rows[0]["side"] == "配当" and rows[0]["amount"] == 5000
    assert st["holdings"]["A"]["shares"] == 200 and st["holdings"]["A"]["avg_cost"] == 500.0
    assert st["last_closes"]["A"] == 600.0 and rows[1]["shares"] == 200
    r = replay(trades + rows)   # 記録からたどり直しても同じ
    assert r["cash"] == 1_000_000 - 100_000 + 5000 and r["holdings"]["A"]["shares"] == 200


def test_dividend_only_for_shares_held_before_ex_date():
    st = held("A", 150, 1000.0, cash=0)
    trades = [{"date": "2026-11-09", "side": "買", "code": "A", "name": "NA", "shares": 100, "price": 1000.0, "amount": 100000, "status": "約定"},
              {"date": "2026-11-11", "side": "買", "code": "A", "name": "NA", "shares": 50, "price": 1000.0, "amount": 50000, "status": "約定"}]
    rows = corporate.apply(st, trades, "2026-11-11", [("A", "配当", 10.0)])
    assert rows[0]["shares"] == 100 and st["cash"] == 1000   # 権利落ち日に買った50株には付かない


def test_collect_reports_failures():
    def f(code, s, e):
        if code == "B":
            raise RuntimeError("x")
        return [{"date": "2026-11-11", "type": "配当", "value": 5.0}]
    by, failed = corporate.collect(["A", "B"], MON, WED, fetch=f)
    assert by == {"2026-11-11": [("A", "配当", 5.0)]} and failed == ["B"]


def _setup(tmp_path, state, orders=()):
    (tmp_path / "orders").mkdir()
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")
    for o in orders:
        (tmp_path / "orders" / f"{o['date']}.json").write_text(json.dumps(o), encoding="utf-8")


def test_settle_applies_split_before_selling(tmp_path):
    st = held("7203", 100, 1000.0, cash=0)
    st["last_date"], st["last_closes"] = "2026-11-09", {"7203": 1000.0}
    _setup(tmp_path, st, [{"date": "2026-11-10", "summary": "s", "settled": False, "buys": [],
                           "sells": [{"code": "7203", "name": "N7203", "reason": "r"}]}])
    (tmp_path / "trades.csv").write_text(
        "date,side,code,name,shares,price,amount,status,reason\n2026-11-09,買,7203,N7203,100,1000.0,100000,約定,r\n",
        encoding="utf-8")
    acts = lambda code, s, e: [{"date": "2026-11-10", "type": "分割", "value": 2.0}]
    res = settle_run(WED, tmp_path, fetch=lambda t, d: {"open": 500.0, "close": 510.0}, actions_fetch=acts)
    assert res["status"] == "ok" and "株式分割" in res["message"]
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["cash"] == 100_000 and state["holdings"] == {} and state["actions_through"] == "2026-11-10"


def test_settle_dividend_and_actions_failure(tmp_path):
    st = held("7203", 100, 1000.0, cash=0)
    st["last_date"], st["last_closes"] = "2026-11-09", {"7203": 1000.0}
    _setup(tmp_path, st)
    (tmp_path / "trades.csv").write_text(
        "date,side,code,name,shares,price,amount,status,reason\n2026-11-09,買,7203,N7203,100,1000.0,100000,約定,r\n",
        encoding="utf-8")
    px = lambda t, d: {"open": 1000.0, "close": 1010.0}

    def boom(code, s, e):
        raise RuntimeError("x")
    res = settle_run(WED, tmp_path, fetch=px, actions_fetch=boom)
    assert res["status"] == "ok" and "配当・分割の確認ができませんでした" in res["message"]
    assert "actions_through" not in json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    # 次の回に取り直して入金される
    res = settle_run(WED, tmp_path, fetch=px,
                     actions_fetch=lambda c, s, e: [{"date": "2026-11-10", "type": "配当", "value": 30.0}])
    state = json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))
    assert state["cash"] == 3000 and state["actions_through"] == "2026-11-10" and "3,000円を入金" in res["message"]


def test_settle_even_if_holiday(tmp_path):
    st = held("7203", 100, 1000.0, cash=0)
    st["last_date"] = "2026-11-12"
    _setup(tmp_path, st)
    px = lambda t, d: {"open": 1000.0, "close": 1100.0}
    assert settle_run(SAT, tmp_path, fetch=px)["status"] == "holiday"
    res = settle_run(SAT, tmp_path, fetch=px, even_if_holiday=True)
    assert res["status"] == "ok" and res["total"] == 110_000
    hist = (tmp_path / "history.csv").read_text(encoding="utf-8")
    assert "2026-11-13,110000" in hist


def test_settle_skips_high_open_using_saved_indicators(tmp_path):
    _setup(tmp_path, new_state("2026-11-09"),
           [{"date": "2026-11-10", "summary": "s", "settled": False, "sells": [], "buys": [buy("7203")]}])
    d = tmp_path / "daily" / "2026-11-10"
    d.mkdir(parents=True)
    (d / "indicators.json").write_text(json.dumps({"7203": {"close": 1000.0}}), encoding="utf-8")
    res = settle_run(WED, tmp_path, fetch=lambda t, dd: {"open": 1070.0, "close": 1080.0})
    assert res["status"] == "ok" and "見送り" in res["message"] and res["holdings"] == []


# ---- 手数料・税引き後 ----

def test_after_tax():
    trades = [{"side": "買", "status": "約定", "amount": "100000"}, {"side": "売", "status": "約定", "amount": "120000"},
              {"side": "配当", "status": "入金", "amount": "500"}]
    a = after_tax(1_100_000, trades)
    assert a == {"fees": 0, "tax": 20315, "net": 1_079_685, "turnover": 220_000}
    a = after_tax(1_100_000, trades, fee_rate=0.001)
    assert a["fees"] == 220 and a["tax"] == int((100_000 - 220) * 0.20315)
    assert after_tax(950_000, trades)["tax"] == 0   # 損失のときは税なし


# ---- 決算日 ----

def test_parse_calendar_and_near():
    cal = {"Earnings Date": [date(2026, 11, 6), date(2026, 11, 19)], "Ex-Dividend Date": date(2027, 3, 30)}
    v = earnings.parse_calendar(cal, date(2026, 11, 13))
    assert v == {"earnings": "2026-11-19", "exdiv": "2027-03-30", "asof": "2026-11-13"}
    data = {"8725": v}
    assert earnings.near(data, "8725", date(2026, 11, 17)) == "2026-11-19"      # 2営業日前
    assert earnings.near(data, "8725", date(2026, 11, 16)) is None             # 3営業日前
    assert earnings.near(data, "8725", date(2026, 11, 19)) == "2026-11-19"      # 当日
    assert earnings.near(data, "8725", date(2026, 11, 20)) is None and earnings.near(data, "0000", MON) is None
    assert earnings.parse_calendar(None, MON)["earnings"] == ""


def test_trading_days_until_skips_weekend_and_holiday():
    assert earnings.trading_days_until(date(2026, 11, 20), date(2026, 11, 24)) == 1   # 土日と11/23(祝)を飛ばす


def test_earnings_refresh_keeps_old_on_failure(tmp_path):
    p = tmp_path / "earnings.csv"
    earnings.save(p, {"A": {"earnings": "2026-12-01", "exdiv": "", "asof": "2026-11-01"}})

    def f(code, today):
        if code == "A":
            raise RuntimeError("x")
        return {"earnings": "2026-11-20", "exdiv": "", "asof": today.isoformat()}
    assert earnings.refresh(p, ["A", "B"], MON, fetch=f) == ["A"]
    d = earnings.load(p)
    assert d["A"]["earnings"] == "2026-12-01" and d["B"]["earnings"] == "2026-11-20"


def test_entry_rule_blocks_buy_before_earnings_unless_low():
    cal = {"7203": {"earnings": "2026-11-11"}}
    o = {"buys": [buy("7203", "中")]}
    assert any("決算発表" in e for e in check_entry_rules(o, None, None, earnings=cal, today="2026-11-10"))
    assert check_entry_rules({"buys": [buy("7203", "低")]}, None, None, earnings=cal, today="2026-11-10") == []


def test_earnings_briefing_lines():
    cal = {"8725": {"earnings": "2026-11-19", "exdiv": "2027-03-30"}, "7203": {"earnings": "2026-11-18", "exdiv": ""}}
    text = "\n".join(earnings.briefing_lines(cal, date(2026, 11, 17), {"8725": "MS&AD"}, {"7203": "トヨタ"}))
    assert "持ち株 MS&AD(8725)：決算発表 2026-11-19／権利落ち日 2027-03-30" in text and "決算またぎに注意" in text
    assert "トヨタ(7203) 11-18" in text


# ---- 業種の上限・一部売却の検証 ----

U = {"1801": "大成", "1803": "清水", "7203": "トヨタ"}
SEC = {"1801": "建設", "1803": "建設", "7203": "自動車"}


def order_of(buys=(), sells=(), holds=()):
    return {"date": "2026-11-10", "summary": "s", "buys": list(buys), "sells": list(sells),
            "holds": [{"code": c, "name": c, "outlook": "横ばい", "reason": "r"} for c in holds]}


def test_sector_cap():
    st = new_state("x")
    st["cash"] = 750_000
    st["holdings"] = {"1803": {"name": "清水", "shares": 250, "avg_cost": 1000.0}}   # 建設 25%
    errs = validate_order(order_of([buy("1801", "中")], holds=["1803"]), st, U, sectors=SEC)
    assert any("業種「建設」" in e and "35%" in e for e in errs)
    assert validate_order(order_of([buy("7203", "中")], holds=["1803"]), st, U, sectors=SEC) == []
    assert validate_order(order_of([buy("1801", "低")], holds=["1803"]), st, U, sectors=SEC) == []   # ちょうど30%は可


def test_portion_validation_and_hold_required_for_partial():
    st = held("7203", 10, 1000.0)
    s = {"code": "7203", "name": "N", "reason": "r", "portion": "半分"}
    errs = validate_order(order_of(sells=[s]), st, U)
    assert any("見通しが holds にありません" in e for e in errs)     # 残りは持つので見通しが要る
    assert validate_order(order_of(sells=[s], holds=["7203"]), st, U) == []
    assert any("portion" in e for e in validate_order(order_of(sells=[{**s, "portion": "3割"}], holds=["7203"]), st, U))
    one = held("7203", 1, 1000.0)
    assert any("1株しか無い" in e for e in validate_order(order_of(sells=[s], holds=["7203"]), one, U))


# ---- 成績の集計 ----

TR = [
    {"date": "2026-11-09", "side": "買", "code": "A", "name": "a", "shares": "100", "price": "1000", "amount": "100000", "status": "約定"},
    {"date": "2026-11-10", "side": "買", "code": "B", "name": "b", "shares": "10", "price": "2000", "amount": "20000", "status": "約定"},
    {"date": "2026-11-11", "side": "売", "code": "A", "name": "a", "shares": "50", "price": "1200", "amount": "60000", "status": "約定"},
    {"date": "2026-11-12", "side": "配当", "code": "A", "name": "a", "shares": "50", "price": "20", "amount": "1000", "status": "入金"},
    {"date": "2026-11-12", "side": "買", "code": "C", "name": "c", "shares": "0", "price": "0", "amount": "0", "status": "取消"},
]
HI = [{"date": "2026-10-30", "total": "1000000", "benchmark_value": "1000000"},
      {"date": "2026-11-09", "total": "1050000", "benchmark_value": "1020000"},
      {"date": "2026-11-10", "total": "1008000", "benchmark_value": "1040000"},
      {"date": "2026-11-11", "total": "1030000", "benchmark_value": "1030000"}]


def test_per_stock():
    ps = {x["code"]: x for x in stats.per_stock(TR, {"A": 1100.0, "B": 1900.0})}
    assert ps["A"]["realized"] == 10000 and ps["A"]["unrealized"] == 5000 and ps["A"]["dividend"] == 1000
    assert ps["A"]["pl"] == 16000 and ps["A"]["pl_pct"] == 16.0 and ps["A"]["holding"]
    assert ps["B"]["pl"] == -1000 and "C" not in ps
    assert [x["code"] for x in stats.per_stock(TR, {"A": 1100.0, "B": 1900.0})] == ["A", "B"]


def test_max_drawdown_monthly_and_period():
    assert stats.max_drawdown(HI) == {"pct": -4.0, "peak_date": "2026-11-09", "date": "2026-11-10"}
    m = stats.monthly(HI)
    assert [x["month"] for x in m] == ["2026-10", "2026-11"] and m[1]["mine"] == 3.0 and m[1]["bench"] == 3.0
    w = stats.period_change(HI, "2026-11-09")
    assert w["mine"] == 3.0 and w["bench"] == 3.0 and w["days"] == 3 and w["start_total"] == 1_000_000
    assert stats.period_change(HI, "2026-12-01") is None


def test_sector_weights_and_moves():
    w = stats.sector_weights({"1801": 100, "1803": 50, "7203": 100}, SEC, 1000)
    assert list(w) == ["建設", "自動車"] and abs(w["建設"] - 0.15) < 1e-9 and abs(w["自動車"] - 0.1) < 1e-9
    ind = {"1801": {"chg1d": 2.0, "chg5d": 4.0}, "1803": {"chg1d": -1.0, "chg5d": 0.0}, "7203": {"chg1d": 3.0, "chg5d": 1.0}, "x": None}
    mv = stats.sector_moves(ind, SEC, min_n=1)
    assert [m["sector"] for m in mv] == ["自動車", "建設"] and mv[1]["chg1d"] == 0.5 and mv[1]["up"] == 1
    assert "業種別の値動き" in "\n".join(stats.sector_lines(mv))


# ---- メール・成績ページ ----

def test_email_shows_partial_sell_after_tax_and_dividend():
    st = held("7203", 11, 1000.0)
    st["last_closes"] = {"7203": 1100.0}
    o = order_of(sells=[{"code": "7203", "name": "トヨタ", "reason": "利益確定", "portion": "半分"}], holds=["7203"])
    last = [{"date": "2026-11-09", "side": "配当", "code": "7203", "name": "トヨタ", "shares": "11", "price": "50", "amount": "550", "status": "入金", "reason": ""},
            {"date": "2026-11-09", "side": "買", "code": "6758", "name": "ソニー", "shares": "0", "price": "1060", "amount": "0", "status": "見送り",
             "reason": "始値が前日終値より+6.0%高く（基準+5%以上）見送り。元の理由：x"}]
    body = build_email(o, st, HI, last, "u", all_trades=TR)["body"]
    assert "トヨタ（7203）半分売却（11株のうち 5株）" in body
    assert "配当 トヨタ 11株 × 50円（+550円を入金）" in body
    assert "買 ソニー：見送り（始値が前日終値より+6.0%高く（基準+5%以上）見送り）" in body
    assert "手数料・税引き後の概算（いま全部売った場合）：1,023,906円（税 6,094円）" in body   # 利益3万円 × 20.315% = 6,094円（切り捨て）


def test_site_has_stats_section():
    st = held("A", 50, 1000.0)
    st["last_closes"] = {"A": 1100.0}
    html = build_site(st, HI, TR, None, sectors={"A": "建設"})
    assert "成績の内訳" in html and "最大下落幅" in html and "銘柄別の損益（2銘柄中 1銘柄がプラス）" in html
    assert "業種の比率：建設" in html and "<td>2026-11</td>" in html


# ---- 見張り ----

def test_watchdog(tmp_path):
    assert watchdog.check(tmp_path, SAT)[0]                       # 休場日
    ok, msg = watchdog.check(tmp_path, TUE)
    assert not ok and "まだ保存されていません" in msg
    d = tmp_path / "data" / "orders"
    d.mkdir(parents=True)
    (d / "2026-11-10.json").write_text("{", encoding="utf-8")
    assert not watchdog.check(tmp_path, TUE)[0]
    (d / "2026-11-10.json").write_text(json.dumps({"date": "2026-11-10", "summary": "s", "buys": [], "sells": []}),
                                       encoding="utf-8")
    assert watchdog.check(tmp_path, TUE)[0]


# ---- 週末のまとめ ----

def test_weekly_build(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    st = held("A", 50, 1000.0)
    st["last_closes"] = {"A": 1100.0}
    (data / "state.json").write_text(json.dumps(st), encoding="utf-8")
    (data / "history.csv").write_text("date,total,cash,stock_value,nikkei_close,benchmark_value\n" + "\n".join(
        f"{r['date']},{r['total']},0,0,0,{r['benchmark_value']}" for r in HI) + "\n", encoding="utf-8")
    (data / "trades.csv").write_text("date,side,code,name,shares,price,amount,status,reason\n" + "\n".join(
        f"{t['date']},{t['side']},{t['code']},{t['name']},{t['shares']},{t['price']},{t['amount']},{t['status']}," for t in TR) + "\n",
        encoding="utf-8")
    (data / "events.csv").write_text("date,end_date,event,importance,note,checked\n2026-11-16,,日本GDP速報,中,,2026-11-13\n",
                                     encoding="utf-8")
    (tmp_path / "config.json").write_text(json.dumps({"site_url": "https://example/"}), encoding="utf-8")
    out = weekly.build(tmp_path, SAT)
    assert out["made"] == "2026-11-14" and out["through"] == "2026-11-11"
    assert out["subject"] == "【株予想・週まとめ】11/9〜11/11 今週 +3.00%（日経平均 +3.00%）"
    b = out["body"]
    assert "予想どおり売買：+3.00%（1,000,000円 → 1,030,000円）" in b and "最大下落幅：-4.00%" in b
    assert "11-11 売 a 50株 @1,200.0円（60,000円）" in b and "11-12 配当 a 50株 × 20円" in b
    assert "・11/16 日本GDP速報（重要度：中）" in b and "https://example/" in b
