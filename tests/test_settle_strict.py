import json
from datetime import date
from kabu.settle import run

MON = date(2026, 11, 9)   # 月曜（営業日）
TUE = date(2026, 11, 10)


def setup(tmp_path):
    (tmp_path / "orders").mkdir()
    (tmp_path / "state.json").write_text(json.dumps(
        {"start_date": MON.isoformat(), "cash": 1_000_000, "holdings": {}, "benchmark": {}}), encoding="utf-8")
    (tmp_path / "orders" / "2026-11-09.json").write_text(json.dumps(
        {"date": MON.isoformat(), "summary": "s", "settled": False,
         "buys": [{"code": "7203", "name": "A", "confidence": "高", "reason": "r"},
                  {"code": "6758", "name": "B", "confidence": "低", "reason": "r"}],
         "sells": []}), encoding="utf-8")


def fetch_missing_one(ticker, d):
    """6758 だけ株価が取れない。"""
    if ticker == "6758.T":
        return None
    return {"open": 1000.0, "close": 1100.0}


def test_partial_price_failure_on_latest_day_is_retried_not_cancelled(tmp_path):
    setup(tmp_path)
    res = run(TUE, tmp_path, fetch=fetch_missing_one)
    assert res["status"] == "price_error" and "6758" in res["message"]
    order = json.loads((tmp_path / "orders" / "2026-11-09.json").read_text(encoding="utf-8"))
    assert order["settled"] is False                 # 何も書き込まれていない
    assert not (tmp_path / "trades.csv").exists()


def test_all_prices_ok_settles(tmp_path):
    setup(tmp_path)
    res = run(TUE, tmp_path, fetch=lambda t, d: {"open": 1000.0, "close": 1100.0})
    assert res["status"] == "ok" and "2 件" in res["message"]
