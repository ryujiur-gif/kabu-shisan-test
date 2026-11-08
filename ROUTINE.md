# 毎朝のルーティン手順（クラウドの Claude 用）

あなたは日本株の試験運用プログラムの「朝の担当」です。以下を上から順に実行してください。
計算はすべてプログラムが行います。あなたが担当するのはニュース調査・銘柄選び・メール送信だけです。
**仮想売買の記録（data/ 以下の state.json・trades.csv・history.csv）を手で書き換えてはいけません。**

## 1. 準備
```bash
python -m pip install -q -r requirements.txt
python -m kabu.settle
```
出力の JSON を読みます。**`today` が本日の日付（日本時間）です。以降の手順では、この日付（例：2026-11-10）をそのまま文字で書き込んでください**（シェル変数は次のコマンドに引き継がれません）。
- `status` が `holiday` → 何もせず終了（メールも送らない）。
- `status` が `price_error` → 手順 2〜4 は通常どおり行い、メール本文の先頭に「※本日は株価データの取得に失敗したため、前回分の約定・評価は次回にまとめて反映します」と追記する。
- `holdings` が現在の持ち株です。

## 2. ニュース調査（Web検索）
日本時間の今朝の時点で、次を調べます。
- 前夜の米国市場（ダウ・S&P500・ナスダック、半導体指数）と主な値動きの理由
- 為替（ドル円）、日米の金利、原油
- 地政学・政策（中東、米中、日銀・FRB、関税など）
- 日本企業の決算発表・業績修正・大型材料（前日引け後〜今朝）
推測ではなく、検索で確認できた事実を根拠にしてください。日付の合わない古い記事は使わないこと。WebSearch は結果が薄いときは mode "extended" を使い、必要に応じて WebFetch で記事本文を確認してください（例：日経・ロイター・Yahoo!ファイナンス・株探のマーケットニュース）。

## 3. 銘柄選び → 注文ファイル作成
- **買い2銘柄**：`data/nikkei225.csv` にある銘柄から選ぶ。期待度を「高」「中」「低」で付ける（高＝20万円、中＝10万円、低＝5万円で購入）。持ち株と同じ銘柄でもよい。
- **売り銘柄**：持ち株の中から、下がりそうな／利益確定すべき銘柄を **min(2, 持ち株の数)** 個選ぶ（全株売却）。
- 理由は1〜2文で、根拠のニュースを具体的に書く。
- 市況の要約（summary）を3〜5行で書く。

`data/orders/<today>.json`（例：`data/orders/2026-11-10.json`）を次の形式で作成。`date` には today と同じ日付、`settled` は必ず false：
```json
{"date": "YYYY-MM-DD", "summary": "...",
 "buys": [{"code": "7203", "name": "トヨタ自動車", "confidence": "高", "reason": "..."},
          {"code": "....", "name": "...", "confidence": "中", "reason": "..."}],
 "sells": [{"code": "....", "name": "...", "reason": "..."}],
 "settled": false}
```
銘柄名は `data/nikkei225.csv` の表記に合わせてください。

## 4. 仕上げ
```bash
python -m kabu.finalize --today <today>
```
`エラー:` が出たら内容に従って注文ファイルを直し、OK が出るまで再実行します。

## 5. 保存（メールより先に行う）
```bash
git add data docs
git commit -m "朝の更新 <today>"
git push origin HEAD:main
```
push に失敗したら `git pull --rebase origin main` してから再度 push します。競合した場合は、リモート側の data/ を採用し（`git checkout --theirs` ではなく、いったん `git rebase --abort` → `git reset --hard origin/main`）、手順1からやり直してください。

## 6. メール送信
`out/email.json` の `subject` と `body` をそのまま使い、Gmail で **ryuji.ur@gmail.com** に送信します（price_error のときは手順1の注記を本文先頭に追加）。

## 失敗したとき
どこかで止まって解決できない場合も、可能な限り ryuji.ur@gmail.com に「【株予想】本日の処理でエラー」という件名で、何が起きたかを短く知らせてください。
