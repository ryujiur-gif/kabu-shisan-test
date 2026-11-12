"""予想の振り返り（学習）：毎回の買い・売り・見通しの結果を集計し、成功例・失敗例と傾向を出す。

毎朝の準備（kabu.prepare → kabu.briefing.build）の中で動き、次を作る。
- data/review/review.json … 集計結果（仕上げ・メール・成績ページが読む）
- data/review/lessons.md  … 人と朝の担当が読む集計表（自動生成。手で書き換えない）
朝の担当が書くもの（プログラムは読むだけ）：
- data/review/journal.md  … 事例ごとの振り返り（成功・失敗の理由と教訓）
- data/review/playbook.md … 振り返りから作った「傾向と対策」のルール集

評価の決まり
- 買い：約定した始値を起点に、1・3・5・10・20営業日後の終値までの騰落率と、同じ期間の日経平均との差（超過）。
  主な物差しは5営業日後（買った日を1日目と数える）。5日たつ前に売った場合は売値で評価する。
- 見通し：出した朝の前営業日終値を起点に5営業日後の終値まで。上昇=+1%以上、下落=-1%以下、横ばい=±3%未満で的中。
- 売り：売った後5営業日の値動き。上がって日経平均にも勝っていれば「早売り」。
- 傾向：同じ条件の事例が MIN_N 件以上たまったものだけを「傾向」とし、それ未満は「仮説」として区別する。
"""
import json
import re
from pathlib import Path
from statistics import mean

HORIZONS = (1, 3, 5, 10, 20)
MAIN = 5
MIN_N = 5      # 「傾向」として扱う最低件数
HINT_N = 2     # 「仮説」として載せる最低件数
EDGE = 1.0     # 日経平均との差の平均がこの％以上で強み、以下で弱み

TAG_WORDS = {
    "上方修正": ("上方修正",),
    "自社株買い": ("自社株買い",),
    "増配": ("増配",),
    "割安": ("割安", "PBR0", "低PBR"),
    "押し目・反発": ("押し目", "反発", "売られすぎ"),
    "国策・テーマ": ("国策", "防衛", "AI", "半導体", "脱炭素"),
    "受注": ("受注",),
}

# 弱みとして出たときの対策（条件ごと）。無いものは汎用の文を使う。
ADVICE = {
    ("chg1d", "前日+5%以上の急騰後"): "急騰の翌朝は寄り付きが高くなりやすい。翌朝すぐには買わず、1〜2日待って押したところで買うか、期待度を1段下げる",
    ("gap", "高寄り（始値が前日終値+2%以上）"): "先物との差（寄り付きの目安）が+2%以上の日は高値づかみになりやすい。買いを1銘柄・期待度「低」までにするか翌日に回す",
    ("rsi", "RSI70以上"): "過熱ぎみの銘柄は材料が良くても買わない（RSIが60台に下がるのを待つ）",
    ("ma25", "25日線乖離+10%以上"): "25日線から離れすぎた銘柄は見送り、乖離が縮むのを待つ",
    ("ma25", "25日線の下"): "25日線の下の銘柄は「反発の確認」（前日比プラス・出来高増）が取れてから買う",
    ("event", "重要イベントの前後"): "重要イベントの前日・当日は買わない（結果が出てから買う）",
    ("mood", "リスクオフ（警戒）"): "リスクオフの日は買いを見送る（現金比率を保つ）",
    ("conf", "期待度 高"): "期待度「高」の基準を厳しくする（材料・値動き・相場環境の3つとも強いときだけ）",
    ("tag", "材料：上方修正"): "上方修正の発表翌日は織り込みが早い。発表当日の上昇率が大きいときは押し目を待つ",
    ("tag", "材料：割安"): "割安さだけを理由にしない（株価が動くきっかけになる材料があるものに絞る）",
}


def pct(base, last):
    if not base or last is None:
        return None
    return round((float(last) / float(base) - 1) * 100, 2)


def _index(bars: list[dict], d: str):
    for i, b in enumerate(bars or []):
        if b["d"] == d:
            return i
    return None


def forward(bars: list[dict], d: str, base: float, horizons=HORIZONS) -> dict:
    """d の足を1日目として、k 営業日目の終値までの騰落率（％）。まだ来ていない日は入れない。"""
    i = _index(bars, d)
    if i is None or not base:
        return {"days": 0, "ret": {}, "latest": None}
    ret = {k: pct(base, bars[i + k - 1]["c"]) for k in horizons if i + k - 1 < len(bars)}
    return {"days": len(bars) - i, "ret": ret, "latest": pct(base, bars[-1]["c"]), "asof": bars[-1]["d"]}


