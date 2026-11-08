"""メール文面と成績ページ（docs/index.html）の生成。"""
import html as H
import json
from datetime import date

from kabu.ledger import START_CASH, amount_for

NOTE = "※試験運用です。投資判断はご自身の責任で行ってください。"


def _yen(n) -> str:
    return f"{int(n):,}円"


def _signed(n) -> str:
    return f"{'+' if n >= 0 else '-'}{abs(int(n)):,}円"


def _pct(n) -> str:
    return f"{'+' if n >= 0 else '-'}{abs(n):.2f}%"


def _man(n) -> str:
    return f"{n // 10000}万円"


def build_email(order, state, history_rows, last_trades, site_url) -> dict:
    d = date.fromisoformat(order["date"])
    buys = "・".join(b["name"] for b in order["buys"]) or "なし"
    sells = "・".join(s["name"] for s in order["sells"]) or "なし"
    subject = f"【株予想】{d.month}/{d.day} 買い：{buys}／売り：{sells}"

    L = [f"■ 本日（{d.month}/{d.day}）の予想", "", "【市況】", order["summary"].strip(), "", "【買い】"]
    for b in order["buys"]:
        L.append(f"・{b['name']}（{b['code']}）期待度：{b['confidence']}　予定額：{_man(amount_for(b['confidence']))}")
        L.append(f"　理由：{b['reason']}")
    L += ["", "【売り】"]
    if order["sells"]:
        for s in order["sells"]:
            L.append(f"・{s['name']}（{s['code']}）全株売却")
            L.append(f"　理由：{s['reason']}")
    else:
        L.append("・なし（持ち株なし）")
    L.append("※売買は本日の始値で成立したものとして記録します。")

    L += ["", "■ 前回の約定結果"]
    if last_trades:
        for t in last_trades:
            if t["status"] == "約定":
                L.append(f"・{t['side']} {t['name']} {int(t['shares']):,}株 @{float(t['price']):,.1f}円（{_yen(t['amount'])}）")
            else:
                L.append(f"・{t['side']} {t['name']}：{t['status']}")
    else:
        L.append("・まだありません")

    L += ["", "■ 成績"]
    if history_rows:
        h = history_rows[-1]
        total, bench = int(h["total"]), int(h["benchmark_value"])
        L.append(f"総資産：{_yen(total)}（{h['date']} 終値時点）")
        L.append(f"損益：{_signed(total - START_CASH)}（{_pct((total - START_CASH) / START_CASH * 100)}）")
        L.append(f"日経平均に同額投資した場合：{_yen(bench)}（{_pct((bench - START_CASH) / START_CASH * 100)}）")
        L.append(f"日経平均との差：{_signed(total - bench)}")
    else:
        L.append(f"総資産：{_yen(START_CASH)}（運用開始前）")
    if state["holdings"]:
        L += ["", "【持ち株】"]
        closes = state.get("last_closes", {})
        for c, hd in state["holdings"].items():
            px = closes.get(c, hd["avg_cost"])
            pl = (px - hd["avg_cost"]) * hd["shares"]
            L.append(f"・{hd['name']}（{c}）{hd['shares']:,}株 取得{hd['avg_cost']:,.1f}→{px:,.1f}円 {_signed(pl)}")
    L += ["", f"成績ページ：{site_url}", "", NOTE]
    return {"subject": subject, "body": "\n".join(L) + "\n"}


def _e(x) -> str:
    return H.escape(str(x))


CSS = """
:root{--bg:#f7f7f4;--card:#fff;--fg:#1d1d1b;--mute:#6b6b66;--line:#e4e4de;--up:#c2410c;--down:#1d4ed8;--mine:#0f766e;--bench:#9a9a92}
@media (prefers-color-scheme:dark){:root{--bg:#151514;--card:#1f1f1d;--fg:#ececea;--mute:#9b9b95;--line:#33332f;--up:#fb923c;--down:#60a5fa;--mine:#2dd4bf;--bench:#77776f}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font-family:system-ui,"Hiragino Sans","Yu Gothic UI",sans-serif;line-height:1.6}
main{max-width:760px;margin:0 auto;padding:16px}h1{font-size:1.25rem;margin:8px 0 2px}h2{font-size:1rem;margin:0 0 10px}
.sub{color:var(--mute);font-size:.8rem;margin:0 0 16px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:14px}
.kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}.kpi small{display:block;color:var(--mute);font-size:.72rem}.kpi b{font-size:1.05rem;font-variant-numeric:tabular-nums}
.up{color:var(--up)}.down{color:var(--down)}table{width:100%;border-collapse:collapse;font-size:.82rem;font-variant-numeric:tabular-nums}
th,td{padding:6px 4px;border-bottom:1px solid var(--line);text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}td small{display:block;color:var(--mute);font-size:.7rem}
.scroll{overflow-x:auto}.pick{border-top:1px solid var(--line);padding:8px 0}.pick p{margin:2px 0 0;font-size:.85rem;color:var(--mute)}
.tag{display:inline-block;font-size:.72rem;font-weight:700;border:1px solid currentColor;border-radius:4px;padding:0 5px;margin-right:6px}
.summary{font-size:.9rem;margin:0 0 6px}.legend{font-size:.75rem;color:var(--mute)}.legend i{display:inline-block;width:10px;height:3px;vertical-align:middle;margin:0 4px 0 10px}
footer{color:var(--mute);font-size:.75rem;text-align:center;padding:8px 0 24px}
"""

