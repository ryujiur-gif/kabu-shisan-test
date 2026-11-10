from kabu.ledger import new_state, amount_for, funds, settle, valuation

def order(buys=(), sells=()):
    return {"date": "2026-11-10", "buys": list(buys), "sells": list(sells)}

def b(code, conf="高"):
    return {"code": code, "name": f"N{code}", "confidence": conf, "reason": "r"}

def s(code):
    return {"code": code, "name": f"N{code}", "reason": "r"}

def test_new_state():
    st = new_state("2026-11-10")
    assert st["cash"] == 1_000_000 and st["holdings"] == {} and st["start_date"] == "2026-11-10"

def test_amounts():
    assert (amount_for("高"), amount_for("中"), amount_for("低")) == (200_000, 100_000, 50_000)

def test_amounts_scale_with_total():
    assert (amount_for("高", 1_234_567), amount_for("中", 1_234_567), amount_for("低", 800_000)) == (246_000, 123_000, 40_000)

def test_funds():
    st = new_state("x"); st["cash"] = 600_000; st["last_closes"] = {"A": 2000.0}
    st["holdings"] = {"A": {"name": "a", "shares": 100, "avg_cost": 1000.0},
                      "B": {"name": "b", "shares": 100, "avg_cost": 2000.0}}
    f = funds(st)
    assert f["total"] == 1_000_000 and f["stock_value"] == 400_000
    assert abs(f["cash_ratio"] - 0.6) < 1e-9 and abs(f["weights"]["A"] - 0.2) < 1e-9

def test_buy_high():
    st, tr = settle(new_state("x"), order([b("7203")]), {"7203": 2000.0})
    assert st["holdings"]["7203"]["shares"] == 100
    assert st["cash"] == 800_000
    assert tr[0]["status"] == "約定" and tr[0]["side"] == "買" and tr[0]["amount"] == 200_000

def test_sell_first_then_buy_with_proceeds():
    st = new_state("x"); st["cash"] = 10_000
    st["holdings"] = {"6758": {"name": "N6758", "shares": 250, "avg_cost": 3000.0}}
    st, tr = settle(st, order([b("7203", "中")], [s("6758")]), {"6758": 4000.0, "7203": 1000.0})
    assert "6758" not in st["holdings"]
    assert st["holdings"]["7203"]["shares"] == 101  # 総資産101万円の10% = 101,000円
    assert st["cash"] == 10_000 + 1_000_000 - 101_000
    assert [t["side"] for t in tr] == ["売", "買"]

def test_insufficient_cash_skips():
    st = new_state("x"); st["cash"] = 30_000
    st, tr = settle(st, order([b("7203", "中")]), {"7203": 50_000.0})
    assert st["cash"] == 30_000 and tr[0]["status"] == "見送り" and "7203" not in st["holdings"]

def test_partial_cash_buys_what_it_can():
    st = new_state("x"); st["cash"] = 30_000
    st["holdings"] = {"6758": {"name": "N6758", "shares": 970, "avg_cost": 1000.0}}
    st, tr = settle(st, order([b("7203", "高")]), {"7203": 1000.0, "6758": 1000.0})
    assert st["holdings"]["7203"]["shares"] == 30 and st["cash"] == 0

def test_missing_open_cancels_only_that_order():
    st, tr = settle(new_state("x"), order([b("7203"), b("9984")]), {"9984": 1000.0})
    assert {t["code"]: t["status"] for t in tr} == {"7203": "取消", "9984": "約定"}

def test_avg_cost_weighted():
    st = new_state("x")
    st["holdings"] = {"7203": {"name": "N7203", "shares": 100, "avg_cost": 1000.0}}
    st, _ = settle(st, order([b("7203", "中")]), {"7203": 2000.0})
    h = st["holdings"]["7203"]
    assert h["shares"] == 160 and abs(h["avg_cost"] - (100 * 1000 + 60 * 2000) / 160) < 1e-9

def test_sell_not_held_is_cancelled():
    st, tr = settle(new_state("x"), order(sells=[s("6758")]), {"6758": 100.0})
    assert tr[0]["status"] == "取消" and st["cash"] == 1_000_000

def test_valuation_uses_close_or_avg_cost():
    st = new_state("x"); st["cash"] = 500
    st["holdings"] = {"A": {"name": "a", "shares": 10, "avg_cost": 100.0},
                      "B": {"name": "b", "shares": 5, "avg_cost": 200.0}}
    v = valuation(st, {"A": 150.0})
    assert v == {"total": 500 + 1500 + 1000, "cash": 500, "stock_value": 2500}
