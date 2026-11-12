import csv
import json
from datetime import date, datetime, timezone

from kabu import health, prepare
from kabu.briefing import fix_nikkei, merge_nikkei
from kabu.ledger import replay
from kabu.picks import check_entry_rules, check_learning, pattern_cautions
from kabu.settle import run as settle_run

MON, TUE, WED, THU = date(2026, 11, 9), date(2026, 11, 10), date(2026, 11, 11), date(2026, 11, 12)
TRADE_FIELDS = ["date", "side", "code", "name", "shares", "price", "amount", "status", "reason"]
HIST_FIELDS = ["date", "total", "cash", "stock_value", "nikkei_close", "benchmark_value"]


def write_csv(p, fields, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def setup(root, cash=800000, hist_dates=("2026-11-09", "2026-11-10"), last="2026-11-10"):
    d = root / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "state.json").write_text(json.dumps({
        "start_date": "2026-11-09", "cash": cash,
        "holdings": {"7203": {"name": "トヨタ自動車", "shares": 100, "avg_cost": 2000.0}},
        "benchmark": {"start_open": 50000.0, "start_date": "2026-11-09"},
        "last_closes": {"7203": 2100.0}, "last_date": last}), encoding="utf-8")
    write_csv(d / "trades.csv", TRADE_FIELDS, [
        {"date": "2026-11-09", "side": "買", "code": "7203", "name": "トヨタ自動車", "shares": 100,
         "price": 2000.0, "amount": 200000, "status": "約定", "reason": "r"}])
    write_csv(d / "history.csv", HIST_FIELDS, [
        {"date": x, "total": 1010000, "cash": 800000, "stock_value": 210000, "nikkei_close": 51000.0,
         "benchmark_value": 1020000} for x in hist_dates])
    (d / "orders").mkdir(exist_ok=True)
    for x in ("2026-11-09", "2026-11-10"):
        (d / "orders" / f"{x}.json").write_text(json.dumps({"date": x, "settled": True}), encoding="utf-8")
    return d


def test_replay_matches_ledger():
    t = [{"date": "2026-11-09", "side": "買", "code": "7203", "name": "A", "shares": 100, "price": 2000.0,
          "amount": 200000, "status": "約定"},
         {"date": "2026-11-10", "side": "買", "code": "6758", "name": "B", "shares": 0, "price": 0, "amount": 0,
          "status": "取消"},
         {"date": "2026-11-11", "side": "売", "code": "7203", "name": "A", "shares": 100, "price": 2100.0,
          "amount": 210000, "status": "約定"}]
    assert replay(t) == {"cash": 1_010_000, "holdings": {}}
    assert replay(t[:1])["holdings"]["7203"]["shares"] == 100


def test_check_clean_state_has_no_problems(tmp_path):
    setup(tmp_path)
    assert health.check(tmp_path, WED) == []


def test_check_finds_mismatch_gap_missing_order_and_stale_nikkei(tmp_path):
    d = setup(tmp_path, cash=790000, hist_dates=("2026-11-09",), last="2026-11-10")
    (d / "orders" / "2026-11-10.json").unlink()
    probs = "\n".join(health.check(tmp_path, WED, [{"ticker": "^N225", "close": 1.0, "date": "2026-11-09"}]))
    assert "取引履歴からの計算" in probs
    assert "前営業日（2026-11-10）の予想が作られていません" in probs
    assert "抜けた日" in probs and "2026-11-10" in probs
    assert "日経平均が前営業日" in probs


def test_check_finds_old_unsettled_order(tmp_path):
    d = setup(tmp_path)
    (d / "orders" / "2026-11-09.json").write_text(json.dumps({"date": "2026-11-09", "settled": False}), encoding="utf-8")
    assert any("確定されていない注文" in p for p in health.check(tmp_path, WED))


def test_backfill_history_fills_missing_day(tmp_path):
    d = setup(tmp_path, hist_dates=("2026-11-09",), last="2026-11-10")
    series = {"7203": [{"d": "2026-11-09", "o": 2000, "c": 2100.0}, {"d": "2026-11-10", "o": 2100, "c": 2200.0}],
              "N225": [{"d": "2026-11-09", "o": 50000, "c": 51000.0}, {"d": "2026-11-10", "o": 51000, "c": 52000.0}]}
    assert health.backfill_history(tmp_path, series) == ["2026-11-10"]
    with open(d / "history.csv", encoding="utf-8") as f:
        row = list(csv.DictReader(f))[-1]
    assert row["date"] == "2026-11-10" and row["total"] == "1020000" and row["benchmark_value"] == "1040000"
    assert health.backfill_history(tmp_path, series) == []
    # 株価が欠けている日は埋めない
    setup(tmp_path, hist_dates=("2026-11-09",), last="2026-11-10")
    assert health.backfill_history(tmp_path, {"7203": series["7203"][:1], "N225": series["N225"]}) == []


def test_fix_nikkei_replaces_stale_bar():
    market = [{"label": "日経平均", "ticker": "^N225", "close": 60459.58, "chg": 2.87, "date": "2026-11-10"},
              {"label": "NYダウ", "ticker": "^DJI", "close": 1.0, "chg": 0.0, "date": "2026-11-11"}]
    nb = merge_nikkei([{"d": "2026-11-10", "o": 1, "c": 60459.58, "v": 0}],
                      [{"date": "2026-11-11", "nikkei_close": "61248.59"}])
    fixed = fix_nikkei(market, "2026-11-11", nb)
    assert fixed[0]["close"] == 61248.59 and fixed[0]["date"] == "2026-11-11" and fixed[0]["chg"] == 1.31
    assert fixed[1] == market[1]
    # 記録に無ければ個別取得、それも無ければ元のまま
    assert fix_nikkei(market, "2026-11-11", [], fetch=lambda d: {"open": 1.0, "close": 61000.0})[0]["close"] == 61000.0
    assert fix_nikkei(market, "2026-11-11", [], fetch=lambda d: None)[0]["date"] == "2026-11-10"