def _prev_close(bars, d):
    i = _index(bars, d)
    if i is None:
        prior = [b for b in bars or [] if b["d"] < d]
        return prior[-1]["c"] if prior else None
    return bars[i - 1]["c"] if i > 0 else None


def nikkei_base(nbars, d):
    """日経平均の起点（その日の始値。無ければ前日終値）。"""
    i = _index(nbars, d)
    if i is not None and nbars[i].get("o"):
        return nbars[i]["o"]
    return _prev_close(nbars, d)


def entry_features(bars, d: str, price: float) -> dict:
    """買った日の朝に見えていた指標（前営業日までの足で計算）と、寄り付きの位置。"""
    from kabu.briefing import indicators_lists
    prior = [b for b in bars or [] if b["d"] < d]
    ind = indicators_lists([b["c"] for b in prior], [b.get("v") or 0.0 for b in prior]) or {}
    prev = prior[-1]["c"] if prior else None
    return {"rsi14": ind.get("rsi14"), "ma25_dev": ind.get("ma25_dev"), "chg1d": ind.get("chg1d"),
            "chg5d": ind.get("chg5d"), "vol_ratio": ind.get("vol_ratio"),
            "cross": ind.get("cross5_25") or ind.get("cross25_75"),
            "gap_open": pct(prev, price)}


def tags_of(reason: str) -> list[str]:
    return [t for t, words in TAG_WORDS.items() if any(w in (reason or "") for w in words)]


def verdict(ret, x) -> str:
    if ret is None:
        return "評価中"
    if x is None:
        return "成功" if ret > 0 else "失敗"
    if ret > 0 and x > 0:
        return "成功"
    if ret <= 0 and x <= 0:
        return "失敗"
    return "上昇したが日経平均に届かず" if ret > 0 else "下落したが日経平均よりは良い"


def build_buys(trades, series, context=None, meta=None) -> tuple[list[dict], list[dict]]:
    """約定した買いごとの結果と、約定した売りごとの結果。
    context: {日付: {"mood":..., "imminent": bool}}、meta: {コード: {"type":..., "sector":...}}"""
    context, meta = context or {}, meta or {}
    nb = series.get("N225") or []
    buys, sells, open_lots = [], [], {}
    for t in sorted(trades, key=lambda r: r["date"]):
        if t.get("status") != "約定":
            continue
        code, d, price = t["code"], t["date"], float(t["price"])
        bars = series.get(code) or []
        if t["side"] == "買":
            f = forward(bars, d, price)
            nf = forward(nb, d, nikkei_base(nb, d))
            o = {"date": d, "code": code, "name": t["name"], "price": price, "shares": int(t["shares"]),
                 "amount": int(t["amount"]), "confidence": t.get("confidence") or "",
                 "reason": t.get("reason", ""), "tags": tags_of(t.get("reason", "")),
                 **meta.get(code, {}), **context.get(d, {}), **entry_features(bars, d, price),
                 "days": f["days"], "latest": f["latest"], "asof": f.get("asof"),
                 "latest_x": None if f["latest"] is None or nf["latest"] is None else round(f["latest"] - nf["latest"], 2),
                 "sell_date": None}
            for k in HORIZONS:
                r, n = f["ret"].get(k), nf["ret"].get(k)
                o[f"r{k}"] = r
                o[f"x{k}"] = None if r is None or n is None else round(r - n, 2)
            buys.append(o)
            open_lots.setdefault(code, []).append(o)
        else:
            lots = open_lots.pop(code, [])
            n_sell = nikkei_base(nb, d)
            for o in lots:
                o["sell_date"], o["sell_price"] = d, price
                o["realized"] = pct(o["price"], price)
                n0 = nikkei_base(nb, o["date"])
                nr = pct(n0, n_sell)
                o["realized_x"] = None if nr is None else round(o["realized"] - nr, 2)
            cost = sum(o["price"] * o["shares"] for o in lots)
            shares = sum(o["shares"] for o in lots)
            avg = cost / shares if shares else None
            f = forward(bars, d, price)
            nf = forward(nb, d, n_sell)
            a5, n5 = f["ret"].get(MAIN), nf["ret"].get(MAIN)
            after_x = None if a5 is None or n5 is None else round(a5 - n5, 2)
            sells.append({"date": d, "code": code, "name": t["name"], "price": price,
                          "shares": int(t["shares"]), "reason": t.get("reason", ""),
                          "bought": lots[0]["date"] if lots else None, "avg_cost": avg,
                          "realized": pct(avg, price),
                          "realized_yen": int((price - avg) * shares) if avg else None,
                          "after5": a5, "after5_x": after_x, "after_latest": f["latest"],
                          "judge": "評価中" if a5 is None else
                          ("早売り（売った後に上昇）" if a5 > 2 and (after_x or 0) > 0 else "売って正解・妥当")})
    for o in buys:
        o["ret"], o["x"], o["basis"] = metric(o)
        o["verdict"] = verdict(o["ret"], o["x"])
    return buys, sells


