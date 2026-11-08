import csv, json
from datetime import date
from kabu.settle import run

MON, TUE, WED = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11)

def fake(prices):
    def f(ticker, d):
        return prices.get((ticker, d))
    return f

def write_order(dd, d, buys=(), sells=()):
    (dd / "orders").mkdir(parents=True, exist_ok=True)
    o = {"date": d.isoformat(), "summary": "s",
         "buys": [{"code": c, "name": c, "confidence": "高", "reason": "r"} for c in buys],
         "sells": [{"code": c, "name": c, "reason": "r"} for c in sells], "settled": False}
    (dd / "orders" / f"{d.isoformat()}.json").write_text(json.dumps(o, ensure_ascii=False), encoding="utf-8")

def rows(p):
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))

P = {("7203.T", MON): {"open": 2000.0, "close": 2100.0},
     ("^N225", MON): {"open": 50000.0, "close": 51000.0},
     ("7203.T", TUE): {"open": 2100.0, "close": 2200.0},
     ("^N225", TUE): {"open": 51000.0, "close": 50000.0}}

def test_first_run_creates_state(tmp_path):
    r = run(MON, tmp_path, fetch=fake(P))
    assert r["status"] == "nothing" and r["total"] == 1_000_000
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8"))["start_date"] == MON.isoformat()

def test_holiday_writes_nothing(tmp_path):
    assert run(date(2026, 11, 8), tmp_path, fetch=fake(P))["status"] == "holiday"
    assert not (tmp_path / "state.json").exists()

def test_settle_and_idempotent(tmp_path):
    run(MON, tmp_path, fetch=fake(P))
    write_order(tmp_path, MON, buys=["7203"])
    r1 = run(TUE, tmp_path, fetch=fake(P))
    r2 = run(TUE, tmp_path, fetch=fake(P))
    assert r1["status"] == r2["status"] == "ok"
    tr = rows(tmp_path / "trades.csv")
    assert len(tr) == 1 and tr[0]["shares"] == "100"
    h = rows(tmp_path / "history.csv")
    assert len(h) == 1 and h[0]["date"] == MON.isoformat()
    assert int(h[0]["total"]) == 800_000 + 100 * 2100
    assert int(h[0]["benchmark_value"]) == int(1_000_000 * 51000 / 50000)
    assert r2["holdings"][0]["code"] == "7203"

def test_price_error_leaves_files_untouched(tmp_path):
    run(MON, tmp_path, fetch=fake(P))
    write_order(tmp_path, MON, buys=["7203"])
    before = (tmp_path / "state.json").read_text(encoding="utf-8")
    r = run(TUE, tmp_path, fetch=fake({}))
    assert r["status"] == "price_error"
    assert (tmp_path / "state.json").read_text(encoding="utf-8") == before
    assert not (tmp_path / "trades.csv").exists()

def test_history_appended_without_order(tmp_path):
    run(MON, tmp_path, fetch=fake(P))
    write_order(tmp_path, MON, buys=["7203"])
    run(TUE, tmp_path, fetch=fake(P))
    r = run(WED, tmp_path, fetch=fake(P))
    assert r["status"] == "ok"
    assert [x["date"] for x in rows(tmp_path / "history.csv")] == [MON.isoformat(), TUE.isoformat()]

def test_missed_day_is_caught_up(tmp_path):
    run(MON, tmp_path, fetch=fake(P))
    write_order(tmp_path, MON, buys=["7203"])
    r = run(WED, tmp_path, fetch=fake(P))   # TUE run was missed
    assert r["status"] == "ok"
    assert len(rows(tmp_path / "trades.csv")) == 1
