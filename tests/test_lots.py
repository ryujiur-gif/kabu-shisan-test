"""100株単位で売買した場合の並行記録。"""
import json

from kabu import lots
from kabu.ledger import new_state, sell_shares, settle
from kabu.report import build_email, build_site


def bar(d, o, c):
    return {"d": d, "o": o, "c": c, "v": 1000.0}


SERIES = {
    "N225": [bar("2026-11-06", 50000, 50000), bar("2026-11-09", 50000, 50500), bar("2026-11-10", 50500, 51000),
             bar("2026-11-11", 51000, 51500)],
    "A": [bar("2026-11-06", 1000, 1000), bar("2026-11-09", 1000, 1050), bar("2026-11-10", 1050, 1100),
          bar("2026-11-11", 1100, 1200)],
    "B": [bar("2026-11-06", 12000, 12000), bar("2026-11-09", 12000, 12100), bar("2026-11-10", 12100, 12200),
          bar("2026-11-11", 12200, 12300)],
}
ORDERS = {
    "2026-11-09": {"date": "2026-11-09", "sells": [],
                   "buys": [{"code": "A", "name": "a", "confidence": "中", "reason": "r"},
                            {"code": "B", "name": "b", "confidence": "中", "reason": "r"}]},
    "2026-11-11": {"date": "2026-11-11", "buys": [],
                   "sells": [{"code": "A", "name": "a", "reason": "r", "portion": "半分"}]},
}


def test_lot_rounding_in_settle():
    st = new_state("x")
    order = {"date": "2026-11-09", "sells": [], "buys": [{"code": "A", "name": "a", "confidence": "中", "reason": "r"},
                                                         {"code": "B", "name": "b", "confidence": "高", "reason": "r"}]}
    st, tr = settle(st, order, {"A": 990.0, "B": 2500.0}, lot=100)
    assert tr[0]["shares"] == 100 and tr[0]["status"] == "約定"          # 10万円 ÷ 990円 = 101株 → 100株
    assert tr[1]["shares"] == 0 and tr[1]["status"] == "見送り"           # 20万円では 2,500円×100株 が買えない
    assert st["cash"] == 1_000_000 - 99_000


def test_sell_half_respects_lot():
    assert sell_shares(300, "半分", 100) == 100 and sell_shares(200, "半分", 100) == 100
    assert sell_shares(100, "半分", 100) == 100 and sell_shares(300, "全部", 100) == 300
    assert sell_shares(11, "半分") == 5     # 本体（1株単位）は従来どおり


def test_simulate_small_and_large_capital():
    small = lots.simulate(ORDERS, SERIES, [], 1_000_000, "2026-11-09")
    s = lots.summarize("100万円", 1_000_000, small)
    assert s["n_orders"] == 2 and s["n_bought"] == 1 and s["n_short"] == 1     # B（120万円/100株）は買えない
    big = lots.simulate(ORDERS, SERIES, [], 10_000_000, "2026-11-09")
    b = lots.summarize("1,000万円", 10_000_000, big)
    assert b["n_bought"] == 2 and b["n_short"] == 0
    assert big["state"]["holdings"]["A"]["shares"] == 500                      # 1,000株 → 半分の500株を売却
    # 最終日の総資産 = 現金 + A 500株×1,200 + B 0株（100万円では B は 12,000円×100株=120万円 > 予算100万円）
    h = big["history"][-1]
    assert h["date"] == "2026-11-11" and h["total"] == h["cash"] + h["stock_value"]
    assert [x["date"] for x in big["history"]] == ["2026-11-09", "2026-11-10", "2026-11-11"]


def test_simulate_one_lot_half_sell_sells_all():
    small = lots.simulate(ORDERS, SERIES, [], 1_000_000, "2026-11-09")
    sells = [t for t in small["trades"] if t["side"] == "売"]
    assert sells[0]["shares"] == 100 and "A" not in small["state"]["holdings"]


def test_simulate_applies_dividend_and_split():
    acts = [{"date": "2026-11-10", "side": "配当", "code": "A", "price": "10"},
            {"date": "2026-11-10", "side": "分割", "code": "A", "price": "2.0"}]
    orders = {"2026-11-09": ORDERS["2026-11-09"]}
    sim = lots.simulate(orders, SERIES, acts, 10_000_000, "2026-11-09")
    base = lots.simulate(orders, SERIES, [], 10_000_000, "2026-11-09")
    assert sim["state"]["holdings"]["A"]["shares"] == base["state"]["holdings"]["A"]["shares"] * 2
    assert sim["state"]["cash"] == base["state"]["cash"] + base["state"]["holdings"]["A"]["shares"] * 10


def test_gap_up_buy_is_skipped_like_main():
    series = {**SERIES, "A": [bar("2026-11-06", 1000, 1000), bar("2026-11-09", 1060, 1050)]}
    only_a = {"date": "2026-11-09", "sells": [], "buys": ORDERS["2026-11-09"]["buys"][:1]}
    sim = lots.simulate({"2026-11-09": only_a}, series, [], 10_000_000, "2026-11-09")
    a = [t for t in sim["trades"] if t["code"] == "A"][0]
    assert a["status"] == "見送り" and a["reason"].startswith("始値が")
    assert lots.summarize("x", 10_000_000, sim)["n_short"] == 0       # 寄り付き高の見送りは「100株に届かず」に数えない


def test_update_writes_files_and_lines(tmp_path):
    data = tmp_path / "data"
    (data / "orders").mkdir(parents=True)
    (data / "state.json").write_text(json.dumps({"start_date": "2026-11-09", "cash": 0, "holdings": {}}), encoding="utf-8")
    for d, o in ORDERS.items():
        (data / "orders" / f"{d}.json").write_text(json.dumps({**o, "summary": "s"}), encoding="utf-8")
    (data / "history.csv").write_text("date,total,cash,stock_value,nikkei_close,benchmark_value\n"
                                      "2026-11-11,1012000,0,0,51500,1030000\n", encoding="utf-8")
    assert lots.order_codes(data) == ["A", "B"]
    out = lots.update(tmp_path, SERIES)
    assert out["asof"] == "2026-11-11" and out["main_ret"] == 1.2 and out["bench_ret"] == 3.0
    assert [x["name"] for x in out["scenarios"]] == ["100万円", "300万円", "500万円", "1,000万円"]
    assert (data / "lots" / "history.csv").read_text(encoding="utf-8").count("\n") == 1 + 4 * 3
    assert lots.load(tmp_path) == out
    text = "\n".join(lots.lines(out))
    assert "■ 100株単位で売買した場合" in text and "資金100万円" in text and "1件は100株に届かず買えず" in text
    assert lots.update(tmp_path, {"N225": []}) is None and lots.lines(None) == []


def test_email_and_site_show_lots():
    s = {"asof": "2026-11-11", "main_ret": 1.2, "bench_ret": 3.0, "scenarios": [
        {"name": "100万円", "start": 1_000_000, "total": 1_010_000, "ret": 1.0, "cash_ratio": 0.9, "n_orders": 2,
         "n_bought": 1, "n_short": 1, "holdings": [], "asof": "2026-11-11"}]}
    st = new_state("2026-11-09")
    order = {"date": "2026-11-12", "summary": "s", "buys": [], "sells": [], "holds": []}
    body = build_email(order, st, [], [], "u", lots=s)["body"]
    assert "資金100万円：+1.00%（1,010,000円）　買えた予想 1/2件・1件は100株に届かず買えず・現金 90%" in body
    assert "100株単位で売買した場合" in build_site(st, [], [], None, lots=s)
    assert "100株単位" not in build_email(order, st, [], [], "u")["body"]
