from kabu.business_types import classify, TYPE_LABELS, market_regime


def test_classify_examples_from_user_table():
    assert classify("9432", "情報通信") == "①"     # NTT ストック型
    assert classify("6098", "サービス") == "①"     # リクルート
    assert classify("7203", "自動車") == "②"       # トヨタ 景気敏感
    assert classify("5401", "鉄鋼") == "②"
    assert classify("4063", "化学") == "②"
    assert classify("9501", "電力") == "③"         # 東電 ディフェンシブ
    assert classify("2914", "食品") == "③"
    assert classify("8267", "小売業") == "③"
    assert classify("4502", "医薬品") == "③"
    assert classify("6758", "電気機器") == "④"     # ソニー プラットフォーム
    assert classify("4755", "サービス") == "④"
    assert classify("4385", "情報通信") == "④"
    assert classify("6920", "電気機器") == "⑤"     # レーザーテック グロース
    assert classify("9999", "不明な業種") == "②"   # 既定


def test_labels():
    assert TYPE_LABELS["①"] == "ストック型"


def M(**kw):
    base = {"日経225先物（CME・円建て）": 0.0, "VIX（恐怖指数）": (16.0, 0.0), "米10年国債利回り": (4.50, 0.0),
            "ドル円": 0.0}
    base.update(kw)
    out = []
    for label, v in base.items():
        close, chg = v if isinstance(v, tuple) else (100.0, v)
        out.append({"label": label, "close": close, "chg": chg})
    return out


def test_regime_risk_off():
    r = market_regime(M(**{"VIX（恐怖指数）": (28.0, 15.0)}))
    assert r["mood"] == "リスクオフ（警戒）" and "③" in r["favor"] and "⑤" in r["avoid"]


def test_regime_rate_up_hurts_growth():
    r = market_regime(M(**{"米10年国債利回り": (4.60, 2.5)}))   # 約+0.11pt
    assert "⑤" in r["avoid"] and any("金利上昇" in x for x in r["notes"])


def test_regime_weak_yen_helps_exporters():
    r = market_regime(M(**{"ドル円": 0.8}))
    assert "②" in r["favor"] and any("円安" in x for x in r["notes"])


def test_regime_risk_on():
    r = market_regime(M(**{"日経225先物（CME・円建て）": 1.5, "VIX（恐怖指数）": (15.0, -5.0)}))
    assert r["mood"] == "リスクオン（強気）" and "⑤" in r["favor"]


def test_regime_missing_data():
    assert market_regime([])["mood"] == "判断材料不足"
