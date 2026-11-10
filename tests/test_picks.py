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

def test_holding_without_selling_is_ok():
    assert validate_order(o([("7203", "高"), ("6758", "中")]), st("9984", "7203"), U) == []

def test_selling_one_of_many_is_ok():
    assert validate_order(o([("7203", "高"), ("6758", "中")], ["9984"]), st("9984", "7203"), U) == []

def test_duplicate_sell():
    assert validate_order(o([("7203", "高"), ("6758", "中")], ["9984", "9984"]), st("9984", "7203"), U)

def test_missing_reason():
    order = o([("7203", "高"), ("6758", "中")]); order["buys"][0]["reason"] = ""
    assert validate_order(order, st(), U)

def test_date_must_match_today():
    order = o([("7203", "高"), ("6758", "中")])
    assert validate_order(order, st(), U, today="2026-11-10") == []
    assert validate_order(order, st(), U, today="2026-11-11")

def test_settled_true_rejected():
    order = o([("7203", "高"), ("6758", "中")]); order["settled"] = True
    assert validate_order(order, st(), U)

def test_missing_name_rejected():
    order = o([("7203", "高"), ("6758", "中")]); del order["buys"][0]["name"]
    assert validate_order(order, st(), U)

def test_non_list_rejected():
    order = o([("7203", "高"), ("6758", "中")]); order["sells"] = "none"
    assert validate_order(order, st(), U)


from kabu.picks import check_notes


def _note(d, code, updated):
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{code}.md").write_text(f"# 企業メモ\n更新日：{updated}\n", encoding="utf-8")


def test_check_notes_ok(tmp_path):
    _note(tmp_path, "7203", "2026-11-01")
    _note(tmp_path, "6758", "2026-09-01")
    order = o([("7203", "高"), ("6758", "中")])
    assert check_notes(order, tmp_path, "2026-11-10") == []


def test_check_notes_missing_and_old(tmp_path):
    _note(tmp_path, "6758", "2026-07-01")          # 90日超
    order = o([("7203", "高"), ("6758", "中")], ["9984"])
    errs = check_notes(order, tmp_path, "2026-11-10")
    assert any("7203" in e and "ありません" in e for e in errs)
    assert any("6758" in e and "古い" in e for e in errs)
    assert any("9984" in e for e in errs)


def test_check_notes_bad_date(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "7203.md").write_text("更新日：YYYY-MM-DD\n", encoding="utf-8")
    _note(tmp_path, "6758", "2026-11-01")
    errs = check_notes(o([("7203", "高"), ("6758", "中")]), tmp_path, "2026-11-10")
    assert any("7203" in e and "更新日" in e for e in errs)
