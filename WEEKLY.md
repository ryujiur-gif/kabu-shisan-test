# 週末のまとめメールの手順（クラウドの Claude 用・土曜の朝）

1週間の成績をまとめたメールを送ります。文面はプログラムが作ります。あなたは送るだけです（文面の手直しはしない）。

## 1. 準備
```bash
git checkout main && git pull -q origin main
python -m pip install -q jpholiday
python -c "from kabu.settle import jst_today; print(jst_today())"
```
最後に表示された日付が **today** です。

## 2. まとめができているか確かめる
`data/weekly/latest.json` を読み、`"made"` が today と同じかを確かめます。
- **同じ** → 手順3へ。
- **違う・ファイルが無い** → GitHub Actions に作成を依頼します（依頼ファイルを push すると自動で起動します）。
  ```bash
  mkdir -p data/request-weekly && echo "<today> $(date -u +%H:%M:%S)" > data/request-weekly/weekly.txt
  git add data/request-weekly && git commit -q -m "週末のまとめを依頼 <today>" && git push -q origin HEAD:main
  ```
  その後、Monitor ツールで1分おきに `git pull -q origin main` し、`data/weekly/latest.json` の `"made"` が today になるのを最大15分待ちます（通常2〜3分）。
  それでもできなければ、**`python -m kabu.weekly` を自分で実行して**（この環境では金曜の株価が取れないので、木曜までの成績になります）、本文の先頭に「※金曜分の株価を取得できなかったため、木曜までの成績です」と1行足してから送ります。
- この環境では `kabu.settle` を実行しないでください（株価サイトに接続できないため）。

## 3. メール送信
`data/weekly/latest.json` の `subject` と `body` をそのまま使い、Gmail で **ルーティンの指示文にある宛先** に送信します。

## 失敗したとき
解決できない場合も、可能な限り ルーティンの指示文にある宛先 に「【株予想】週末のまとめでエラー」という件名で、何が起きたかを短く知らせてください。
