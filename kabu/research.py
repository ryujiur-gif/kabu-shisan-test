"""研究：売買の決まりを、日経225の全銘柄・過去2年の株価で検証する（週1回、GitHub Actions で実行）。

使い方: python -m kabu.research [--period 2y] [--root .]
結果は data/research/<日付>.md・latest.md・latest.json に保存する。

物差しは本体の振り返りと同じ「その日の始値で買い、5営業日後の終値で評価」。日経平均の同じ期間の騰落を引いた
「日経平均との差（超過リターン）」で比べる。重なり合う期間を数えるので件数ほど独立ではない（t値は目安）。
ここで「有意」としたものだけを、ルール集・手順書の変更の根拠にする。
"""
import argparse
import json
import math
from datetime import date
from pathlib import Path

HOLD = 5            # 評価する営業日数（買った日を含む）
MIN_N = 200         # 結論に使う最少件数
T_SIG = 3.0         # 「はっきりした差」とみなす t 値（重なりを考えて厳しめ）


# ---------------- データ ----------------

def _arrays(df):
    if df is None or len(df) == 0:
        return None
    d = df.dropna(subset=["Open", "Close"])
    d = d[(d["Open"] > 0) & (d["Close"] > 0)]
    if len(d) < 100:
        return None
    return {"d": [x.strftime("%Y-%m-%d") for x in d.index], "o": [float(x) for x in d["Open"]],
            "c": [float(x) for x in d["Close"]], "v": [float(x) if x == x else 0.0 for x in d["Volume"]]}


def load_prices(codes: list[str], period: str = "2y") -> tuple[dict, dict]:
    """全銘柄と日経平均の日足（分割・配当で調整済み）。"""
    import yfinance as yf
    tickers = [f"{c}.T" for c in codes] + ["^N225"]
    raw = yf.download(tickers, period=period, group_by="ticker", auto_adjust=True, progress=False, threads=True)
    out = {}
    for c in codes:
        try:
            a = _arrays(raw[f"{c}.T"])
        except KeyError:
            a = None
        if a:
            out[c] = a
    return out, _arrays(raw["^N225"])


# ---------------- 指標 ----------------

def _ma(c, i, n):
    return sum(c[i - n + 1:i + 1]) / n


def _rsi(c, i, n=14):
    diffs = [c[k] - c[k - 1] for k in range(i - n + 1, i + 1)]
    g = sum(x for x in diffs if x > 0) / n
    l_ = sum(-x for x in diffs if x < 0) / n
    return 100.0 if l_ == 0 else 100 - 100 / (1 + g / l_)


def events(stocks: dict, nk: dict, hold: int = HOLD) -> list[dict]:
    """銘柄×日 ごとに「その日の始値で買ったら」の結果と、買う前日の状態を作る。"""
    nidx = {d: i for i, d in enumerate(nk["d"])}
    no, nc = nk["o"], nk["c"]
    out = []
    for code, s in stocks.items():
        o, c, v, ds = s["o"], s["c"], s["v"], s["d"]
        for t in range(80, len(c) - hold):
            j0, j1 = nidx.get(ds[t]), nidx.get(ds[t + hold - 1])
            if j0 is None or j1 is None or j0 < 30:
                continue
            p = t - 1
            ret = c[t + hold - 1] / o[t] - 1
            nret = nc[j1] / no[j0] - 1
            avgv = sum(v[p - 20:p]) / 20
            jp = j0 - 1
            out.append({
                "code": code, "date": ds[t], "ret": ret * 100, "x": (ret - nret) * 100,
                "gap": (o[t] / c[p] - 1) * 100, "prev": (c[p] / c[p - 1] - 1) * 100,
                "ma25": (c[p] / _ma(c, p, 25) - 1) * 100, "ma75": (c[p] / _ma(c, p, 75) - 1) * 100,
                "slope25": (_ma(c, p, 25) / _ma(c, p - 5, 25) - 1) * 100,
                "rsi": _rsi(c, p), "volr": v[p] / avgv if avgv else None,
                "r20": (c[p] / c[p - 20] - 1) * 100,
                "n_ma25": (nc[jp] / _ma(nc, jp, 25) - 1) * 100, "n_r5": (nc[jp] / nc[jp - 5] - 1) * 100,
                "n_gap": (no[j0] / nc[jp] - 1) * 100,
            })
    # 同じ日に買えた全銘柄の平均との差（その日の相場全体の上げ下げを取り除いた「銘柄選びの差」）
    day = {}
    for r in out:
        day.setdefault(r["date"], []).append(r["ret"])
    avg = {d: sum(v) / len(v) for d, v in day.items()}
    for r in out:
        r["rel"] = r["ret"] - avg[r["date"]]
    return out