CHART_JS = """
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
if(window.Chart&&D.labels.length){new Chart(document.getElementById('c'),{type:'line',
data:{labels:D.labels.map(s=>s.slice(5)),datasets:[
{label:'予想どおり売買',data:D.mine,borderColor:css('--mine'),borderWidth:2,pointRadius:D.labels.length<3?3:0,tension:.2},
{label:'日経平均に同額投資',data:D.bench,borderColor:css('--bench'),borderWidth:2,borderDash:[4,3],pointRadius:D.labels.length<3?3:0,tension:.2}]},
options:{maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:false},
tooltip:{callbacks:{label:c=>c.dataset.label+'：'+c.parsed.y.toLocaleString()+'円'}}},
scales:{x:{ticks:{color:css('--mute'),maxTicksLimit:6},grid:{display:false}},
y:{ticks:{color:css('--mute'),callback:v=>(v/10000).toFixed(0)+'万'},grid:{color:css('--line')}}}}});}
else{document.getElementById('c').parentNode.innerHTML='<p class="sub">記録がたまるとグラフが表示されます</p>';}
"""


def build_site(state, history_rows, trades_rows, order) -> str:
    closes = state.get("last_closes", {})
    if history_rows:
        h = history_rows[-1]
        total, bench, asof = int(h["total"]), int(h["benchmark_value"]), h["date"]
    else:
        total, bench, asof = START_CASH, START_CASH, "運用開始前"
    pl = total - START_CASH
    chart = {"labels": [r["date"] for r in history_rows],
             "mine": [int(r["total"]) for r in history_rows],
             "bench": [int(r["benchmark_value"]) for r in history_rows]}

    hold = []
    for c, hd in state["holdings"].items():
        px = closes.get(c, hd["avg_cost"])
        p = (px - hd["avg_cost"]) * hd["shares"]
        hold.append(f"<tr><td>{_e(hd['name'])}<small>{_e(c)}</small></td><td>{hd['shares']:,}</td>"
                    f"<td>{hd['avg_cost']:,.1f}</td><td>{px:,.1f}</td>"
                    f"<td class='{'up' if p >= 0 else 'down'}'>{_signed(p)}</td></tr>")
    hold_rows = "".join(hold) or "<tr><td colspan='5'>持ち株はありません</td></tr>"

    trade_rows = "".join(
        f"<tr><td>{_e(t['date'][5:])}</td><td class='{'up' if t['side'] == '買' else 'down'}'>{_e(t['side'])}</td>"
        f"<td>{_e(t['name'])}</td><td>{int(t['shares']):,}</td><td>{float(t['price']):,.1f}</td><td>{_e(t['status'])}</td></tr>"
        for t in reversed(trades_rows)) or "<tr><td colspan='6'>まだありません</td></tr>"

    picks = "<p>まだありません</p>"
    if order:
        items = [("買", b["name"], b["code"], f"期待度 {b['confidence']}", b["reason"]) for b in order["buys"]]
        items += [("売", s["name"], s["code"], "全株売却", s["reason"]) for s in order["sells"]]
        picks = f"<p class='summary'>{_e(order['summary'])}</p>" + "".join(
            f"<div class='pick'><span class='tag {'up' if k == '買' else 'down'}'>{k}</span>"
            f"<b>{_e(n)}</b> <small>{_e(c)}・{_e(m)}</small><p>{_e(r)}</p></div>" for k, n, c, m, r in items)

    return f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>株予想 成績</title>
<style>{CSS}</style></head><body><main>
<h1>株予想 試験運用の成績</h1>
<p class="sub">仮想の100万円で毎朝の予想どおりに売買した場合（{_e(asof)} 終値時点・運用開始 {_e(state['start_date'])}）</p>
<section class="card kpis">
<div class="kpi"><small>総資産</small><b>{_yen(total)}</b></div>
<div class="kpi"><small>損益</small><b class="{'up' if pl >= 0 else 'down'}">{_signed(pl)}<br>{_pct(pl / START_CASH * 100)}</b></div>
<div class="kpi"><small>日経平均との差</small><b class="{'up' if total >= bench else 'down'}">{_signed(total - bench)}</b></div>
</section>
<section class="card"><h2>資産の推移</h2>
<div class="legend"><i style="background:var(--mine)"></i>予想どおり売買<i style="background:var(--bench)"></i>日経平均に同額投資</div>
<div style="position:relative;height:240px"><canvas id="c"></canvas></div></section>
<section class="card"><h2>最新の予想（{_e(order['date'] if order else '-')}）</h2>{picks}</section>
<section class="card"><h2>持ち株</h2><div class="scroll"><table><tr><th>銘柄</th><th>株数</th><th>取得単価</th><th>現在値</th><th>損益</th></tr>{hold_rows}</table></div>
<p class="sub" style="margin:8px 0 0">現金：{_yen(state['cash'])}</p></section>
<section class="card"><h2>取引履歴</h2><div class="scroll"><table><tr><th>日付</th><th>売買</th><th>銘柄</th><th>株数</th><th>単価</th><th>状態</th></tr>{trade_rows}</table></div></section>
<footer>{NOTE}</footer>
</main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<script>const D={json.dumps(chart, ensure_ascii=False)};{CHART_JS}</script>
</body></html>
"""
