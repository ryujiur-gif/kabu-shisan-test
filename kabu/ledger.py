"""仮想口座：約定と評価。金額は円の整数（端数切り捨て）。"""
import copy

START_CASH = 1_000_000
# 期待度ごとの購入額 = 総資産（現金＋持ち株の時価）に対する割合
RATIOS = {"高": 0.20, "中": 0.10, "低": 0.05}
MIN_CASH_RATIO = 0.10    # 買った後も現金を総資産の10%以上残す
MAX_STOCK_RATIO = 0.30   # 1銘柄の保有額は総資産の30%まで
MAX_SECTOR_RATIO = 0.30  # 1業種の保有額は総資産の30%まで
MAX_OPEN_GAP = 5.0       # 始値が前日終値より +5% 以上高い買いは見送る（高値づかみを避ける）
TAX_RATE = 0.20315       # 利益・配当にかかる税（概算の「税引き後」の計算に使う）
PORTIONS = {"全部": 1.0, "半分": 0.5}


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


def sell_shares(held: int, portion: str | None) -> int:
    """売る株数。「半分」は切り捨て（最低1株）。1株しか無ければ全部売る。"""
    if PORTIONS.get(portion or "全部", 1.0) >= 1.0 or held <= 1:
        return held
    return max(1, held // 2)


def open_gap(price: float, ref_close: float | None) -> float | None:
    """始値が前日終値より何%高いか。"""
    if not ref_close or not price:
        return None
    return round((price / ref_close - 1) * 100, 2)


def settle(state: dict, order: dict, opens: dict[str, float],
           ref_closes: dict[str, float] | None = None) -> tuple[dict, list[dict]]:
    """注文を始値で約定する。ref_closes（前日終値）があれば、始値が高すぎる買いを見送る。"""
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
        n = sell_shares(h["shares"], item.get("portion"))
        st["cash"] += int(n * price)
        trades.append(_trade(d, "売", {**item, "name": item.get("name") or h["name"]}, n, price, "約定"))
        h["shares"] -= n
        if h["shares"] <= 0:
            del st["holdings"][code]
    for item in order.get("buys", []):
        code = item["code"]
        price = opens.get(code)
        if not price:
            trades.append(_trade(d, "買", item, 0, 0, "取消"))
            continue
        gap = open_gap(price, (ref_closes or {}).get(code))
        limit = item.get("max_open_gap", MAX_OPEN_GAP)
        if gap is not None and limit is not None and gap >= float(limit):
            trades.append(_trade(d, "買", {**item, "reason": f"始値が前日終値より{gap:+.1f}%高く（基準+{float(limit):.0f}%以上）見送り。"
                                           f"元の理由：{item.get('reason', '')}"}, 0, price, "見送り"))
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
            held = h["shares"] + shares   # （総資産の total を上書きしないこと）
            h["avg_cost"] = (h["shares"] * h["avg_cost"] + shares * price) / held
            h["shares"] = held
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


ACTION_SIDES = ("配当", "分割")


def _order_key(t: dict):
    """同じ日なら、配当・分割（その日の取引より前に効く）を先に並べる。"""
    return (t["date"], 0 if t["side"] in ACTION_SIDES else 1)


def apply_split(h: dict, eligible: int, ratio: float) -> int:
    """分割・併合を持ち株に反映し、新しい株数を返す。取得額の合計は変えない（単価を調整）。"""
    old = h["shares"]
    new = old - eligible + int(eligible * ratio)
    if new > 0:
        h["avg_cost"] = h["avg_cost"] * old / new
    h["shares"] = new
    return new


def replay(trades: list[dict]) -> dict:
    """取引履歴を最初からたどって、現金と持ち株を計算し直す。記録の点検と過去日の評価に使う。
    約定した売買のほか、配当（入金）と株式分割（調整）も反映する。"""
    cash, holdings = START_CASH, {}
    for t in sorted(trades, key=_order_key):
        code, side = t["code"], t["side"]
        if side == "配当":
            cash += int(t["amount"])
            continue
        if side == "分割":
            h = holdings.get(code)
            if h:
                h["shares"] = int(t["shares"])
                h["avg_cost"] = h["avg_cost"] / float(t["price"])
                if h["shares"] <= 0:
                    holdings.pop(code)
            continue
        if t.get("status") != "約定":
            continue
        shares, price = int(t["shares"]), float(t["price"])
        if side == "買":
            cash -= int(t["amount"])
            h = holdings.get(code)
            if h:
                total = h["shares"] + shares
                h["avg_cost"] = (h["shares"] * h["avg_cost"] + shares * price) / total
                h["shares"] = total
            else:
                holdings[code] = {"name": t.get("name", ""), "shares": shares, "avg_cost": price}
        elif side == "売":
            cash += int(t["amount"])
            h = holdings.get(code)
            if h:
                h["shares"] -= shares
                if h["shares"] <= 0:
                    holdings.pop(code)
    return {"cash": cash, "holdings": holdings}


def after_tax(total: int, trades: list[dict], fee_rate: float = 0.0, start: int = START_CASH) -> dict:
    """手数料と税を引いた概算（いま全部売った場合）。利益が出ているときだけ税がかかる。"""
    turnover = sum(int(t["amount"]) for t in trades if t["side"] in ("買", "売") and t.get("status") == "約定")
    fees = int(turnover * fee_rate)
    gain = total - fees - start
    tax = int(gain * TAX_RATE) if gain > 0 else 0
    return {"fees": fees, "tax": tax, "net": total - fees - tax, "turnover": turnover}
