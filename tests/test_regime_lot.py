"""地合いの上限（日経平均が25日線より下なら株は30%まで・買いは期待度「高」のみ）と100株単位（2026-11-25）。"""
import json
from datetime import date

from kabu.briefing import trend25, trend_lines
from kabu.ledger import new_state, settle
from kabu.picks import check_lot_rules
from kabu.report import build_email
from kabu.settle import regime_cap, run as settle_run, trade_settings


def bars(closes):
    return [{"d": f"2026-10-{i + 1:02d}" if i < 31 else f"2026-11-{i - 30:02d}", "c": c} for i, c in enumerate(closes)]


def buy(code, conf="高"):
    return {"code": code, "name": "N" + code, "confidence": conf, "reason": "r"}


def test_trend25():
    up = bars([100.0 + i for i in range(30)])
    t = trend25(up, "2026-11-30")
    assert t["above"] is True and t["close"] == 129.0
    down = bars([130.0 - i for i in range(30)])
    assert trend25(down, "2026-11-30")["above"] is False
    assert trend25(bars([100.0] * 10), "2026-11-30") is None


def test_trend_lines_text():
    f = {"total": 1_000_000, "stock_value": 220_000}
    weak = "\n".join(trend_lines({"close": 58000, "ma25": 60000, "dev": -3.3, "above": False}, f, 100))
    assert "地合いが弱い：株の合計は総資産の30%まで、新しい買いは期待度「高」のみ" in weak
    assert "上限まであと **80,000円**" in weak and "高 株価2,000円まで／中 株価1,000円まで／低 株価500円まで" in weak
    strong = "\n".join(trend_lines({"close": 61000, "ma25": 60000, "dev": 1.7, "above": True}, f, 100))
    assert "地合いの上限なし" in strong


def test_settle_buys_in_lots_and_respects_cap():
    st = new_state("x")   # 現金100万円・株なし
    order = {"date": "2026-11-26", "sells": [], "buys": [buy("A"), buy("B")]}
    s2, tr = settle(st, order, {"A": 640.0, "B": 2500.0}, lot=100)
    assert tr[0]["shares"] == 300 and tr[0]["status"] == "約定"          # 20万円 ÷ 640円 → 312株 → 300株
    assert tr[1]["status"] == "見送り"                                   # 2,500円×100株 > 20万円
    # 地合いが弱い（上限30%）：すでに株が25万円あると、あと5万円分しか買えない
    st = new_state("x")
    st["cash"] = 750_000
    st["holdings"] = {"C": {"name": "c", "shares": 250, "avg_cost": 1000.0}}
    s3, tr = settle(st, {"date": "2026-11-26", "sells": [], "buys": [buy("A")]}, {"A": 400.0, "C": 1000.0},
                    lot=100, stock_cap=0.30)
    assert tr[0]["status"] == "約定" and tr[0]["shares"] == 100           # 5万円 ÷ 400円 → 125株 → 100株
    s4, tr = settle(st, {"date": "2026-11-26", "sells": [], "buys": [buy("A")]}, {"A": 600.0, "C": 1000.0},
                    lot=100, stock_cap=0.30)
    assert tr[0]["status"] == "見送り" and tr[0]["reason"].startswith("地合いの上限")


def test_check_lot_rules():
    st = new_state("x")
    st["cash"] = 780_000
    st["holdings"] = {"C": {"name": "c", "shares": 220, "avg_cost": 1000.0}}   # 株22%
    ind = {"A": {"close": 450.0}, "B": {"close": 2500.0}, "D": {"close": 900.0}}
    weak = {"above": False, "dev": -3.0}
    # 地合いが弱い：期待度「中」はだめ
    errs = check_lot_rules({"buys": [buy("A", "中")], "sells": []}, st, ind, weak, 100)
    assert any("期待度「高」だけ" in e for e in errs)
    # 100株の代金が予定額を超える
    errs = check_lot_rules({"buys": [buy("B")], "sells": []}, st, ind, None, 100)
    assert any("100株の代金（約250,000円）" in e and "株価2,000円以下" in e for e in errs)
    # 上限まであと8万円：450円×100株=4.5万円は買えるが、900円×100株=9万円は買えない
    assert check_lot_rules({"buys": [buy("A")], "sells": []}, st, ind, weak, 100) == []
    errs = check_lot_rules({"buys": [buy("D")], "sells": []}, st, ind, weak, 100)
    assert any("上限まであと80,000円" in e for e in errs)
    # 売って枠を空ければ買える
    assert check_lot_rules({"buys": [buy("D")], "sells": [{"code": "C"}]}, st, ind, weak, 100) == []
    # 地合いが強ければ上限なし
    assert check_lot_rules({"buys": [buy("D", "中")], "sells": []}, st, ind, {"above": True}, 100) == []