def metric(o) -> tuple:
    """成績に数える値：売却済みなら売値、そうでなければ5営業日後。どちらも無ければ評価中。"""
    if o.get("sell_date"):
        return o.get("realized"), o.get("realized_x"), "売却"
    if o.get(f"r{MAIN}") is not None:
        return o[f"r{MAIN}"], o.get(f"x{MAIN}"), f"{MAIN}日後"
    return None, None, "評価中"


def build_outlooks(orders: dict, series) -> list[dict]:
    """毎朝の持ち株の見通し（上昇/横ばい/下落）と、その後5営業日の実際。"""
    out = []
    for d in sorted(orders):
        for h in orders[d].get("holds") or []:
            bars = series.get(h.get("code")) or []
            base = _prev_close(bars, d)
            f = forward(bars, d, base)
            r5, r1 = f["ret"].get(MAIN), f["ret"].get(1)
            hit = None
            if r5 is not None:
                hit = {"上昇": r5 >= 1.0, "下落": r5 <= -1.0, "横ばい": abs(r5) < 3.0}.get(h.get("outlook"))
            out.append({"date": d, "code": h.get("code"), "name": h.get("name", ""),
                        "outlook": h.get("outlook"), "r1": r1, "r5": r5, "hit": hit})
    return out


def stats(items: list[dict]) -> dict:
    rs = [o["ret"] for o in items if o.get("ret") is not None]
    xs = [o["x"] for o in items if o.get("x") is not None]
    if not rs:
        return {"n": 0}
    return {"n": len(rs), "win": round(sum(r > 0 for r in rs) / len(rs) * 100),
            "beat": round(sum(x > 0 for x in xs) / len(xs) * 100) if xs else None,
            "avg_ret": round(mean(rs), 2), "avg_x": round(mean(xs), 2) if xs else None}


def _band(v, cuts):
    """cuts: [(上限, ラベル), ...] 上限未満ならそのラベル。最後は (None, ラベル)。"""
    if v is None:
        return None
    for hi, label in cuts:
        if hi is None or v < hi:
            return label
    return None


GROUPS = [
    ("conf", "期待度", lambda o: f"期待度 {o['confidence']}" if o.get("confidence") else None),
    ("type", "ビジネスモデルの型", lambda o: o.get("type")),
    ("mood", "相場環境", lambda o: o.get("mood")),
    ("event", "重要イベント", lambda o: None if o.get("imminent") is None else
     ("重要イベントの前後" if o["imminent"] else "重要イベントなし")),
    ("chg1d", "前日の値動き", lambda o: _band(o.get("chg1d"), [(0, "前日マイナス（押し目）"), (5, "前日プラス（+5%未満）"), (None, "前日+5%以上の急騰後")])),
    ("gap", "寄り付きの位置", lambda o: _band(o.get("gap_open"), [(2, "通常の寄り付き"), (None, "高寄り（始値が前日終値+2%以上）")])),
    ("rsi", "RSI", lambda o: _band(o.get("rsi14"), [(50, "RSI50未満"), (70, "RSI50〜70"), (None, "RSI70以上")])),
    ("ma25", "25日線乖離", lambda o: _band(o.get("ma25_dev"), [(0, "25日線の下"), (10, "25日線の上（+10%未満）"), (None, "25日線乖離+10%以上")])),
    ("vol", "出来高", lambda o: _band(o.get("vol_ratio"), [(2, "出来高ふつう"), (None, "出来高2倍以上")])),
    ("tag", "材料", lambda o: [f"材料：{t}" for t in o.get("tags") or []] or ["材料：タグなし"]),
    ("sector", "業種", lambda o: o.get("sector")),
]


