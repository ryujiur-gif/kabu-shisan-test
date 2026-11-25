# 週1回の点検・振り返り・研究の手順（クラウドの Claude 用・日曜の朝）

目的：**負けない仕組み**に近づけること。1週間の売買を振り返り、日経225全銘柄・過去2年の大量データ（研究レポート）と照らして、
ルール集（data/review/playbook.md）のどの決まりが本当に効いているかを確かめ、効かない決まりは外し、効く決まりを残す。
プログラム（kabu/）・手順書（ROUTINE.md）・記録（state.json・trades.csv・history.csv）は書き換えない。変えたほうがよいことは「竜司さんへの提案」に書く。

## 1. 準備
```bash
git checkout main && git pull -q origin main
python -m pip install -q jpholiday
python -c "from kabu.settle import jst_today; print(jst_today())"
```
表示された日付が **today**。

## 2. 研究レポートと自己テストがそろっているか
`data/research/latest.json` の `"made"` が today と同じかを確かめる。
- 違う・無い → GitHub Actions に依頼する（push で起動。通常5〜10分）。
  ```bash
  mkdir -p data/request-research && echo "<today> $(date -u +%H:%M:%S)" > data/request-research/research.txt
  git add data/request-research && git commit -q -m "研究を依頼 <today>" && git push -q origin HEAD:main
  ```
  Monitor ツールで1分おきに `git pull -q origin main` し、最大20分待つ。できなければ前回のレポートで進め、メールにその旨を書く。
- この環境では `kabu.research`・`kabu.settle`・`kabu.prepare` を実行しない（株価サイトに接続できないため）。

## 3. システムの点検
次を読み、問題を一覧にする（直すのは竜司さんとの会話で行うので、ここでは見つけて書くだけ）。
1. `data/research/selftest.txt`：テストが全部通っているか（`failed` が無いか）、データの点検で問題が出ていないか。
2. 直近1週間の `data/daily/<日付>/settle.json` の `status`（`price_error` が無いか）と `briefing.json` の `missing`・`health`。
3. `data/orders/` に、営業日なのに予想が無い日が無いか（`python -m kabu.watchdog --today <日付>` で確かめられる）。
4. `data/weekly/latest.json` が今週の土曜に作られているか。
5. メール・成績ページの数字と記録（history.csv）が食い違っていないか（気づいた範囲で）。

## 4. 振り返り（1週間の売買）
`data/review/lessons.md`（自動集計）・`data/review/journal.md`（事例ごとの振り返り）・今週の `data/orders/*.json` を読み、次をまとめる。
- **成功した点**：うまくいった判断と、その理由（偶然か、決まりどおりか）。
- **反省点**：損をした判断と、その原因。売りの判断（損切り・早売り）も含める。
- 日経平均との差の内訳（現金で持っていた分／銘柄選びの分）がどう変わったか。

## 5. 研究と照らして、ルール集を見直す（いちばん大事）
`data/research/latest.md` を読む。物差しは「同じ日に買えた他の銘柄との差」（銘柄選びの差）と「相場全体のタイミング」（日単位）。
playbook.md の **有効なルール1つずつ** に、次のどれかを書き添える（ルールの末尾に【研究：…】の形で）。
- **【研究：支持】**：大量データでも同じ向きの差がはっきり出た（判定が「有利」「不利」）。
- **【研究：差なし】**：大量データでは差が出ない。少ない事例からの思い込みの可能性が高い。→ 事例が5件たまっても成績が良くならなければ「廃止したルール」へ移す。
- **【研究：反対】**：大量データでは逆の向き。→ 「廃止したルール」へ移し、理由を書く。
- **【研究：検証できず】**：ニュースや業種の事情など、株価だけでは調べられない。→ 事例を集め続ける。
有効なルールは12個まで。「研究：支持」のものを優先して残す。最終見直しの日付と、何を変えたかを先頭に書く。

## 6. 研究ノート
`data/research/notes-<today>.md` に次を書く（1〜2ページ）。
1. 今週の点検結果（問題なし／見つかった問題）
2. 今週の成功点・反省点（具体的な銘柄と数字）
3. 研究レポートから分かったこと（先週から判定が変わったものは必ず書く）
4. ルール集で変えたこと
5. **負けないための提案**（手順書の基準や仕組みの変更が必要なもの。根拠の数字つき）→ playbook.md の「竜司さんへの提案」にも写す
6. 来週、朝の担当が気をつけること（3つまで）

## 7. 保存とメール
```bash
git add data/review/playbook.md data/research
git commit -m "週1回の点検・振り返り・研究 <today>"
git push origin HEAD:main
```
push に失敗したら `git pull --rebase origin main` してから再度 push。
メールは Gmail で **ルーティンの指示文にある宛先** に送る。件名「【株予想・研究】<月/日> 点検：<問題なし／問題◯件>・<今週の一言>」。
本文は研究ノートの1〜6を短くしたもの（1,500字以内）と、成績ページのURL（config.json の site_url）。

## 失敗したとき
解決できない場合も、可能な限り「【株予想】週1回の点検でエラー」という件名で、何が起きたかを短く知らせる。
