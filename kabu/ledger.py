"""仮想口座：約定と評価。金額は円の整数（端数切り捨て）。"""
import copy

START_CASH = 1_000_000
# 期待度ごとの購入額 = 総資産（現金＋持ち株の時価）に対する割合
RATIOS = {"高": 0.20, "中": 0.10, "低": 0.05}
MIN_CASH_RATIO = 0.10    # 買った後も現金を総資産の10%以上残す
MAX_STOCK_RATIO = 0.30   # 1銘柄の保有額は総資産の30%まで
MAX_SECTOR_RATIO = 0.30  # 1業種の保有額は総資産の30%まで
WEAK_STOCK_CAP = 0.30   # 日経平均が25日線より下の間は、株の合計を総資産の30%まで（2026-11-25 竜司さん決定）
WEAK_STOCK_CAP_PROVEN = 0.40   # 期待度「高」の実績が条件を満たしたら、地合いが弱い間の上限をここまで広げる
HIGH_MIN_CASES = 10            # 条件：期待度「高」の評価済みの買いが10件以上で、
                               #       日経平均との差の平均がプラス（2026-11-25 竜司さん決定）


def high_track(review: dict | None) -> dict:
    """期待度「高」の買いの実績（評価済みの件数と、日経平均との差の平均）。"""
    xs = [b["x"] for b in (review or {}).get("buys") or []
          if b.get("confidence") == "高" and b.get("ret") is not None and b.get("x") is not None]
    avg = round(sum(xs) / len(xs), 2) if xs else None
    return {"n": len(xs), "avg_x": avg, "proven": len(xs) >= HIGH_MIN_CASES and avg is not None and avg > 0}


def weak_cap(review: dict | None) -> dict:
    """地合いが弱い間の株の上限。「高」の実績が条件を満たせば40%、そうでなければ30%。"""
    t = high_track(review)
    return {"cap": WEAK_STOCK_CAP_PROVEN if t["proven"] else WEAK_STOCK_CAP, "high": t}
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


def sell_shares(held: int, portion: str | None, lot: int = 1) -> int:
    """売る株数。「半分」は売買単位（lot）に切り捨て（最低1単位）。1単位しか無ければ全部売る。"""
    if PORTIONS.get(portion or "全部", 1.0) >= 1.0 or held <= lot:
        return held
    return max(lot, held // 2 // lot * lot)


def open_gap(price: float, ref_close: float | None) -> float | None:
    """始値が前日終値より何%高いか。"""
    if not ref_close or not price:
        return None
    return round((price / ref_close - 1) * 100, 2)


def settle(state: dict, order: dict, opens: dict[str, float],
           ref_closes: dict[str, float] | None = None, lot: int = 1,
           stock_cap: float | None = None) -> tuple[dict, list[dict]]:
    """注文を始値で約定する。ref_closes（前日終値）があれば、始値が高すぎる買いを見送る。
    lot は売買単位（本体は1株。100株単位の試算では100）。"""
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
        n = sell_shares(h["shares"], item.get("portion"), lot)
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
        if stock_cap is not None:   # 地合いが弱い間の上限：買った後の株の合計を総資産の stock_cap まで
            stock_now = sum(int(x["shares"] * (opens.get(c) or price_of(st, c))) for c, x in st["holdings"].items())
            room = int(total * stock_cap) - stock_now
            if room < price * lot:
                trades.append(_trade(d, "買", {**item, "reason": f"地合いの上限（株は総資産の{stock_cap:.0%}まで）に達していたため見送り。"
                                               f"元の理由：{item.get('reason', '')}"}, 0, price, "見送り"))
                continue
            budget = min(budget, room)
        shares = int(budget // price) // lot * lot
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


def fee_for(amount: float, fee) -> int:
    """1回の注文の手数料。fee は料率（例 0.001）か、段階制の表 [[約定代金の上限, 手数料], ...]（上限 None は「それ以上」）。"""
    if not fee or amount <= 0:
        return 0
    if isinstance(fee, (int, float)):
        return int(amount * fee)
    for limit, yen in fee:
        if limit is None or amount <= limit:
            return int(yen)
    return int(fee[-1][1])


def load_fee(cfg: dict):
    """config.json から手数料の設定を読む（fee_table があれば優先、無ければ fee_rate）。"""
    return cfg.get("fee_table") or float(cfg.get("fee_rate", 0.0))


def after_tax(total: int, trades: list[dict], fee_rate=0.0, start: int = START_CASH) -> dict:
    """手数料と税を引いた概算（いま全部売った場合）。利益が出ているときだけ税がかかる。
    手数料は、これまでの売買の分と、いまの持ち株を1銘柄ずつ売る分の合計。"""
    done = [t for t in trades if t["side"] in ("買", "売") and t.get("status") == "約定"]
    turnover = sum(int(t["amount"]) for t in done)
    fees = sum(fee_for(int(t["amount"]), fee_rate) for t in done)
    if fee_rate:
        fees += sum(fee_for(h["shares"] * h["avg_cost"], fee_rate) for h in replay(trades)["holdings"].values())
    gain = total - fees - start
    tax = int(gain * TAX_RATE) if gain > 0 else 0
    return {"fees": fees, "tax": tax, "net": total - fees - tax, "turnover": turnover}