def group_stats(items: list[dict]) -> dict:
    """条件別の成績。評価の済んだ買いだけを数える。"""
    done = [o for o in items if o.get("ret") is not None]
    out = {}
    for gid, glabel, fn in GROUPS:
        buckets = {}
        for o in done:
            v = fn(o)
            for b in (v if isinstance(v, list) else [v]):
                if b:
                    buckets.setdefault(b, []).append(o)
        out[gid] = {"label": glabel, "buckets": {}}
        for b, xs in buckets.items():
            rest = stats([o for o in done if all(o is not y for y in xs)])
            out[gid]["buckets"][b] = {**stats(xs), "rest_n": rest["n"], "rest_avg": _edge(rest)}
    return out


def _edge(s: dict):
    """成績の物差し：日経平均との差の平均（無ければ騰落率の平均）。"""
    if not s.get("n"):
        return None
    return s["avg_x"] if s.get("avg_x") is not None else s["avg_ret"]


def find_patterns(groups: dict) -> list[dict]:
    """条件別の成績から、強み・弱みを拾う。件数が MIN_N 未満は「仮説」。
    その条件の成績そのものが悪い（良い）ことに加え、**その条件に当てはまらない他の事例より** EDGE 以上
    悪い（良い）ものだけを拾う。全部の事例に共通する条件は、相場全体の結果と区別できないので拾わない。"""
    out = []
    for gid, g in groups.items():
        for b, s in g["buckets"].items():
            if s["n"] < HINT_N or not s.get("rest_n") or b == "材料：タグなし":
                continue
            edge, diff = _edge(s), _edge(s) - s["rest_avg"]
            kind = "弱み" if edge <= -EDGE and diff <= -EDGE else "強み" if edge >= EDGE and diff >= EDGE else None
            if not kind:
                continue
            advice = ADVICE.get((gid, b)) if kind == "弱み" else None
            advice = advice or ("この条件の買いは見送るか、期待度を1段下げる" if kind == "弱み"
                                else "この条件は続けてよい（件数が増えても成績が保たれるか確認する）")
            out.append({"gid": gid, "bucket": b, "kind": kind,
                        "level": "傾向" if s["n"] >= MIN_N else "仮説", **s, "advice": advice})
    out.sort(key=lambda p: (p["level"] != "傾向", p["kind"] != "弱み", -(p["n"])))
    return out


def matching_patterns(features: dict, patterns: list[dict], kind="弱み") -> list[dict]:
    """今日の買い候補（features）が当てはまる過去の弱みパターン。"""
    hits = []
    for p in patterns or []:
        if p["kind"] != kind:
            continue
        fn = next((f for gid, _, f in GROUPS if gid == p["gid"]), None)
        v = fn(features) if fn else None
        if p["bucket"] in (v if isinstance(v, list) else [v]):
            hits.append(p)
    return hits


def outlook_stats(outlooks: list[dict]) -> dict:
    out = {}
    for kind in ("上昇", "横ばい", "下落"):
        xs = [o for o in outlooks if o["outlook"] == kind and o["hit"] is not None]
        if xs:
            out[kind] = {"n": len(xs), "hit": round(sum(o["hit"] for o in xs) / len(xs) * 100),
                         "avg_r5": round(mean(o["r5"] for o in xs), 2)}
    done = [o for o in outlooks if o["hit"] is not None]
    if done:
        out["全体"] = {"n": len(done), "hit": round(sum(o["hit"] for o in done) / len(done) * 100),
                     "avg_r5": round(mean(o["r5"] for o in done), 2)}
    return out


