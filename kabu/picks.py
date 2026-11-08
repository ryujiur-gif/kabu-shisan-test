"""注文JSONの検証と対象銘柄一覧。"""
import csv
from pathlib import Path

CONFIDENCES = ("高", "中", "低")


def load_universe(path="data/nikkei225.csv") -> dict[str, str]:
    with open(Path(path), encoding="utf-8") as f:
        return {r["code"]: r["name"] for r in csv.DictReader(f)}


def validate_order(order: dict, state: dict, universe: dict, today: str | None = None) -> list[str]:
    if not isinstance(order, dict):
        return ["注文ファイルの形式が正しくありません"]
    buys, sells = order.get("buys"), order.get("sells")
    if not isinstance(buys, list) or not isinstance(sells, list) or             not all(isinstance(x, dict) for x in buys + sells):
        return ["buys と sells は銘柄({...})のリストにしてください"]
    errs = []
    if today is not None and order.get("date") != today:
        errs.append(f"date は {today} にしてください（現在 {order.get('date')}）")
    if order.get("settled", False) is not False:
        errs.append("settled は false にしてください")
    for x in buys + sells:
        if not str(x.get("name", "")).strip():
            errs.append(f"{x.get('code')} の name（銘柄名）が空です")
    held = state["holdings"]
    if len(buys) != 2:
        errs.append(f"買い銘柄は2つにしてください（現在{len(buys)}）")
    if len({b.get('code') for b in buys}) != len(buys):
        errs.append("買い銘柄が重複しています")
    for b in buys:
        if b.get("code") not in universe:
            errs.append(f"買い {b.get('code')} は日経225の銘柄ではありません")
        if b.get("confidence") not in CONFIDENCES:
            errs.append(f"買い {b.get('code')} の期待度は 高/中/低 のいずれかにしてください")
    need = min(2, len(held))
    if len(sells) != need:
        errs.append(f"売り銘柄は持ち株から{need}つにしてください（現在{len(sells)}）")
    if len({s.get('code') for s in sells}) != len(sells):
        errs.append("売り銘柄が重複しています")
    for s in sells:
        if s.get("code") not in held:
            errs.append(f"売り {s.get('code')} は持ち株にありません")
    for x in buys + sells:
        if not str(x.get("reason", "")).strip():
            errs.append(f"{x.get('code')} の理由が空です")
    if not str(order.get("summary", "")).strip():
        errs.append("市況の要約(summary)が空です")
    return errs
