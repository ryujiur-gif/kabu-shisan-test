from kabu.picks import load_universe, validate_order

U = {"7203": "トヨタ", "6758": "ソニー", "9984": "SBG"}

def st(*held):
    return {"cash": 1, "holdings": {c: {"name": c, "shares": 1, "avg_cost": 1.0} for c in held}}

def o(buys, sells=()):
    return {"date": "2026-11-10", "summary": "s",
            "buys": [{"code": c, "name": c, "confidence": k, "reason": "r"} for c, k in buys],
            "sells": [{"code": c, "name": c, "reason": "r"} for c in sells]}

def test_universe_has_225():
    u = load_universe()
    assert len(u) == 225 and u["7203"].startswith("トヨタ")

def test_valid_order():
    assert validate_order(o([("7203", "高"), ("6758", "低")], ["9984"]), st("9984"), U) == []

def test_buys_must_be_two():
    assert validate_order(o([("7203", "高")]), st(), U)

def test_bad_confidence():
    assert validate_order(o([("7203", "超"), ("6758", "中")]), st(), U)

def test_outside_universe():
    assert validate_order(o([("1234", "高"), ("6758", "中")]), st(), U)

def test_sell_not_held():
    assert validate_order(o([("7203", "高"), ("6758", "中")], ["9984"]), st(), U)

def test_too_many_sells():
    assert validate_order(o([("7203", "高"), ("6758", "中")], ["7203", "6758", "9984"]),
                          st("7203", "6758", "9984"), U)

def test_must_sell_two_when_holding_two_or_more():
    assert validate_order(o([("7203", "高"), ("6758", "中")], ["9984"]), st("9984", "7203"), U)

def test_duplicate_sell():
    assert validate_order(o([("7203", "高"), ("6758", "中")], ["9984", "9984"]), st("9984", "7203"), U)

def test_missing_reason():
    order = o([("7203", "高"), ("6758", "中")]); order["buys"][0]["reason"] = ""
    assert validate_order(order, st(), U)
