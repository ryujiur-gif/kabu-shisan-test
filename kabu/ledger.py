"""仮想口座：約定と評価。金額は円の整数（端数切り捨て）。"""
import copy

START_CASH = 1_000_000
# 期待度ごとの購入額 = 総資産（現金＋持ち株の時価）に対する割合
RATIOS = {"高": 0.20, "中": 0.10, "低": 0.05}
MIN_CASH_RATIO = 0.10    # 買った後も現金を総資産の10%以上残す
MAX_STOCK_RATIO = 0.30   # 1銘柄の保有額は総資産の30%まで


def new_state(start_date: str) -> dict:
    return {"start_date": start_date, "cash": START_CASH, "holdings": {}, "benchmark": {}}


def amount_for(confidence: str, total: int = START_CASH) -> int:
    """期待度と総資産から購入予定額を決める（1,000円未満切り捨て）。"""
    return int(total * RATIOS[confidence]) // 1000 * 1000


def price_of(state: dict, code: str, prices: dict | None = None) -> float:
    """評価に使う株価：指定の株価 → 前回終値 → 取得単価 の順。"""
    h = state["holdings"][code]
    return (prices or {}).get(code) or state.get("last_closes", {}).get(code) or h["avg_cost"]


def funds(state: dict, prices: dict | None = None) -> dict:
    """資金状況：総資産・現金・株式・現金比率・銘柄ごとの比率。"""
    values = {c: int(h["shares"] * price_of(state, c, prices)) for c, h in state["holdings"].items()}
    stock = sum(values.values())
    total = state["cash"] + stock
    return {"total": total, "cash": state["cash"], "stock_value": stock,
            "cash_ratio": state["cash"] / total if total else 0.0,
            "weights": {c: v / total if total else 0.0 for c, v in values.items()},
            "values": values}


def _trade(date, side, item, shares, price, status):
    return {"date": date, "side": side, "code": item["code"], "name": item.get("name", ""),
            "shares": shares, "price": round(price, 2) if price else 0,
            "amount": int(shares * price) if price else 0, "status": status,
            "reason": item.get("reason", "")}


def settle(state: dict, order: dict, opens: dict[str, float]) -> tuple[dict, list[dict]]:
    st = copy.deepcopy(state)
    d = order["date"]
    total = funds(st, opens)["total"]  # 購入額の基準は約定日の始値で見た総資産
    trades = []
    for item in order.get("sells", []):
        code = item["code"]
        h = st["holdings"].get(code)
        price = opens.get(code)
        if not h or not price:
            trades.append(_trade(d, "売", item, 0, 0, "取消"))
            continue
        proceeds = int(h["shares"] * price)
        st["cash"] += proceeds
        trades.append(_trade(d, "売", {**item, "name": item.get("name") or h["name"]},
                             h["shares"], price, "約定"))
        del st["holdings"][code]
    for item in order.get("buys", []):
        code = item["code"]
        price = opens.get(code)
        if not price:
            trades.append(_trade(d, "買", item, 0, 0, "取消"))
            continue
        budget = min(amount_for(item["confidence"], total), st["cash"])
        shares = int(budget // price)
        if shares <= 0:
            trades.append(_trade(d, "買", item, 0, price, "見送り"))
            continue
        cost = int(shares * price)
        st["cash"] -= cost
        h = st["holdings"].get(code)
        if h:
            total = h["shares"] + shares
            h["avg_cost"] = (h["shares"] * h["avg_cost"] + shares * price) / total
            h["shares"] = total
        else:
            st["holdings"][code] = {"name": item.get("name", ""), "shares": shares,
                                    "avg_cost": float(price)}
        trades.append(_trade(d, "買", item, shares, price, "約定"))
    return st, trades


def valuation(state: dict, closes: dict[str, float]) -> dict:
    stock = 0
    for code, h in state["holdings"].items():
        stock += int(h["shares"] * closes.get(code, h["avg_cost"]))
    return {"total": state["cash"] + stock, "cash": state["cash"], "stock_value": stock}
