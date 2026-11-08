"""ビジネスモデルの型（①ストック型〜⑤グロース型）と、相場環境からみた有利・不利の目安。

型は業種から既定値を決め、代表的な銘柄は個別に上書きする。
正確な型は企業メモ（data/notes/<コード>.md）で Claude が見直してよい。
"""

TYPE_LABELS = {
    "①": "ストック型",
    "②": "景気敏感型",
    "③": "ディフェンシブ型",
    "④": "プラットフォーム型",
    "⑤": "グロース型",
}

TYPE_GUIDE = {
    "①": "業績・配当が安定し減配リスクが低い。押し目買い向き。新規獲得の鈍化と強い競合の参入に注意。",
    "②": "景気・為替・資源価格に連動。回復初期に強く、PERが極端に低いときは業績の天井の可能性に注意。",
    "③": "不景気・下落相場に強く、連続増配・高利回りで下値が堅い。急成長は期待しにくい。",
    "④": "ネットワーク効果で強いが、規制・技術の代替リスク。成長優先で低配当が多い。",
    "⑤": "売上成長が高いが期待先行で値動きが荒い。金利上昇局面に弱い。原則無配。",
}

SECTOR_DEFAULT = {
    "情報通信": "①", "サービス": "①",
    "食品": "③", "医薬品": "③", "電力": "③", "ガス": "③", "鉄道・バス": "③", "陸運": "③",
    "小売業": "③", "水産": "③",
}

OVERRIDES = {
    # ① ストック型
    "9432": "①", "9433": "①", "9434": "①", "6098": "①", "4307": "①", "4704": "①", "9735": "①",
    # ③ ディフェンシブ型
    "2914": "③", "8267": "③", "4502": "③", "9501": "③", "4661": "③",
    # ④ プラットフォーム型
    "6758": "④", "4755": "④", "4385": "④", "4689": "④", "9984": "④", "2413": "④", "3659": "④",
    # ⑤ グロース型
    "6920": "⑤", "6146": "⑤", "6857": "⑤",
}


def classify(code: str, sector: str) -> str:
    return OVERRIDES.get(code) or SECTOR_DEFAULT.get(sector, "②")


def _find(market, label):
    for m in market:
        if m.get("label") == label and m.get("close") is not None:
            return m
    return None


def market_regime(market: list[dict]) -> dict:
    """主要指標から相場環境を判定し、有利（favor）・不利（avoid）な型を返す。"""
    fut = _find(market, "日経225先物（CME・円建て）")
    vix = _find(market, "VIX（恐怖指数）")
    tnx = _find(market, "米10年国債利回り")
    usd = _find(market, "ドル円")
    if not (fut or vix):
        return {"mood": "判断材料不足", "favor": [], "avoid": [], "notes": []}
    favor, avoid, notes = [], [], []
    fchg = (fut or {}).get("chg") or 0.0
    vclose = (vix or {}).get("close") or 0.0
    if vclose >= 25 or fchg <= -2:
        mood = "リスクオフ（警戒）"
        favor += ["③", "①"]
        avoid += ["⑤", "②"]
        notes.append(f"VIX {vclose:.1f}・日経先物 {fchg:+.2f}%：守りの型を優先し、買いの期待度は控えめに")
    elif vclose and vclose < 20 and fchg >= 1:
        mood = "リスクオン（強気）"
        favor += ["②", "⑤", "④"]
        notes.append(f"VIX {vclose:.1f}・日経先物 {fchg:+.2f}%：景気敏感・成長株に追い風")
    else:
        mood = "中立"
    if tnx and tnx.get("chg") is not None:
        prev = tnx["close"] / (1 + tnx["chg"] / 100)
        diff = tnx["close"] - prev
        if diff >= 0.08:
            avoid.append("⑤")
            favor.append("②") if mood != "リスクオフ（警戒）" else None
            notes.append(f"米金利上昇（{diff:+.2f}pt）：グロース株に逆風、銀行など金利上昇の恩恵株に追い風")
        elif diff <= -0.08:
            favor.append("⑤")
            notes.append(f"米金利低下（{diff:+.2f}pt）：グロース株に追い風")
    if usd and usd.get("chg") is not None:
        if usd["chg"] >= 0.5:
            favor.append("②")
            notes.append(f"円安（ドル円 {usd['chg']:+.2f}%）：輸出の景気敏感株に追い風")
        elif usd["chg"] <= -0.5:
            avoid.append("②")
            favor.append("③")
            notes.append(f"円高（ドル円 {usd['chg']:+.2f}%）：輸出株に逆風、内需ディフェンシブに追い風")
    dedup = lambda xs: list(dict.fromkeys(x for x in xs if x))
    avoid = dedup(avoid)
    favor = [x for x in dedup(favor) if x not in avoid]
    return {"mood": mood, "favor": favor, "avoid": avoid, "notes": notes}