def test_regime_cap_and_settings(tmp_path):
    data = tmp_path / "data"
    (data / "daily" / "2026-11-26").mkdir(parents=True)
    (data / "daily" / "2026-11-26" / "briefing.json").write_text(json.dumps({"trend25": {"above": False}}), encoding="utf-8")
    assert regime_cap(data, "2026-11-26") == 0.30 and regime_cap(data, "2026-11-27") is None
    assert trade_settings(data) == {"lot": 1}
    (tmp_path / "config.json").write_text(json.dumps({"lot": 100}), encoding="utf-8")
    assert trade_settings(data) == {"lot": 100}


def test_settle_run_uses_lot_and_cap(tmp_path):
    data = tmp_path / "data"
    (data / "orders").mkdir(parents=True)
    (tmp_path / "config.json").write_text(json.dumps({"lot": 100}), encoding="utf-8")
    (data / "state.json").write_text(json.dumps(new_state("2026-11-09")), encoding="utf-8")
    (data / "orders" / "2026-11-10.json").write_text(json.dumps(
        {"date": "2026-11-10", "summary": "s", "settled": False, "sells": [], "buys": [buy("A")]}), encoding="utf-8")
    d = data / "daily" / "2026-11-10"
    d.mkdir(parents=True)
    (d / "briefing.json").write_text(json.dumps({"trend25": {"above": False}}), encoding="utf-8")
    res = settle_run(date(2026, 11, 11), data, fetch=lambda t, dd: {"open": 640.0, "close": 650.0})
    st = json.loads((data / "state.json").read_text(encoding="utf-8"))
    # 予定20万円・上限30万円（総資産100万円の30%）→ 20万円 ÷ 640円 → 300株
    assert res["status"] == "ok" and st["holdings"]["A"]["shares"] == 300


def test_email_shows_regime_and_lot_plan():
    st = new_state("2026-11-09")
    order = {"date": "2026-11-26", "summary": "s", "buys": [buy("A")], "sells": [], "holds": []}
    body = build_email(order, st, [], [], "u", trend={"above": False, "dev": -2.5},
                       indicators={"A": {"close": 640.0}}, lot=100)["body"]
    assert "地合い：日経平均は25日線より下（-2.50%）→ 株は総資産の30%まで・新しい買いは期待度「高」のみ" in body
    assert "100株単位で約300株の見込み" in body and "新しい買いは100株単位です。" in body


# ---- 期待度「高」の実績しだいで上限を40%に（2026-11-25） ----

def _rv(n, x, conf="高"):
    return {"buys": [{"confidence": conf, "ret": 1.0, "x": x} for _ in range(n)]
            + [{"confidence": "高", "ret": None, "x": None}]}      # 評価中は数えない


def test_weak_cap_needs_ten_high_cases_beating_nikkei():
    from kabu.ledger import weak_cap
    assert weak_cap(None)["cap"] == 0.30
    assert weak_cap(_rv(9, 2.0))["cap"] == 0.30                      # 件数不足
    assert weak_cap(_rv(10, -0.5))["cap"] == 0.30                    # 平均がマイナス
    assert weak_cap(_rv(10, 2.0, conf="中"))["cap"] == 0.30           # 「高」以外は数えない
    w = weak_cap(_rv(10, 0.8))
    assert w["cap"] == 0.40 and w["high"] == {"n": 10, "avg_x": 0.8, "proven": True}


def test_cap_flows_to_checks_settle_and_text(tmp_path):
    st = new_state("x")
    st["cash"] = 650_000
    st["holdings"] = {"C": {"name": "c", "shares": 350, "avg_cost": 1000.0}}   # 株35%
    ind = {"A": {"close": 450.0}}
    order = {"buys": [buy("A")], "sells": []}
    assert check_lot_rules(order, st, ind, {"above": False, "cap": 0.30}, 100)   # 30%なら買えない
    assert check_lot_rules(order, st, ind, {"above": False, "cap": 0.40}, 100) == []   # 40%なら買える
    data = tmp_path / "data"
    (data / "daily" / "2026-11-26").mkdir(parents=True)
    (data / "daily" / "2026-11-26" / "briefing.json").write_text(
        json.dumps({"trend25": {"above": False, "cap": 0.40}}), encoding="utf-8")
    assert regime_cap(data, "2026-11-26") == 0.40
    f = {"total": 1_000_000, "stock_value": 350_000}
    t = {"close": 58000, "ma25": 60000, "dev": -3.3, "above": False, "cap": 0.40,
         "high": {"n": 12, "avg_x": 0.8, "proven": True}}
    text = "\n".join(trend_lines(t, f, 100))
    assert "株の合計は総資産の40%まで" in text and "上限まであと **50,000円**" in text and "条件を満たしているので40%" in text
    t2 = {**t, "cap": 0.30, "high": {"n": 3, "avg_x": -1.0, "proven": False}}
    assert "まだ満たしていないので30%" in "\n".join(trend_lines(t2, f, 100))