def test_settle_already_done_does_not_refetch(tmp_path):
    d = setup(tmp_path)

    def boom(ticker, day):
        raise AssertionError("確定済みの日に株価を取りに行ってはいけない")
    r = settle_run(WED, d, fetch=boom)
    assert r["status"] == "ok" and "確定済み" in r["message"]


def test_prepare_does_not_overwrite_done_day_with_error(tmp_path):
    ok = {"today": "2026-11-12", "status": "ok", "message": "確定しました"}
    early = datetime(2026, 11, 11, 22, 5, tzinfo=timezone.utc)   # 7:05 JST
    late = datetime(2026, 11, 12, 2, 18, tzinfo=timezone.utc)    # 11:18 JST（取引時間中）
    builds = []

    def build(root, today):
        builds.append(today)
        return f"# md{len(builds)}", {"today": today, "market": [], "indicators": {"7203": {"rsi14": 50}}}
    prepare.run(tmp_path, THU, settle_fn=lambda t, d: ok, build_fn=build, now=early)
    daily = tmp_path / "data" / "daily" / "2026-11-12"
    assert json.loads((daily / "indicators.json").read_text(encoding="utf-8")) == {"7203": {"rsi14": 50}}
    assert "indicators" not in json.loads((daily / "briefing.json").read_text(encoding="utf-8"))
    res = prepare.run(tmp_path, THU, settle_fn=lambda t, d: {"today": "2026-11-12", "status": "price_error"},
                      build_fn=build, now=late)
    assert res["status"] == "ok"
    assert json.loads((daily / "settle.json").read_text(encoding="utf-8"))["status"] == "ok"
    assert (daily / "briefing.md").read_text(encoding="utf-8") == "# md1" and len(builds) == 1
    # 7時前の再実行（予備の定時実行）では資料を作り直してよい。--force でも作り直す
    prepare.run(tmp_path, THU, settle_fn=lambda t, d: ok, build_fn=build, now=early)
    prepare.run(tmp_path, THU, settle_fn=lambda t, d: ok, build_fn=build, now=late, force=True)
    assert len(builds) == 3


def test_prepare_error_can_be_recovered_later(tmp_path):
    late = datetime(2026, 11, 12, 2, 18, tzinfo=timezone.utc)
    build = lambda root, today: ("# md", {"today": today, "market": []})
    prepare.run(tmp_path, THU, settle_fn=lambda t, d: {"status": "price_error"}, build_fn=build, now=late)
    prepare.run(tmp_path, THU, settle_fn=lambda t, d: {"status": "ok"}, build_fn=build, now=late)
    sp = tmp_path / "data" / "daily" / "2026-11-12" / "settle.json"
    assert json.loads(sp.read_text(encoding="utf-8"))["status"] == "ok"


def test_entry_rules():
    order = {"buys": [{"code": "7203", "confidence": "中"}, {"code": "6758", "confidence": "低"}]}
    ind = {"7203": {"rsi14": 80.0, "ma25_dev": 3.0}, "6758": {"rsi14": 50.0, "ma25_dev": 16.0}}
    errs = check_entry_rules(order, ind, [])
    assert len(errs) == 2 and "RSI 80" in errs[0] and "25日線" in errs[1]
    errs = check_entry_rules(order, {}, ["米 FOMC"])
    assert len(errs) == 1 and "7203" in errs[0]
    assert check_entry_rules(order, None, None) == []


def test_learning_checks():
    order = {"buys": [], "sells": []}
    assert check_learning(order, None, "", "") == []
    assert check_learning(order, {"n_buys": 0}, "", "") == []
    rv = {"n_buys": 2, "overall": {"n": 1},
          "cases_due": [{"key": "## 2026-11-02 買 7203", "title": "t"}]}
    errs = "\n".join(check_learning(order, rv, "", ""))
    assert "## 2026-11-02 買 7203" in errs and "playbook.md" in errs and "learned" in errs
    good = {**order, "learned": "急騰翌日の高寄りは見送り、押し目を待つことにした。"}
    assert check_learning(good, rv, "## 2026-11-02 買 7203 トヨタ\n- 教訓：…\n", "1. ルール") == []


def test_pattern_cautions():
    rv = {"patterns": [{"gid": "chg1d", "bucket": "前日+5%以上の急騰後", "kind": "弱み", "level": "傾向",
                        "n": 6, "avg_ret": -2.0, "avg_x": -3.0, "rest_n": 5, "rest_avg": 0.5, "advice": "押し目を待つ"}]}
    order = {"buys": [{"code": "7203", "name": "トヨタ自動車", "confidence": "中", "reason": "上方修正"}]}
    out = pattern_cautions(order, {"7203": {"chg1d": 8.0}}, rv, None)
    assert len(out) == 1 and "前日+5%以上の急騰後" in out[0] and "押し目を待つ" in out[0]
    assert pattern_cautions(order, {"7203": {"chg1d": 1.0}}, rv, None) == []
