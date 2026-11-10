import json
from kabu.report import build_email, build_site
from kabu.finalize import run as finalize_run

ORDER = {"date": "2026-11-10", "summary": "米株高で輸出株に追い風。",
         "buys": [{"code": "7203", "name": "トヨタ自動車", "confidence": "高", "reason": "円安"},
                  {"code": "6758", "name": "ソニーグループ", "confidence": "低", "reason": "決算"}],
         "sells": [],
         "holds": [{"code": "9984", "name": "ソフトバンクグループ", "outlook": "上昇", "reason": "AI需要"}]}
STATE = {"start_date": "2026-11-09", "cash": 800000,
         "holdings": {"9984": {"name": "ソフトバンクグループ", "shares": 10, "avg_cost": 20000.0}},
         "last_closes": {"9984": 21000.0}, "benchmark": {"start_open": 50000.0}}
HIST = [{"date": "2026-11-09", "total": "1010000", "cash": "800000", "stock_value": "210000",
         "nikkei_close": "50500", "benchmark_value": "1010000"},
        {"date": "2026-11-10", "total": "1023456", "cash": "800000", "stock_value": "223456",
         "nikkei_close": "50000", "benchmark_value": "1000000"}]
TRADES = [{"date": "2026-11-09", "side": "買", "code": "9984", "name": "ソフトバンクグループ",
           "shares": "10", "price": "20000", "amount": "200000", "status": "約定", "reason": "x"}]

def test_subject_format():
    e = build_email(ORDER, STATE, HIST, TRADES, "https://example.github.io/k/")
    assert e["subject"] == "【株予想】11/10 買い：トヨタ自動車・ソニーグループ／売り：なし"

def test_body_contents():
    body = build_email(ORDER, STATE, HIST, TRADES, "https://example.github.io/k/")["body"]
    assert "+23,456円" in body and "+2.35%" in body
    assert "日経平均" in body and "https://example.github.io/k/" in body
    # 総資産 = 現金80万 + 9984 10株×21,000 = 101万円 → 高20% / 低5%
    assert "202,000円（総資産の20%）" in body and "50,000円（総資産の5%）" in body
    assert "【資金状況（前日終値）】" in body and "総資産 1,010,000円" in body and "（79%）" in body
    assert body.rstrip().endswith("※試験運用です。投資判断はご自身の責任で行ってください。")

def test_body_shows_hold_outlook_and_no_buys():
    body = build_email(dict(ORDER, buys=[]), STATE, HIST, TRADES, "u")["body"]
    assert "・なし（本日は買いの基準を満たす銘柄なし）" in body
    assert "【持ち株の見通し（保有継続）】" in body and "ソフトバンクグループ（9984）まだ上がりそう" in body

def test_body_before_first_history():
    body = build_email(ORDER, STATE, [], [], "u")["body"]
    assert "1,000,000円" in body

def test_site_html():
    html = build_site(STATE, HIST, TRADES, ORDER)
    assert "<title>株予想 成績</title>" in html and "2026-11-10" in html and "トヨタ自動車" in html

def test_finalize_rejects_bad_order(tmp_path):
    (tmp_path / "data" / "orders").mkdir(parents=True)
    (tmp_path / "data" / "state.json").write_text(json.dumps(STATE), encoding="utf-8")
    bad = dict(ORDER, holds=[])
    (tmp_path / "data" / "orders" / "2026-11-10.json").write_text(json.dumps(bad), encoding="utf-8")
    code, errs = finalize_run("2026-11-10", tmp_path, universe={"7203": "", "6758": ""}, check_note_files=False)
    assert code == 1 and errs

def test_finalize_writes_outputs(tmp_path):
    (tmp_path / "data" / "orders").mkdir(parents=True)
    st = STATE
    (tmp_path / "data" / "state.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "data" / "orders" / "2026-11-10.json").write_text(json.dumps(ORDER), encoding="utf-8")
    code, errs = finalize_run("2026-11-10", tmp_path, universe={"7203": "", "6758": ""}, check_note_files=False)
    assert code == 0 and errs == []
    assert json.loads((tmp_path / "out" / "email.json").read_text(encoding="utf-8"))["subject"].startswith("【株予想】")
    assert (tmp_path / "docs" / "index.html").exists()

def test_email_market_section():
    mk = [{"label": "NYダウ", "close": 51285.73, "chg": -0.46, "date": "2026-11-06"},
          {"label": "金", "close": None, "chg": None, "date": "-"}]
    body = build_email(ORDER, STATE, HIST, TRADES, "u", market=mk)["body"]
    assert "【主要指標（前日終値）】" in body and "NYダウ 51,285.73（-0.46%）" in body
    assert "金 取得できず" in body

def test_finalize_uses_briefing_json(tmp_path):
    (tmp_path / "data" / "orders").mkdir(parents=True)
    (tmp_path / "out").mkdir()
    st = STATE
    (tmp_path / "data" / "state.json").write_text(json.dumps(st), encoding="utf-8")
    (tmp_path / "data" / "orders" / "2026-11-10.json").write_text(json.dumps(ORDER), encoding="utf-8")
    (tmp_path / "out" / "briefing.json").write_text(json.dumps({"today": "2026-11-10", "market": [
        {"label": "NYダウ", "close": 1.0, "chg": 0.1, "date": "x"}]}), encoding="utf-8")
    finalize_run("2026-11-10", tmp_path, universe={"7203": "", "6758": ""}, check_note_files=False)
    assert "NYダウ" in json.loads((tmp_path / "out" / "email.json").read_text(encoding="utf-8"))["body"]


def test_finalize_requires_notes(tmp_path):
    (tmp_path / "data" / "orders").mkdir(parents=True)
    (tmp_path / "data" / "state.json").write_text(json.dumps(STATE), encoding="utf-8")
    (tmp_path / "data" / "orders" / "2026-11-10.json").write_text(json.dumps(ORDER), encoding="utf-8")
    code, errs = finalize_run("2026-11-10", tmp_path, universe={"7203": "", "6758": ""})
    assert code == 1 and any("企業メモ" in e for e in errs)
