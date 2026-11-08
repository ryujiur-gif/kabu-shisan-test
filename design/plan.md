# 株予想 試験運用プログラム Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 平日朝7時にクラウドのClaudeが日本株の買い2・売り2を選んでGmailで通知し、仮想100万円の売買を始値で記録して、GitHub Pagesで成績を公開する。

**Architecture:** 計算はすべて Python パッケージ `kabu`（決定的・テスト済み）が担い、Claudeルーティンは「確定スクリプト実行 → ニュース調査 → 注文JSON作成 → 仕上げスクリプト実行 → Gmail送信 → push」だけを行う。状態はリポジトリ内の JSON/CSV、成績ページは `docs/index.html`（GitHub Pages）。

**Tech Stack:** Python 3.11+、yfinance（株価、失敗時 stooq CSV）、jpholiday、pytest、Chart.js 4.4.1（CDN, cdnjs）、Claude ルーティン（RemoteTrigger）、Gmail コネクタ。

**Spec:** `G:\マイドライブ\投資アプリ\設計書.md`

## Global Constraints
- 原資 1,000,000 円。手数料・税金は無視。空売りなし。
- 対象は日経225採用銘柄のみ（`data/nikkei225.csv`）。ティッカーは `<4桁コード>.T`。
- 購入額：期待度 高=200,000円、中=100,000円、低=50,000円。株数 = floor(min(購入額, 現金) / 始値)、0株なら見送り。
- 売り：持ち株から最大2銘柄、全株売却。売りを先に約定し、その代金を同日の買いに使える。
- 約定価格：通知日の始値。評価：各営業日の終値。
- 休場：土日・祝日（jpholiday）・12/31〜1/3。
- 実行：平日 7:00 JST（cron `0 22 * * 0-4` UTC）。宛先 ryuji.ur@gmail.com。
- リポジトリは公開（GitHub Pages 無料のため）。個人情報・秘密情報を置かない。
- 作業コピーは `C:\Users\sassu\dev\kabu-shisan-test`（Googleドライブ内に .git を置かない）。設計書・計画書はドライブ側に残す。
- メール本文末尾に「※試験運用です。投資判断はご自身の責任で行ってください。」

## Review Focus
1. 同じ日にルーティンが2回動いた → 二重約定しない（注文ファイルに `settled` を記録）。Task 5 でテスト。
2. 始値が取れない銘柄（売買停止・データ欠落）→ その注文だけ「取消」として記録し、他は約定。Task 3 でテスト。
3. 売り指定が持ち株にない／買い指定が225外 → 検証で弾き、ルーティンが選び直す。Task 4 でテスト。
4. 現金不足 → 買える株数だけ、0株なら見送り。Task 3 でテスト。
5. 株価データ取得が全面失敗 → 確定をせず、メールに「株価取得失敗」と明記して終了（記録を壊さない）。Task 5 でテスト。

---

## ファイル構成
```
kabu/__init__.py
kabu/market_calendar.py   休場判定
kabu/prices.py            株価取得（yfinance→stooq）
kabu/ledger.py            状態・約定・評価
kabu/picks.py             注文JSONの検証、銘柄一覧
kabu/report.py            メール文面・成績ページ生成
kabu/settle.py            CLI: 前営業日の確定と評価記録
kabu/finalize.py          CLI: 注文検証→メール文→ページ生成
data/nikkei225.csv        code,name
data/state.json           {"start_date","cash","holdings":{code:{"name","shares","avg_cost"}},"benchmark":{"start_open"}}
data/trades.csv           date,side,code,name,shares,price,amount,status,reason
data/history.csv          date,total,cash,stock_value,nikkei_close,benchmark_value
data/orders/YYYY-MM-DD.json  注文（通知日=約定日）
docs/index.html           成績ページ
out/email.json            {"subject","body"}（コミットしない）
ROUTINE.md                ルーティンへの指示書
tests/...
```

注文JSON形式：
```json
{"date":"2026-11-10","summary":"市況の要約(3〜5行)",
 "buys":[{"code":"7203","name":"トヨタ自動車","confidence":"高","reason":"..."}],
 "sells":[{"code":"6758","name":"ソニーグループ","reason":"..."}],
 "settled":false}
```