def attribution(hist: list[dict], context: dict | None = None, start_cash: int = 1_000_000) -> dict | None:
    """日経平均との差を「現金で持っていた分」と「銘柄選びの分」に分ける（日ごとの近似を足し上げる）。
    現金の分 = −（前日の現金比率 × その日の日経平均の騰落率）。残りが銘柄選びの分。"""
    from kabu.briefing import cash_target
    rows = sorted(hist, key=lambda r: r["date"])
    if not rows:
        return None
    cash_part = sel_part = 0.0
    ratios, over = [], 0
    prev_total, prev_bench, prev_w = start_cash, start_cash, None
    for r in rows:
        total, bench, cash = int(r["total"]), int(r["benchmark_value"]), int(r["cash"])
        w_today = cash / total if total else 0.0
        w = w_today if prev_w is None else prev_w
        rp, rn = total / prev_total - 1, bench / prev_bench - 1
        c = -w * rn
        cash_part += c
        sel_part += (rp - rn) - c
        ratios.append(w_today)
        mood = (context or {}).get(r["date"], {}).get("mood") or ""
        if w_today > cash_target(mood)[1]:
            over += 1
        prev_total, prev_bench, prev_w = total, bench, w_today
    last = rows[-1]
    mine, bench = int(last["total"]) / start_cash - 1, int(last["benchmark_value"]) / start_cash - 1
    return {"asof": last["date"], "days": len(rows), "mine": round(mine * 100, 2), "bench": round(bench * 100, 2),
            "diff": round((mine - bench) * 100, 2), "cash_part": round(cash_part * 100, 2),
            "selection_part": round(sel_part * 100, 2), "avg_cash_ratio": round(mean(ratios) * 100),
            "days_cash_over": over}


def portfolio_lines(pf: dict | None) -> list[str]:
    if not pf:
        return []
    L = [f"- 資産全体（{pf['asof']} まで {pf['days']}営業日）：予想どおり売買 {_p(pf['mine'])}／日経平均 {_p(pf['bench'])}"
         f" → 差 {_pt(pf['diff'])}",
         f"- 差の内訳（概算）：現金で持っていた分 {_pt(pf['cash_part'])}／銘柄選びの分 {_pt(pf['selection_part'])}"
         f"（現金比率の平均 {pf['avg_cash_ratio']}%、目安の上限を超えていた日 {pf['days_cash_over']}/{pf['days']}日）"]
    if pf["days"] >= 3 and pf["cash_part"] <= -1.0 and pf["days_cash_over"] * 2 > pf["days"]:
        L.append("- 【対策】日経平均に負けている主因は現金の持ちすぎ。現金比率が目安の上限を超えている間は、"
                 "基準を満たす銘柄を見送らず、期待度どおりの額で買って目安の範囲に近づける（イベント当日を除く）")
    elif pf["days"] >= 3 and pf["cash_part"] >= 1.0:
        L.append("- 現金を多めに持っていたことが下落局面で成績を守っている（現金比率の目安は今のままでよい）")
    if pf["days"] >= 5 and pf["selection_part"] <= -1.0:
        L.append("- 【対策】銘柄選びの分がマイナス。下の「傾向と対策」の弱みの条件を避けることを優先する")
    return L


def _pt(x) -> str:
    return "-" if x is None else f"{'+' if x >= 0 else ''}{x:.2f}ポイント"


def case_key(kind: str, o: dict) -> str:
    """振り返り（journal.md）の見出しに使う決まった書き出し。"""
    if kind == "sell":
        return f"## {o['date']} 売 {o['code']}"
    return f"## {o['date']} 買 {o['code']}"


def cases_due(buys, sells, journal_text: str) -> list[dict]:
    """結果が出たのに、まだ振り返りが書かれていない事例（古い順）。"""
    due = []
    for o in buys:
        if o["sell_date"] is None and o.get(f"r{MAIN}") is not None:
            due.append({"key": case_key("buy", o), "when": o["date"], "title":
                        f"{o['name']}（{o['code']}）{o['date']} 買い → {MAIN}営業日後 {_p(o['ret'])}（日経平均との差 {_p(o['x'])}）：{o['verdict']}"})
    for s in sells:
        due.append({"key": case_key("sell", s), "when": s["date"], "title":
                    f"{s['name']}（{s['code']}）{s['bought'] or '-'} 買い → {s['date']} 売り {_p(s['realized'])}（{_y(s['realized_yen'])}）"})
    due.sort(key=lambda c: c["when"])
    return [c for c in due if not re.search(r"^" + re.escape(c["key"]) + r"\b", journal_text or "", re.M)]


def _p(x) -> str:
    return "-" if x is None else f"{'+' if x >= 0 else ''}{x:.2f}%"


def _y(x) -> str:
    return "-" if x is None else f"{'+' if x >= 0 else '-'}{abs(int(x)):,}円"


