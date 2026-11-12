"""買い候補の値動きと割安度を調べる（朝の資料の順位表に載っていない銘柄用）。

使い方: python -m kabu.lookup 5714 1801 [--today 2026-11-12]
朝の準備で保存した全銘柄の指標（data/daily/<today>/indicators.json）と財務データを表示する。
この環境から株価サイトには接続しない。
"""
import argparse
import csv
import json
from pathlib import Path


def _p(x) -> str:
    return "-" if x is None else f"{'+' if x >= 0 else ''}{x:.2f}%"


def lines(root: Path, today: str, codes: list[str]) -> list[str]:
    from kabu.business_types import TYPE_LABELS, classify
    from kabu.fundamentals import load_fundamentals
    data = Path(root) / "data"
    ip = data / "daily" / today / "indicators.json"
    if not ip.exists():
        return [f"{ip} がありません（朝の準備が済んでいない、または指標の保存前の日付です）"]
    ind = json.loads(ip.read_text(encoding="utf-8"))
    with open(data / "nikkei225.csv", encoding="utf-8") as f:
        uni = {r["code"]: r for r in csv.DictReader(f)}
    _, fund = load_fundamentals(data / "fundamentals.csv")
    cross = {"GC": "ゴールデンクロス", "DC": "デッドクロス"}
    out = []
    for c in codes:
        u, x, f = uni.get(c), ind.get(c), fund.get(c) or {}
        if not u:
            out.append(f"{c}：日経225の銘柄ではありません")
            continue
        t = classify(c, u.get("sector", ""))
        head = f"{u['name']}（{c}・{u.get('sector', '')}・{t}{TYPE_LABELS[t]}）"
        if not x:
            out.append(f"{head}：値動きのデータがありません")
            continue
        xs = "・".join(s for s in (
            cross.get(x.get("cross5_25")) and f"5日/25日{cross[x['cross5_25']]}",
            cross.get(x.get("cross25_75")) and f"25日/75日{cross[x['cross25_75']]}") if s) or "クロスなし"
        vol = "-" if x.get("vol_ratio") is None else f"{x['vol_ratio']:.1f}倍"
        rsi = "-" if x.get("rsi14") is None else f"{x['rsi14']:.0f}"
        fx = lambda k, fmt: "-" if f.get(k) is None else fmt.format(f[k])
        out.append(f"{head}：終値 {x['close']:,.1f}／前日比 {_p(x.get('chg1d'))}／5日 {_p(x.get('chg5d'))}／"
                   f"出来高 {vol}／25日線乖離 {_p(x.get('ma25_dev'))}／RSI {rsi}／{xs}／"
                   f"PER {fx('per', '{:.1f}倍')}／PBR {fx('pbr', '{:.2f}倍')}／ROE {fx('roe', '{:.1f}%')}／"
                   f"配当利回り {fx('div_yield', '{:.2f}%')}")
    return out


def main():
    from kabu.settle import jst_today
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="+")
    ap.add_argument("--today", default=None)
    ap.add_argument("--root", default=".")
    a = ap.parse_args()
    for l in lines(Path(a.root), a.today or jst_today().isoformat(), a.codes):
        print(l)


if __name__ == "__main__":
    main()