---

### Task 1: 雛形と休場判定
**Files:** Create `pyproject.toml`, `requirements.txt`(yfinance, jpholiday, pytest), `.gitignore`(out/, __pycache__), `kabu/__init__.py`, `kabu/market_calendar.py`, `tests/test_market_calendar.py`
**Interfaces — Produces:** `is_trading_day(d: date) -> bool`, `previous_trading_day(d: date) -> date`

- [ ] Step 1: テスト — `is_trading_day(date(2026,11,9))` True（月）、`date(2026,11,8)` False（日）、`date(2026,11,23)` False（勤労感謝の日）、`date(2026,12,31)`/`date(2027,1,2)` False、`previous_trading_day(date(2026,11,24)) == date(2026,11,20)`。
- [ ] Step 2: `pytest tests/test_market_calendar.py -v` → FAIL。
- [ ] Step 3: 実装（jpholiday.is_holiday + 土日 + 12/31〜1/3）。
- [ ] Step 4: PASS 確認。
- [ ] Step 5: `git init` 後コミット `feat: market calendar`。

### Task 2: 株価取得
**Files:** Create `kabu/prices.py`, `tests/test_prices.py`
**Interfaces — Produces:** `get_day_prices(codes: list[str], d: date, fetch=None) -> dict[str, dict]`（`{"7203": {"open": float, "close": float}}`、取れない銘柄はキー無し）、`get_nikkei(d: date, fetch=None) -> dict|None`（`^N225`）。`fetch(ticker, d) -> dict|None` を差し替え可能にしてテストする。

- [ ] Step 1: テスト — 偽fetchで、一部銘柄が None のときキーが欠けること、yfinance側が例外なら stooq 側が呼ばれること。
- [ ] Step 2: FAIL 確認。 Step 3: 実装（yfinance `history(start=d, end=d+1日)`、stooq `https://stooq.com/q/d/l/?s=7203.jp&i=d`）。 Step 4: PASS。
- [ ] Step 5: 実データ確認 — `python -c` で 7203 と ^N225 の 2026-11-06 の始値・終値が取れること。
- [ ] Step 6: コミット。

### Task 3: 台帳（約定・評価）
**Files:** Create `kabu/ledger.py`, `tests/test_ledger.py`
**Interfaces — Produces:** `new_state(start_date: str) -> dict`、`amount_for(confidence: str) -> int`、`settle(state: dict, order: dict, opens: dict[str,float]) -> tuple[dict, list[dict]]`（trade行：date,side,code,name,shares,price,amount,status(`約定`/`取消`/`見送り`),reason）、`valuation(state: dict, closes: dict[str,float]) -> dict`（total,cash,stock_value。終値が無い銘柄は avg_cost で評価）。

- [ ] Step 1: テスト —
  - 現金1,000,000、買い 高(始値2,000) → 100株、現金800,000。
  - 売り→買いの順：持ち株売却代金で買えること。
  - 現金30,000で 中(始値50,000) → `見送り`、現金不変。
  - 始値が無い銘柄 → `取消`、他は約定。
  - 買い増しで avg_cost が加重平均。売りで holdings から削除。
- [ ] Step 2: FAIL。 Step 3: 実装（現金・金額は円の整数、端数切り捨て）。 Step 4: PASS。 Step 5: コミット。

### Task 4: 注文検証と銘柄一覧
**Files:** Create `data/nikkei225.csv`（日経公式の構成銘柄一覧から作成、225行を確認）、`kabu/picks.py`, `tests/test_picks.py`
**Interfaces — Produces:** `load_universe(path="data/nikkei225.csv") -> dict[str,str]`、`validate_order(order: dict, state: dict, universe: dict) -> list[str]`（エラー文の一覧、空なら正常）。

- [ ] Step 1: テスト — 買い2件・期待度が高中低以外／225外コード／売りが持ち株外／売り3件以上／持ち株0で売りありはエラー。持ち株1で売り1件・買い2件は正常。
- [ ] Step 2〜4: FAIL→実装→PASS。`len(load_universe()) == 225` も確認。 Step 5: コミット。