def build_review(today: str, trades, orders, series, context=None, meta=None, journal_text="",
                 hist=None) -> dict:
    conf = {(d, b.get("code")): b.get("confidence") for d, o in orders.items() for b in o.get("buys") or []}
    trades = [{**t, "confidence": conf.get((t["date"], t["code"]), "")} for t in trades]
    buys, sells = build_buys(trades, series, context, meta)
    outlooks = build_outlooks(orders, series)
    groups = group_stats(buys)
    nb = series.get("N225") or []
    return {"today": today, "asof": nb[-1]["d"] if nb else None,
            "portfolio": attribution(hist or [], context),
            "overall": stats(buys), "n_buys": len(buys),
            "n_pending": sum(o["ret"] is None for o in buys),
            "buys": buys, "sells": sells,
            "outlook_stats": outlook_stats(outlooks),
            "outlook_misses": [o for o in outlooks if o["hit"] is False][-10:],
            "groups": groups, "patterns": find_patterns(groups),
            "cases_due": cases_due(buys, sells, journal_text)}


def _stat_cells(s: dict) -> str:
    if not s.get("n"):
        return "0 | - | - | - | -"
    beat = "-" if s.get("beat") is None else f"{s['beat']}%"
    return f"{s['n']} | {s['win']}% | {beat} | {_p(s['avg_ret'])} | {_p(s.get('avg_x'))}"


def pattern_lines(patterns: list[dict]) -> list[str]:
    L = []
    for p in patterns:
        beat = "" if p.get("beat") is None else f"・日経平均超え{p['beat']}%"
        L.append(f"- 【{p['level']}・{p['kind']}】{p['bucket']}：{p['n']}件・上昇した割合{p['win']}%{beat}・"
                 f"平均{_p(p['avg_ret'])}（日経平均との差{_p(p.get('avg_x'))}）→ **対策：{p['advice']}**")
    return L