# ---------------- 集計 ----------------

MIN_DAYS = 30      # 結論に使う最少の日数（同じ日の銘柄はまとめて動くので、日数で数える）


def stats(rows: list[dict], key: str = "rel") -> dict | None:
    """平均・中央値・勝率は件数で、t値は「日ごとの平均」で計算する（同じ日の銘柄は一緒に動くため）。
    既定の物差し rel は「同じ日に買えた全銘柄の平均との差」。"""
    xs = [r[key] for r in rows if r.get(key) is not None]
    n = len(xs)
    if n < 2:
        return None
    m = sum(xs) / n
    s = sorted(xs)
    by_day = {}
    for r in rows:
        if r.get(key) is not None:
            by_day.setdefault(r.get("date"), []).append(r[key])
    dm = [sum(v) / len(v) for v in by_day.values()]
    k = len(dm)
    t = 0.0
    if k >= 2:
        mm = sum(dm) / k
        sd = math.sqrt(sum((x - mm) ** 2 for x in dm) / (k - 1))
        t = mm / (sd / math.sqrt(k)) if sd else 0.0
    return {"n": n, "days": k, "mean": round(m, 2), "median": round(s[n // 2], 2),
            "win": round(sum(1 for x in xs if x > 0) / n * 100, 1),
            "ret": round(sum(r["ret"] for r in rows) / n, 2), "t": round(t, 1)}


def verdict(s: dict | None, base: dict | None) -> str:
    if not s or s["n"] < MIN_N or s.get("days", 0) < MIN_DAYS:
        return "件数不足"
    d = s["mean"] - (base["mean"] if base else 0)
    if abs(s["t"]) >= T_SIG and abs(d) >= 0.3:
        return "有利" if d > 0 else "不利"
    return "差なし"


def table(title: str, groups: list[tuple[str, callable]], rows: list[dict], base: dict) -> tuple[list[str], list[dict]]:
    L = [f"### {title}", "", "| 条件 | 件数（日数） | 他の銘柄との差（平均） | 中央値 | 他の銘柄に勝った割合 | 騰落（平均） | 日経平均との差 | t値 | 判定 |",
         "|---|---:|---:|---:|---:|---:|---:|---:|---|"]
    found = []
    for label, f in groups:
        sub = [r for r in rows if f(r)]
        s = stats(sub)
        if not s:
            L.append(f"| {label} | {len(sub)} | - | - | - | - | - | - | 件数不足 |")
            continue
        v = verdict(s, base)
        xn = stats(sub, key="x")
        L.append(f"| {label} | {s['n']:,}（{s['days']}日） | {s['mean']:+.2f}% | {s['median']:+.2f}% | {s['win']:.0f}% | "
                 f"{s['ret']:+.2f}% | {xn['mean']:+.2f}% | {s['t']:+.1f} | {v} |")
        found.append({"section": title, "label": label, **s, "x": xn["mean"], "verdict": v})
    return L + [""], found


def stop_loss_study(stocks: dict, nk: dict, horizon: int = 20, stops=(None, -5, -8, -10, -15)) -> list[dict]:
    """始値で買って最長 horizon 日持つ。終値が取得価格から stop% 以下になったら翌日の始値で売る。"""
    nidx = {d: i for i, d in enumerate(nk["d"])}
    res = {s: [] for s in stops}
    for code, s in stocks.items():
        o, c, ds = s["o"], s["c"], s["d"]
        for t in range(80, len(c) - horizon - 1, 5):     # 5日おきに入って重なりを減らす
            j0 = nidx.get(ds[t])
            if j0 is None:
                continue
            entry = o[t]
            for st in stops:
                exit_i, price = t + horizon - 1, c[t + horizon - 1]
                if st is not None:
                    for k in range(t, t + horizon - 1):
                        if c[k] / entry - 1 <= st / 100:
                            exit_i, price = k + 1, o[k + 1]
                            break
                j1 = nidx.get(ds[exit_i])
                if j1 is None:
                    continue
                nret = (nk["o"][j1] if exit_i > t + horizon - 1 or price != c[exit_i] else nk["c"][j1]) / nk["o"][j0] - 1
                r = price / entry - 1
                res[st].append({"date": ds[t], "ret": r * 100, "x": (r - nret) * 100, "slip": (price / (entry * (1 + st / 100)) - 1) * 100 if st and exit_i < t + horizon - 1 else None})
    out = []
    for st, rows in res.items():
        s = stats(rows, key="x")
        worst = sorted(r["ret"] for r in rows)[: max(1, len(rows) // 20)]
        slips = [r["slip"] for r in rows if r["slip"] is not None]
        out.append({"stop": st, **(s or {}), "p5": round(worst[-1], 2) if worst else None,
                    "cut_rate": round(len(slips) / len(rows) * 100, 1) if rows else None,
                    "slip": round(sum(slips) / len(slips), 2) if slips else None})
    return out


def regime_study(nk: dict) -> list[dict]:
    """日経平均そのものを、移動平均より上のときだけ持つ（前日の終値で判断し、翌日の始値で売買）。"""
    o, c = nk["o"], nk["c"]
    out = []
    for name, n in (("いつも持つ（買い持ち）", None), ("25日線より上のときだけ持つ", 25), ("75日線より上のときだけ持つ", 75)):
        v, peak, mdd, held_days, holding = 1.0, 1.0, 0.0, 0, False
        start = 80
        for i in range(start, len(c)):
            want = True if n is None else c[i - 1] > _ma(c, i - 1, n)
            if want and not holding:
                v *= c[i] / o[i]
                holding = True
            elif want and holding:
                v *= c[i] / c[i - 1]
            elif not want and holding:
                v *= o[i] / c[i - 1]
                holding = False
            held_days += 1 if holding else 0
            peak = max(peak, v)
            mdd = min(mdd, v / peak - 1)
        out.append({"name": name, "ret": round((v - 1) * 100, 1), "mdd": round(mdd * 100, 1),
                    "held": round(held_days / (len(c) - start) * 100), "from": nk["d"][start], "to": nk["d"][-1]})
    return out


def cash_core_study(root: Path, nk: dict) -> dict | None:
    """実際の記録で、使っていない現金を日経平均（ETF）で持っていたらどうなったか（概算）。"""
    from kabu.settle import read_rows
    hist = read_rows(Path(root) / "data" / "history.csv")
    if len(hist) < 2:
        return None
    nc = {d: c for d, c in zip(nk["d"], nk["c"])}
    idx = {d: i for i, d in enumerate(nk["d"])}
    v = vf = float(hist[0]["total"])
    for a, b in zip(hist, hist[1:]):
        if a["date"] not in nc or b["date"] not in nc:
            return None
        stock_pl = float(b["total"]) - float(a["total"])
        r = nc[b["date"]] / nc[a["date"]] - 1
        v += stock_pl + float(a["cash"]) * r
        i = idx[a["date"]]
        above = i >= 25 and nk["c"][i] > _ma(nk["c"], i, 25)   # 前日終値で判断
        vf += stock_pl + (float(a["cash"]) * r if above else 0.0)
    h = hist[-1]
    return {"from": hist[0]["date"], "to": h["date"], "actual": round((int(h["total"]) / 1_000_000 - 1) * 100, 2),
            "core": round((v / 1_000_000 - 1) * 100, 2), "core_filtered": round((vf / 1_000_000 - 1) * 100, 2),
            "bench": round((int(h["benchmark_value"]) / 1_000_000 - 1) * 100, 2)}


def day_table(rows: list[dict]) -> list[dict]:
    """銘柄×日 の結果を、日ごとにまとめる（その朝の相場全体の状態と、全銘柄を買ったときの5日後の騰落）。"""
    g = {}
    for r in rows:
        g.setdefault(r["date"], []).append(r)
    out = []
    for d, rs in sorted(g.items()):
        n = len(rs)
        out.append({"date": d, "ret": sum(r["ret"] for r in rs) / n, "x": sum(r["x"] for r in rs) / n,
                    "gap": sum(r["gap"] for r in rs) / n, "prev": sum(r["prev"] for r in rs) / n,
                    "n_ma25": rs[0]["n_ma25"], "n_r5": rs[0]["n_r5"],
                    "breadth": sum(1 for r in rs if r["ma25"] > 0) / n * 100})
    return out


def day_stats(days: list[dict], base: dict | None = None) -> dict | None:
    n = len(days)
    if n < 2:
        return None
    xs = [d["ret"] for d in days]
    m = sum(xs) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    downs = [x for x in xs if x < 0]
    t = 0.0
    if base is not None and sd:
        t = (m - base["ret"]) / (sd / math.sqrt(n))
    return {"n": n, "ret": round(m, 2), "up": round(sum(1 for x in xs if x > 0) / n * 100, 1),
            "down_avg": round(sum(downs) / len(downs), 2) if downs else 0.0,
            "p10": round(sorted(xs)[max(0, n // 10 - 1)], 2), "t": round(t, 1), "base": base["ret"] if base else m}


def day_verdict(s: dict) -> str:
    if s["n"] < MIN_DAYS:
        return "件数不足"
    d = s["ret"] - s["base"]
    if abs(s["t"]) >= 2 and abs(d) >= 0.5:
        return "有利（買ってよい日）" if d > 0 else "不利（買わない日）"
    return "差なし"


DAY_GROUPS = [
    ("相場全体が大きく安く寄った朝（全銘柄の寄りの平均 −1.5%以下）", lambda d: d["gap"] <= -1.5),
    ("相場全体がやや安く寄った朝（−1.5〜−0.5%）", lambda d: -1.5 < d["gap"] <= -0.5),
    ("ほぼ前日並みの朝（−0.5〜+0.5%）", lambda d: -0.5 < d["gap"] < 0.5),
    ("相場全体がやや高く寄った朝（+0.5〜+1.5%）", lambda d: 0.5 <= d["gap"] < 1.5),
    ("相場全体が大きく高く寄った朝（+1.5%以上）", lambda d: d["gap"] >= 1.5),
    ("日経平均が25日線より上", lambda d: d["n_ma25"] > 0),
    ("日経平均が25日線より下", lambda d: d["n_ma25"] < 0),
    ("日経平均が5日で −5%以下（急落の後）", lambda d: d["n_r5"] <= -5),
    ("日経平均が5日で +5%以上（急騰の後）", lambda d: d["n_r5"] >= 5),
    ("25日線より上の銘柄が7割以上（全面高の後）", lambda d: d["breadth"] >= 70),
    ("25日線より上の銘柄が3割未満（全面安の後）", lambda d: d["breadth"] < 30),
]


# ---------------- 研究の中身 ----------------

def run_all(stocks: dict, nk: dict, root: Path) -> tuple[str, dict]:
    rows = events(stocks, nk)
    base = stats(rows)
    findings = []
    L = [f"# 研究レポート（{date.today().isoformat()} 作成）", "",
         f"対象：日経225採用銘柄 {len(stocks)}銘柄・{nk['d'][80]}〜{nk['d'][-1]}・{len(rows):,}件（銘柄×日）。",
         f"物差し：その日の始値で買い、{HOLD}営業日後の終値で評価。**同じ日に買えた日経225全銘柄の平均との差**（その日の相場全体の上げ下げを除いた、銘柄選びの差）で比べる。日経平均との差も参考に載せる。",
         f"判定：件数{MIN_N}以上かつ{MIN_DAYS}日以上・t値の絶対値{T_SIG:.0f}以上・0.3ポイント以上の差があるものだけを「有利」「不利」とする。"
         "t値は日ごとの平均から計算する（同じ日の銘柄はまとめて動くため）。期間が重なるので、それでも甘めに出る。",
         "", f"**全体（どの銘柄をいつ買っても）**：騰落 {base['ret']:+.2f}%・日経平均との差 {stats(rows, key='x')['mean']:+.2f}%・{base['n']:,}件（{base['days']}日）", ""]

    sections = [
        ("1. 寄り付きの位置（始値が前日終値より何%高いか）", [
            ("−2%未満（大きく安く寄る）", lambda r: r["gap"] < -2), ("−2〜0%", lambda r: -2 <= r["gap"] < 0),
            ("0〜+2%", lambda r: 0 <= r["gap"] < 2), ("+2〜+4%（高寄り）", lambda r: 2 <= r["gap"] < 4),
            ("+4%以上（大幅な高寄り）", lambda r: r["gap"] >= 4)]),
        ("2. 前日の値動き（急騰・急落の翌日）", [
            ("前日 −5%以下（急落の翌日）", lambda r: r["prev"] <= -5), ("前日 −5〜−2%", lambda r: -5 < r["prev"] <= -2),
            ("前日 −2〜+2%", lambda r: -2 < r["prev"] < 2), ("前日 +2〜+5%", lambda r: 2 <= r["prev"] < 5),
            ("前日 +5%以上（急騰の翌日）", lambda r: r["prev"] >= 5),
            ("急騰の翌日で、さらに+2%以上高く寄る", lambda r: r["prev"] >= 5 and r["gap"] >= 2),
            ("急騰の翌日で、寄りが+1%未満", lambda r: r["prev"] >= 5 and r["gap"] < 1)]),
        ("3. トレンド（移動平均線との位置）", [
            ("25日線・75日線の両方より上で、25日線が上向き", lambda r: r["ma25"] > 0 and r["ma75"] > 0 and r["slope25"] > 0),
            ("25日線より下で、25日線が下向き", lambda r: r["ma25"] < 0 and r["slope25"] < 0),
            ("75日線より上で、25日線から−3%以内の押し目", lambda r: r["ma75"] > 0 and -3 <= r["ma25"] <= 0),
            ("25日線から+10〜+15%の上方乖離", lambda r: 10 <= r["ma25"] < 15),
            ("25日線から+15%以上の上方乖離（今の決まりでは買わない）", lambda r: r["ma25"] >= 15),
            ("25日線から−10%以上の下方乖離", lambda r: r["ma25"] <= -10)]),
        ("4. RSI（過熱・売られすぎ）", [
            ("RSI 30未満", lambda r: r["rsi"] < 30), ("RSI 30〜50", lambda r: 30 <= r["rsi"] < 50),
            ("RSI 50〜70", lambda r: 50 <= r["rsi"] < 70), ("RSI 70〜75", lambda r: 70 <= r["rsi"] < 75),
            ("RSI 75以上（今の決まりでは買わない）", lambda r: r["rsi"] >= 75),
            ("上昇トレンド（75日線より上）でRSI 40未満", lambda r: r["ma75"] > 0 and r["rsi"] < 40)]),
        ("5. 直近20日の値動き（勢いが続くか、戻るか）", [
            ("20日で −15%以下", lambda r: r["r20"] <= -15), ("20日で −15〜−5%", lambda r: -15 < r["r20"] <= -5),
            ("20日で −5〜+5%", lambda r: -5 < r["r20"] < 5), ("20日で +5〜+15%", lambda r: 5 <= r["r20"] < 15),
            ("20日で +15%以上", lambda r: r["r20"] >= 15)]),
        ("6. 出来高", [
            ("出来高が平均の2倍以上で、前日上昇", lambda r: (r["volr"] or 0) >= 2 and r["prev"] > 0),
            ("出来高が平均の2倍以上で、前日下落", lambda r: (r["volr"] or 0) >= 2 and r["prev"] < 0),
            ("出来高が平均の0.7倍未満", lambda r: r["volr"] is not None and r["volr"] < 0.7)]),
    ]
    for title, groups in sections:
        lines, f = table(title, groups, rows, base)
        L += lines
        findings += f

    # 相場全体のタイミング（1日を1件として数える。いつ買うか・いつ休むか）
    days = day_table(rows)
    dbase = day_stats(days)
    L += ["### 7. 相場全体のタイミング（1日＝1件。その朝に全銘柄を始値で買ったら、5営業日後にどうなったか）", "",
          f"全体：{dbase['n']}日・騰落の平均 {dbase['ret']:+.2f}%・上がった日の割合 {dbase['up']:.0f}%・下がった日の平均 {dbase['down_avg']:+.2f}%", "",
          "| その朝の状態 | 日数 | 騰落（平均） | 上がった日の割合 | 下がった日の割合 | 悪いほうから10%目 | t値（全体との差） | 判定 |",
          "|---|---:|---:|---:|---:|---:|---:|---|"]
    for label, f in DAY_GROUPS:
        sub = [d for d in days if f(d)]
        s = day_stats(sub, dbase)
        if not s:
            L.append(f"| {label} | {len(sub)} | - | - | - | - | - | 件数不足 |")
            continue
        v = day_verdict(s)
        L.append(f"| {label} | {s['n']} | {s['ret']:+.2f}% | {s['up']:.0f}% | {100 - s['up']:.0f}% | {s['p10']:+.2f}% | {s['t']:+.1f} | {v} |")
        findings.append({"section": "7. 相場全体のタイミング", "label": label, "n": s["n"], "days": s["n"], "mean": s["ret"],
                         "win": s["up"], "t": s["t"], "verdict": v})
    L += ["", "（騰落は日経225全銘柄の単純平均。「判定」は全体と比べて t値の絶対値2以上・0.5ポイント以上の差・30日以上）", ""]

    # 損切り
    sl = stop_loss_study(stocks, nk)
    L += ["### 8. 損切りの幅（始値で買い、最長20営業日。終値で基準を割ったら翌朝の始値で売る）", "",
          "| 損切り | 件数 | 騰落（平均） | 日経平均との差 | 上がった割合 | 損切りになった割合 | 損切りの売値の平均のずれ | 悪いほうから5%目 |",
          "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for s in sl:
        name = "なし" if s["stop"] is None else f"{s['stop']}%"
        L.append(f"| {name} | {s.get('n', 0):,} | {s.get('ret', 0):+.2f}% | {s.get('mean', 0):+.2f}% | {s.get('win', 0):.0f}% | "
                 f"{'-' if s['cut_rate'] is None or s['stop'] is None else str(s['cut_rate']) + '%'} | "
                 f"{'-' if s['slip'] is None else f'{s[chr(115)+chr(108)+chr(105)+chr(112)]:+.2f}%'} | {s['p5']:+.2f}% |")
    L += ["", "（「ずれ」は、損切りの基準の価格に対して実際の売値（翌朝の始値）がどれだけ下だったか）", ""]

    # 日経平均を地合いで持ち分ける
    rg = regime_study(nk)
    L += ["### 9. 日経平均そのものを、移動平均線より上のときだけ持ったら（前日終値で判断・翌朝の始値で売買）", "",
          "| やり方 | 騰落 | 最大下落幅 | 持っていた日の割合 |", "|---|---:|---:|---:|"]
    L += [f"| {r['name']} | {r['ret']:+.1f}% | {r['mdd']:.1f}% | {r['held']}% |" for r in rg]
    L.append(f"\n期間：{rg[0]['from']}〜{rg[0]['to']}\n")

    cc = cash_core_study(root, nk)
    if cc:
        L += ["### 10. 実際の記録：使っていない現金を日経平均（ETF）で持っていたら（概算）", "",
              f"- {cc['from']}〜{cc['to']}：実際 {cc['actual']:+.2f}%／現金をいつも日経平均で持った場合 {cc['core']:+.2f}%／"
              f"日経平均が25日線より上の日だけ持った場合 {cc['core_filtered']:+.2f}%／日経平均 {cc['bench']:+.2f}%", ""]

    good = [f for f in findings if f["verdict"].startswith("有利")]
    bad = [f for f in findings if f["verdict"].startswith("不利")]
    L += ["## まとめ（有意な差が出た条件）", ""]
    L += ["**有利（買う候補を絞るときに優先）**"] + [f"- {f['label']}（{f['section'][:2].strip('. ')}）：差 {f['mean']:+.2f}%・{f['n']:,}件（{f['days']}日）・t {f['t']:+.1f}" for f in good] or ["- なし"]
    L += ["", "**不利（避ける）**"] + [f"- {f['label']}（{f['section'][:2].strip('. ')}）：差 {f['mean']:+.2f}%・{f['n']:,}件（{f['days']}日）・t {f['t']:+.1f}" for f in bad] or ["- なし"]
    L += ["", "※過去2年の傾向で、これからも続くとは限らない。毎週計算し直し、判定が変わったら知らせる。"]
    summary = {"made": date.today().isoformat(), "period": [nk["d"][80], nk["d"][-1]], "n": len(rows), "base": base,
               "findings": findings, "stop_loss": sl, "regime": rg, "cash_core": cc}
    return "\n".join(L) + "\n", summary


def main():
    from kabu.picks import load_universe
    ap = argparse.ArgumentParser()
    ap.add_argument("--period", default="2y")
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    root = Path(a.root)
    stocks, nk = load_prices(list(load_universe(root / "data" / "nikkei225.csv")), a.period)
    if not nk or len(stocks) < 150:
        raise SystemExit(f"株価を十分に取得できませんでした（{len(stocks)}銘柄）")
    md, summary = run_all(stocks, nk, root)
    d = root / "data" / "research"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{summary['made']}.md").write_text(md, encoding="utf-8")
    (d / "latest.md").write_text(md, encoding="utf-8")
    (d / "latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(md)


if __name__ == "__main__":
    main()