### Task 5: 確定CLI
**Files:** Create `kabu/settle.py`, `tests/test_settle.py`
**Interfaces — Consumes:** Task 1〜3。 **Produces:** `python -m kabu.settle --today YYYY-MM-DD [--data data]`。標準出力に JSON `{"status": "ok"|"holiday"|"price_error"|"nothing", "holdings": [...], "total": int, "message": str}`。`run(today: date, data_dir: Path, fetch=None) -> dict`。

動作：今日が休場→`holiday`。前営業日 p の注文ファイルがあり `settled` false なら、p の始値で `settle`、trades.csv 追記、`settled: true` に更新。p の終値で `valuation`、history.csv に p の行を追加（同日行があれば上書き）。benchmark は初回確定日の日経始値を `state.benchmark.start_open` に保存し、`benchmark_value = 1,000,000 × 日経終値 / start_open`。state.json が無ければ `new_state` で作る。

- [ ] Step 1: テスト — 2回実行しても trades 行数が増えない／休場日は何も書かない／価格が全部取れないと `price_error` でファイル不変／注文が無い日も history は追記。
- [ ] Step 2〜4: FAIL→実装→PASS。 Step 5: コミット。

### Task 6: メール文面と成績ページ
**Files:** Create `kabu/report.py`, `kabu/finalize.py`, `tests/test_report.py`
**Interfaces — Produces:** `build_email(order, state, history_rows, last_trades, site_url) -> dict`（subject, body）、`build_site(state, history_rows, trades_rows, closes) -> str`（HTML）。CLI `python -m kabu.finalize --today YYYY-MM-DD` → 注文を `validate_order`（エラーなら終了コード1でエラー文を表示）→ `out/email.json` と `docs/index.html` を書く。

- 件名：`【株予想】11/10 買い：トヨタ自動車・ソニーグループ／売り：なし`
- 本文：本日の買い（銘柄・期待度・予定額・理由）、売り（理由）、市況要約、昨日の約定結果、総資産・損益(円/%)、日経平均に同額投資した場合との差、成績ページURL、末尾の注記。
- ページ：スマホ幅前提、資産推移（本プログラム vs 日経平均）の折れ線、持ち株表、取引履歴（新しい順）、最新の予想と理由。ライト/ダーク対応。

- [ ] Step 1: テスト — 件名の形式、本文に損益と注記が含まれる、HTMLに `<title>株予想 成績</title>` と history の日付が含まれる。
- [ ] Step 2〜4: FAIL→実装→PASS。 Step 5: 疑似データでページを生成し目視確認。 Step 6: コミット。

### Task 7: GitHub 公開
- [ ] Step 1: ブラウザ（竜司さんがログイン中のGitHub）で公開リポジトリ `kabu-shisan-test` を作成。
- [ ] Step 2: `git remote add origin` → `git push -u origin main`（認証画面が出たら竜司さんが許可）。
- [ ] Step 3: Settings → Pages で `main` / `/docs` を公開。URL `https://<ユーザー名>.github.io/kabu-shisan-test/` が開けることを確認。

### Task 8: ルーティン設定と試運転
**Files:** Create `ROUTINE.md`
- [ ] Step 1: ROUTINE.md に手順を記述：`pip install -r requirements.txt` → `python -m kabu.settle --today <JST今日>`（holiday なら終了）→ Web検索で前夜の米国市場・為替・金利・地政学・決算を調査 → `data/orders/<今日>.json` 作成 → `python -m kabu.finalize`（エラーなら直して再実行）→ Gmail で ryuji.ur@gmail.com に `out/email.json` を送信 → `git commit` & `push`。price_error 時は銘柄選びまで行い、メールに取得失敗を明記。
- [ ] Step 2: RemoteTrigger create（cron `0 22 * * 0-4`、リポジトリ指定、Gmailコネクタ付き）。claude.ai に GitHub 連携が無い場合は竜司さんに許可してもらう。
- [ ] Step 3: RemoteTrigger run で試運転 → get_run_log で確認 → メール受信、Pages 更新、リポジトリに注文ファイルがあることを確認。
- [ ] Step 4: 設計書と作業記録（CLAUDE.md への追記は竜司さんの確認後）を更新。
