"""仮想口座：約定と評価。金額は円の整数（端数切り捨て）。"""
import copy

START_CASH = 1_000_000
AMOUNTS = {"高": 200_000, "中": 100_000, "低": 50_000}


def new_state(start_date: str) -> dict:
    return {"start_date": start_date, "cash": START_CASH, "holdings": {}, "benchmark": {}}


def amount_for(confidence: str) -> int:
    return AMOUNTS[confidence]


def _trade(date, side, item, shares, price, status):
    return {"date": date, "side": side, "code": item["code"], "name": item.get("name", ""),
            "shares": shares, "price": round(price, 2) if price else 0,
            "amount": int(shares * price) if price else 0, "status": status,
            "reason": item.get("reason", "")}


def settle(state: dict, order: dict, opens: dict[str, float]) -> tuple[dict, list[dict]]:
    st = copy.deepcopy(state)
    d = order["date"]
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
        budget = min(amount_for(item["confidence"]), st["cash"])
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