def buy_table(buys: list[dict]) -> list[str]:
    L = ["| 買った日 | 銘柄 | 期待度 | 買値 | 1日後 | 3日後 | 5日後 | 直近 | 日経平均との差 | 判定 | 買う前日の状態 |",
         "|---|---|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for o in buys:
        if o["sell_date"]:
            x, last = o.get("realized_x"), f"{_p(o.get('realized'))}（{o['sell_date'][5:]}売却）"
        else:
            x = o.get(f"x{MAIN}") if o.get(f"r{MAIN}") is not None else o.get("latest_x")
            last = f"{_p(o.get('latest'))}（{o['days']}日目）"
        cond = "・".join(s for s in (
            None if o.get("chg1d") is None else f"前日{_p(o['chg1d'])}",
            None if o.get("gap_open") is None else f"寄り{_p(o['gap_open'])}",
            None if o.get("rsi14") is None else f"RSI{o['rsi14']:.0f}",
            None if o.get("ma25_dev") is None else f"25日線{_p(o['ma25_dev'])}") if s)
        L.append(f"| {o['date'][5:]} | {o['name']}({o['code']}) | {o['confidence'] or '-'} | {o['price']:,.1f} | "
                 f"{_p(o.get('r1'))} | {_p(o.get('r3'))} | {_p(o.get('r5'))} | {last} | {_p(x)} | "
                 f"{o['verdict'] if o['ret'] is not None else '評価中'} | {cond or '-'} |")
    return L


def render_lessons(rv: dict) -> str:
    L = ["# 予想の振り返り（自動集計）", "",
         f"{rv['today']} 朝に作成（株価は {rv.get('asof') or '-'} 終値まで）。このファイルはプログラムが毎朝作り直します。手で書き換えないでください。",
         "事例ごとの振り返りは journal.md、そこから決めたルールは playbook.md にあります。", "",
         "## 0. 資産全体（日経平均との比較）", ""]
    L += portfolio_lines(rv.get("portfolio")) or ["（記録がたまると表示されます）"]
    L += ["", "## 1. 買い予想の成績", ""]
    s = rv["overall"]
    if s.get("n"):
        beat = "-" if s.get("beat") is None else f"{s['beat']}%"
        L.append(f"- 評価済み {s['n']}件：上昇した割合 {s['win']}%／日経平均を上回った割合 {beat}／"
                 f"平均 {_p(s['avg_ret'])}（日経平均との差 {_p(s.get('avg_x'))}）")
    else:
        L.append("- 評価済みの買いはまだありません（買ってから5営業日たつか、売ると評価されます）。")
    L += [f"- 評価中 {rv['n_pending']}件（下の表の「直近」は途中経過）", "",
          "評価の物差し：買った日の始値から5営業日後の終値まで（その前に売ったら売値）。"
          "「成功」＝上昇し日経平均にも勝った／「失敗」＝下落し日経平均にも負けた。", ""]
    L += buy_table(rv["buys"]) if rv["buys"] else ["（買いの約定はまだありません）"]
    L += ["", "## 2. 売りの結果", ""]
    if rv["sells"]:
        L += ["| 売った日 | 銘柄 | 買った日 | 損益率 | 損益額 | 売った後5日 | 判定 |", "|---|---|---|---:|---:|---:|---|"]
        L += [f"| {s['date'][5:]} | {s['name']}({s['code']}) | {(s['bought'] or '-')[5:]} | {_p(s['realized'])} | "
              f"{_y(s['realized_yen'])} | {_p(s['after5'])} | {s['judge']} |" for s in rv["sells"]]
    else:
        L.append("（売りの約定はまだありません）")
    L += ["", "## 3. 持ち株の見通しの的中", "",
          "的中の決まり：5営業日後に 上昇=+1%以上／下落=-1%以下／横ばい=±3%未満。", ""]
    if rv["outlook_stats"]:
        L += ["| 見通し | 件数 | 的中率 | 5日後の平均 |", "|---|---:|---:|---:|"]
        L += [f"| {k} | {v['n']} | {v['hit']}% | {_p(v['avg_r5'])} |" for k, v in rv["outlook_stats"].items()]
        if rv["outlook_misses"]:
            L += ["", "最近の外れ："]
            L += [f"- {o['date'][5:]} {o['name']}({o['code']}) 見通し「{o['outlook']}」→ 5日後 {_p(o['r5'])}"
                  for o in rv["outlook_misses"]]
    else:
        L.append("（5営業日たった見通しはまだありません）")
    L += ["", "## 4. 条件別の成績（評価済みの買いのみ）", "",
          f"同じ条件が {MIN_N}件以上たまるまでは参考程度に見てください。", ""]
    any_rows = False
    for g in rv["groups"].values():
        if not g["buckets"]:
            continue
        any_rows = True
        L += [f"### {g['label']}", "", "| 条件 | 件数 | 上昇した割合 | 日経平均超え | 平均 | 日経平均との差 |",
              "|---|---:|---:|---:|---:|---:|"]
        L += [f"| {b} | {_stat_cells(s)} |" for b, s in sorted(g["buckets"].items(), key=lambda x: -x[1]["n"])]
        L.append("")
    if not any_rows:
        L += ["（評価済みの買いがたまると表示されます）", ""]
    L += ["## 5. 傾向と対策（自動抽出）", ""]
    L += pattern_lines(rv["patterns"]) or ["（強み・弱みと言える差はまだ出ていません）"]
    L += ["", "## 6. 振り返りを書く事例（journal.md に未記入）", ""]
    L += [f"- `{c['key']}` … {c['title']}" for c in rv["cases_due"]] or ["（ありません）"]
    return "\n".join(L) + "\n"


def briefing_lines(rv: dict, playbook_text: str = "") -> list[str]:
    """朝の資料の先頭に載せる要約。"""
    L = ["## 0. これまでの予想の振り返り（学習）— 銘柄を選ぶ前に必ず読む", ""]
    L += portfolio_lines(rv.get("portfolio"))
    s = rv["overall"]
    if s.get("n"):
        beat = "-" if s.get("beat") is None else f"{s['beat']}%"
        L.append(f"- 買い予想の成績（評価済み {s['n']}件）：上昇した割合 {s['win']}%／日経平均超え {beat}／"
                 f"平均 {_p(s['avg_ret'])}（日経平均との差 {_p(s.get('avg_x'))}）")
    else:
        L.append("- 評価済みの買いはまだありません（5営業日後に評価）。下は途中経過です。")
    if rv.get("outlook_stats", {}).get("全体"):
        o = rv["outlook_stats"]
        L.append("- 見通しの的中率：" + "／".join(f"{k} {v['hit']}%（{v['n']}件）" for k, v in o.items()))
    if rv["buys"]:
        L += ["", "### 買い予想の結果（成功例・失敗例）", ""] + buy_table(rv["buys"][-15:])
    if rv["sells"]:
        L += ["", "### 売りの結果", ""]
        L += [f"- {s['date'][5:]} {s['name']}({s['code']})：損益 {_p(s['realized'])}・売った後5日 {_p(s['after5'])} → {s['judge']}"
              for s in rv["sells"][-8:]]
    L += ["", "### 傾向と対策（自動抽出。「傾向」は5件以上、「仮説」はそれ未満）", ""]
    L += pattern_lines(rv["patterns"][:12]) or ["- まだ差が出ていません。"]
    if playbook_text.strip():
        L += ["", "### ルール集（data/review/playbook.md の写し）", ""] + playbook_text.strip().splitlines()[:80]
    if rv["cases_due"]:
        L += ["", "### 今朝、振り返りを書く事例（手順2.5。古い順に最大3件）", ""]
        L += [f"- `{c['key']}` … {c['title']}" for c in rv["cases_due"][:3]]
    L += ["", "→ 弱みの条件に当てはまる買いは、対策に従う（見送る・期待度を下げる・待つ）。"
          "従わないときは理由を注文ファイルの `learned` に書くこと。", ""]
    return L


def email_lines(rv: dict | None) -> list[str]:
    if not rv or not rv.get("n_buys"):
        return []
    L = ["", "■ 予想の振り返り"]
    pf = rv.get("portfolio")
    if pf:
        L.append(f"日経平均との差 {_pt(pf['diff'])}（内訳の概算：現金で持っていた分 {_pt(pf['cash_part'])}・"
                 f"銘柄選びの分 {_pt(pf['selection_part'])}）")
    s = rv["overall"]
    if s.get("n"):
        beat = "" if s.get("beat") is None else f"・日経平均超え {s['beat']}%"
        L.append(f"買い予想（評価済み{s['n']}件）：上昇した割合 {s['win']}%{beat}・平均 {_p(s['avg_ret'])}"
                 f"（日経平均との差 {_p(s.get('avg_x'))}）")
    if rv.get("n_pending"):
        L.append(f"評価中：{rv['n_pending']}件（買ってから5営業日後に評価）")
    o = rv.get("outlook_stats", {}).get("全体")
    if o:
        L.append(f"持ち株の見通しの的中率：{o['hit']}%（{o['n']}件）")
    for p in [p for p in rv.get("patterns", []) if p["level"] == "傾向"][:3]:
        L.append(f"・{p['kind']}：{p['bucket']}（{p['n']}件・日経平均との差 {_p(p.get('avg_x'))}）")
    return L


def load_orders(data: Path) -> dict:
    out = {}
    for f in sorted((Path(data) / "orders").glob("*.json")):
        try:
            o = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if isinstance(o, dict):
            out[o.get("date") or f.stem] = o
    return out


def load_context(data: Path) -> dict:
    """日付ごとの相場環境（朝の資料の主要指標から判定）と、重要イベントの有無。"""
    from kabu.business_types import market_regime
    out = {}
    for f in sorted((Path(data) / "daily").glob("*/briefing.json")):
        try:
            b = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        imm = b.get("imminent")
        out[f.parent.name] = {"mood": market_regime(b.get("market") or []).get("mood"),
                              "imminent": None if imm is None else bool(imm)}
    return out


def read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def update(root: Path, today: str, series: dict, context_today: dict | None = None) -> dict:
    """集計して data/review/review.json と lessons.md を書く。戻り値は集計結果。"""
    import csv
    from kabu.business_types import TYPE_LABELS, classify
    from kabu.settle import read_rows
    data = Path(root) / "data"
    rd = data / "review"
    rd.mkdir(parents=True, exist_ok=True)
    with open(data / "nikkei225.csv", encoding="utf-8") as fh:
        sectors = {r["code"]: r.get("sector", "") for r in csv.DictReader(fh)}
    meta = {}
    for c, sec in sectors.items():
        t = classify(c, sec)
        meta[c] = {"sector": sec, "type": f"{t}{TYPE_LABELS[t]}"}
    context = load_context(data)
    if context_today:
        context[today] = context_today
    rv = build_review(today, read_rows(data / "trades.csv"), load_orders(data), series,
                      context=context, meta=meta, journal_text=read_text(rd / "journal.md"),
                      hist=read_rows(data / "history.csv"))
    (rd / "review.json").write_text(json.dumps(rv, ensure_ascii=False, indent=1), encoding="utf-8")
    (rd / "lessons.md").write_text(render_lessons(rv), encoding="utf-8")
    return rv
