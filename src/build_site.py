"""Render the DB into a single self-contained static site for GitHub Pages.

Everything is precomputed here (Python) and embedded into site/index.html as a
JSON blob; the page itself is vanilla JS with no network calls, so it hosts for
free on Pages and answers "why does X think Y?" from stored data — no live
tokens. A future Phase 2 chat box would add a hosted backend; this is Phase 1.
"""
from __future__ import annotations
import datetime as dt
import json
import statistics
from pathlib import Path

from db import connect
import score as scoring

# GitHub Pages serves from /docs on the main branch with zero config.
SITE_DIR = Path(__file__).resolve().parent.parent / "docs"


def _jload(s, default):
    try:
        return json.loads(s) if s else default
    except (json.JSONDecodeError, TypeError):
        return default


def load_data() -> dict:
    conn = connect()
    reports = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM reports")}
    evals = {r["call_id"]: dict(r) for r in conn.execute("SELECT * FROM evaluations")}

    calls = []
    for c in conn.execute("SELECT * FROM calls"):
        c = dict(c)
        rep = reports.get(c["report_id"], {})
        ev = evals.get(c["id"], {})
        calls.append({
            "id": c["id"],
            "analyst": rep.get("analyst") or "Unknown",
            "broker": rep.get("broker") or "Unknown",
            "ticker": c["ticker"],
            "company": c["company_raw"],
            "sector": c["sector"],
            "report_date": c["report_date"],
            "rating": c["rating"],
            "rating_raw": c["rating_raw"],
            "rating_action": c["rating_action"],
            "cmp": c["cmp"],
            "target_price": c["target_price"],
            "prior_target": c["prior_target"],
            "horizon_months": c["horizon_months"],
            "thesis": c["thesis"],
            "drivers": _jload(c["drivers_json"], []),
            "risks": _jload(c["risks_json"], []),
            "estimates": _jload(c["estimates_json"], {}),
            "status": ev.get("status"),
            "tp_hit": ev.get("tp_hit"),
            "tp_hit_date": ev.get("tp_hit_date"),
            "direction_ok": ev.get("direction_ok"),
            "stock_return": ev.get("stock_return"),
            "alpha": ev.get("alpha"),
            "capture_ratio": ev.get("capture_ratio"),
            "max_drawdown": ev.get("max_drawdown"),
        })

    market = []
    for m in conn.execute(
        "SELECT m.*, r.broker, r.analyst, r.report_date, r.filename "
        "FROM market_reports m JOIN reports r ON r.id=m.report_id"
    ):
        m = dict(m)
        market.append({
            "broker": m["broker"], "analyst": m["analyst"],
            "date": m["report_date"], "theme": m["theme"],
            "sectors": _jload(m["sectors_json"], []),
            "summary": m["summary"], "outlook": m["outlook"],
            "key_points": _jload(m["key_points_json"], []),
        })
    conn.close()

    analysts = _aggregate(calls, key="analyst")
    brokers = _aggregate(calls, key="broker")
    stocks = _by_stock(calls)

    return {
        "generated_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "analysts": analysts,
        "brokers": brokers,
        "stocks": stocks,
        "market": market,
        "counts": {
            "reports": len(reports), "calls": len(calls),
            "analysts": len(analysts), "market_reports": len(market),
        },
    }


def _aggregate(calls: list[dict], key: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for c in calls:
        groups.setdefault(c[key], []).append(c)
    out = []
    for name, rows in groups.items():
        rating = scoring.analyst_score(rows)
        out.append({
            "name": name,
            **rating,
            "calls": sorted(rows, key=lambda r: r["report_date"] or "", reverse=True),
            "flags": _flags(rows, rating),
        })
    # ranked: scored first (desc), unrated last
    out.sort(key=lambda a: (a["score"] is None, -(a["score"] or 0)))
    return out


def _flags(rows: list[dict], rating: dict) -> list[str]:
    flags = []
    closed = [r for r in rows if r.get("alpha") is not None]
    ups = [r["capture_ratio"] for r in closed if r.get("capture_ratio") is not None]
    implied = [r.get("target_price") and r.get("cmp") and (r["target_price"]/r["cmp"]-1)
               for r in rows]
    implied = [x for x in implied if x]
    if len(closed) >= 3 and ups and statistics.mean(ups) < 0.4 and implied \
            and statistics.mean(implied) > 0.2:
        flags.append("chronic-optimism")
    if rating.get("direction_rate") is not None and rating["direction_rate"] < 0.4 \
            and len(closed) >= 4:
        flags.append("fade-signal")
    if rating.get("confidence") == "low":
        flags.append("low-sample")
    # drift: recent half vs older half by alpha
    if len(closed) >= 6:
        ordered = sorted(closed, key=lambda r: r["report_date"] or "")
        half = len(ordered) // 2
        old = statistics.mean([r["alpha"] for r in ordered[:half]])
        new = statistics.mean([r["alpha"] for r in ordered[half:]])
        if new < old - 0.05:
            flags.append("deteriorating")
    return flags


def _by_stock(calls: list[dict]) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for c in calls:
        if not c["ticker"]:
            continue
        groups.setdefault(c["ticker"], []).append(c)
    out = []
    for ticker, rows in groups.items():
        rows.sort(key=lambda r: r["report_date"] or "")
        tps = [r["target_price"] for r in rows if r.get("target_price")]
        ratings = [r["rating"] for r in rows if r.get("rating")]
        bulls = sum(1 for r in ratings if r in scoring.BULLISH)
        bears = sum(1 for r in ratings if r in scoring.BEARISH)
        out.append({
            "ticker": ticker,
            "company": rows[-1]["company"],
            "sector": rows[-1]["sector"],
            "n_calls": len(rows),
            "consensus": ("Bullish" if bulls > bears else
                          "Bearish" if bears > bulls else "Mixed"),
            "avg_target": round(statistics.mean(tps), 1) if tps else None,
            "target_spread": [min(tps), max(tps)] if tps else None,
            "calls": rows,
        })
    out.sort(key=lambda s: -s["n_calls"])
    return out


def render() -> Path:
    data = load_data()
    SITE_DIR.mkdir(parents=True, exist_ok=True)
    html = TEMPLATE.replace("/*DATA*/", json.dumps(data, default=str))
    out = SITE_DIR / "index.html"
    out.write_text(html, encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Analyst Rating &amp; Tracker</title>
<style>
  :root{
    --bg:#0f1115; --panel:#171a21; --panel2:#1e222b; --line:#2a2f3a;
    --txt:#e6e8ec; --mut:#9aa3b2; --acc:#4f9cf9; --good:#38b26b;
    --bad:#e0555b; --warn:#e0a63b;
  }
  @media (prefers-color-scheme: light){
    :root{--bg:#f6f7f9;--panel:#fff;--panel2:#f0f2f5;--line:#e2e5ea;
      --txt:#1a1d23;--mut:#5c6570;--acc:#2563eb;--good:#188a4e;--bad:#c0343a;--warn:#b5791f;}
  }
  *{box-sizing:border-box}
  body{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
    background:var(--bg);color:var(--txt);-webkit-font-smoothing:antialiased}
  header{padding:22px 20px 10px;max-width:1100px;margin:0 auto}
  h1{font-size:22px;margin:0 0 2px}
  .sub{color:var(--mut);font-size:13px}
  .wrap{max-width:1100px;margin:0 auto;padding:0 20px 60px}
  .tabs{display:flex;gap:6px;flex-wrap:wrap;margin:18px 0 14px;position:sticky;top:0;
    background:var(--bg);padding:8px 0;z-index:5}
  .tab{padding:7px 14px;border-radius:20px;border:1px solid var(--line);
    background:var(--panel);color:var(--mut);cursor:pointer;font-size:13px}
  .tab.on{background:var(--acc);color:#fff;border-color:var(--acc)}
  .card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
    margin-bottom:10px;overflow:hidden}
  .row{display:flex;align-items:center;gap:12px;padding:13px 15px;cursor:pointer}
  .row:hover{background:var(--panel2)}
  .grade{width:34px;height:34px;border-radius:9px;display:flex;align-items:center;
    justify-content:center;font-weight:700;font-size:15px;flex:0 0 auto}
  .gA{background:rgba(56,178,107,.18);color:var(--good)}
  .gB{background:rgba(79,156,249,.18);color:var(--acc)}
  .gC{background:rgba(224,166,59,.18);color:var(--warn)}
  .gD,.gF{background:rgba(224,85,91,.18);color:var(--bad)}
  .gNR{background:var(--panel2);color:var(--mut)}
  .nm{font-weight:600}.mut{color:var(--mut);font-size:12.5px}
  .spacer{flex:1}
  .score{font-size:20px;font-weight:700}
  .metrics{display:flex;gap:16px;flex-wrap:wrap}
  .metric{text-align:right}.metric .v{font-weight:600}.metric .k{font-size:11px;color:var(--mut)}
  .detail{display:none;padding:4px 15px 16px;border-top:1px solid var(--line);
    background:var(--panel2)}
  .detail.on{display:block}
  .chip{display:inline-block;padding:2px 8px;border-radius:12px;font-size:11px;
    margin:2px 4px 2px 0;border:1px solid var(--line)}
  .chip.flag{background:rgba(224,85,91,.13);color:var(--bad);border-color:transparent}
  .chip.warnflag{background:rgba(224,166,59,.14);color:var(--warn);border-color:transparent}
  .call{border-top:1px solid var(--line);padding:11px 0}
  .call:first-child{border-top:0}
  .pos{color:var(--good)}.neg{color:var(--bad)}
  .badge{font-size:11px;padding:2px 7px;border-radius:6px;border:1px solid var(--line)}
  .buy{color:var(--good)}.sell{color:var(--bad)}.hold{color:var(--warn)}
  .thesis{color:var(--txt);font-size:13.5px;margin:6px 0}
  .lbl{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em;margin-top:8px}
  ul.tight{margin:4px 0;padding-left:18px}ul.tight li{margin:2px 0;font-size:13px}
  .tl{display:flex;gap:8px;overflow-x:auto;padding:6px 0}
  .tlpt{min-width:130px;background:var(--panel);border:1px solid var(--line);
    border-radius:9px;padding:8px 10px;font-size:12px}
  .empty{color:var(--mut);text-align:center;padding:40px}
  .search{width:100%;padding:9px 12px;border-radius:9px;border:1px solid var(--line);
    background:var(--panel);color:var(--txt);margin-bottom:10px;font-size:14px}
  .prov{font-size:11px;color:var(--warn)}
</style>
</head>
<body>
<header>
  <h1>Analyst Rating &amp; Tracker</h1>
  <div class="sub" id="sub"></div>
</header>
<div class="wrap">
  <div class="tabs" id="tabs"></div>
  <input class="search" id="search" placeholder="Filter…">
  <div id="view"></div>
</div>
<script>
const DATA = /*DATA*/;
const $=(s,e=document)=>e.querySelector(s);
const pct=x=>x==null?"–":(x*100).toFixed(1)+"%";
const money=x=>x==null?"–":"₹"+Number(x).toLocaleString("en-IN");
const cls=x=>x==null?"":x>=0?"pos":"neg";
const gcl=g=>"g"+(g||"NR");
const ratingClass=r=>({BUY:"buy",ADD:"buy",ACCUMULATE:"buy",SELL:"sell",REDUCE:"sell",
  HOLD:"hold",NEUTRAL:"hold"}[r]||"");
let TAB="analysts", Q="";

$("#sub").textContent =
  `${DATA.counts.reports} reports · ${DATA.counts.calls} calls · `+
  `${DATA.counts.analysts} analysts · ${DATA.counts.market_reports} market notes · `+
  `updated ${DATA.generated_at}`;

const TABS=[["analysts","Analysts"],["stocks","Stocks"],["brokers","Brokers"],
  ["market","Market notes"]];
const tabsEl=$("#tabs");
TABS.forEach(([k,label])=>{
  const b=document.createElement("div");
  b.className="tab"+(k===TAB?" on":"");b.textContent=label;
  b.onclick=()=>{TAB=k;[...tabsEl.children].forEach(c=>c.classList.remove("on"));
    b.classList.add("on");Q="";$("#search").value="";render();};
  tabsEl.appendChild(b);
});
$("#search").oninput=e=>{Q=e.target.value.toLowerCase();render();};

function flagChip(f){
  const warn=["low-sample"].includes(f);
  return `<span class="chip ${warn?'warnflag':'flag'}">${f}</span>`;
}

function callBlock(c){
  const est=Object.entries(c.estimates||{}).map(([k,v])=>`${k}: ${v}`).join(" · ");
  const prov=c.status==="open"?`<span class="prov">● open (provisional)</span>`:"";
  return `<div class="call">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <span class="badge ${ratingClass(c.rating)}">${c.rating_raw||c.rating||"–"}</span>
      <b>${c.company||c.ticker||"?"}</b>
      <span class="mut">${c.report_date||""} · ${c.analyst} · ${c.broker}</span>
      ${prov}
    </div>
    <div class="mut" style="margin-top:4px">
      CMP ${money(c.cmp)} → Target ${money(c.target_price)}
      ${c.prior_target?`<span class="mut">(was ${money(c.prior_target)})</span>`:""}
      · ${c.horizon_months||12}m horizon</div>
    ${c.thesis?`<div class="thesis">${c.thesis}</div>`:""}
    <div class="metrics" style="margin-top:6px;justify-content:flex-start">
      <div class="metric" style="text-align:left"><div class="k">Target hit</div>
        <div class="v">${c.tp_hit==null?"–":c.tp_hit?("Yes · "+(c.tp_hit_date||"")):"No"}</div></div>
      <div class="metric" style="text-align:left"><div class="k">Return</div>
        <div class="v ${cls(c.stock_return)}">${pct(c.stock_return)}</div></div>
      <div class="metric" style="text-align:left"><div class="k">Alpha vs Nifty</div>
        <div class="v ${cls(c.alpha)}">${pct(c.alpha)}</div></div>
      <div class="metric" style="text-align:left"><div class="k">Max drawdown</div>
        <div class="v ${cls(c.max_drawdown)}">${pct(c.max_drawdown)}</div></div>
    </div>
    ${c.drivers&&c.drivers.length?`<div class="lbl">Drivers</div><ul class="tight">${c.drivers.map(d=>`<li>${d}</li>`).join("")}</ul>`:""}
    ${c.risks&&c.risks.length?`<div class="lbl">Risks</div><ul class="tight">${c.risks.map(d=>`<li>${d}</li>`).join("")}</ul>`:""}
    ${est?`<div class="lbl">Estimates</div><div class="mut">${est}</div>`:""}
  </div>`;
}

function personCard(a){
  const m=[`<div class="metric"><div class="v">${a.n}</div><div class="k">calls</div></div>`];
  if(a.hit_rate!=null)m.push(`<div class="metric"><div class="v">${pct(a.hit_rate)}</div><div class="k">target hit</div></div>`);
  if(a.direction_rate!=null)m.push(`<div class="metric"><div class="v">${pct(a.direction_rate)}</div><div class="k">direction</div></div>`);
  if(a.beat_market!=null)m.push(`<div class="metric"><div class="v">${pct(a.beat_market)}</div><div class="k">beat Nifty</div></div>`);
  if(a.avg_alpha!=null)m.push(`<div class="metric"><div class="v ${cls(a.avg_alpha)}">${pct(a.avg_alpha)}</div><div class="k">avg alpha</div></div>`);
  return `<div class="card">
    <div class="row" onclick="this.nextElementSibling.classList.toggle('on')">
      <div class="grade ${gcl(a.grade)}">${a.grade}</div>
      <div><div class="nm">${a.name}</div>
        <div class="mut">${a.confidence} confidence${a.flags.length?' · '+a.flags.map(flagChip).join(''):''}</div></div>
      <div class="spacer"></div>
      <div class="metrics">${m.join("")}</div>
      <div class="score">${a.score==null?'–':a.score}</div>
    </div>
    <div class="detail">${a.calls.map(callBlock).join("")}</div>
  </div>`;
}

function stockCard(s){
  const cons=s.consensus==="Bullish"?"buy":s.consensus==="Bearish"?"sell":"hold";
  return `<div class="card">
    <div class="row" onclick="this.nextElementSibling.classList.toggle('on')">
      <div><div class="nm">${s.company||s.ticker}</div>
        <div class="mut">${s.ticker} · ${s.sector||""}</div></div>
      <div class="spacer"></div>
      <div class="metrics">
        <div class="metric"><div class="v badge ${cons}">${s.consensus}</div><div class="k">consensus</div></div>
        <div class="metric"><div class="v">${s.n_calls}</div><div class="k">calls</div></div>
        <div class="metric"><div class="v">${s.avg_target?money(s.avg_target):'–'}</div><div class="k">avg target</div></div>
      </div>
    </div>
    <div class="detail">
      <div class="lbl">Coverage timeline</div>
      <div class="tl">${s.calls.map(c=>`<div class="tlpt">
        <div class="mut">${c.report_date||''}</div>
        <b class="${ratingClass(c.rating)}">${c.rating||'–'}</b>
        <div>${money(c.target_price)}</div>
        <div class="mut">${c.broker}</div></div>`).join("")}</div>
      ${s.calls.map(callBlock).join("")}
    </div>
  </div>`;
}

function marketCard(m){
  return `<div class="card">
    <div class="row" onclick="this.nextElementSibling.classList.toggle('on')">
      <div><div class="nm">${m.theme||'Market note'}</div>
        <div class="mut">${m.broker||''} · ${m.date||''}</div></div>
      <div class="spacer"></div>
      <div class="mut">${(m.sectors||[]).slice(0,3).join(", ")}</div>
    </div>
    <div class="detail">
      ${m.summary?`<div class="lbl">Summary</div><div class="thesis">${m.summary}</div>`:""}
      ${m.outlook?`<div class="lbl">Outlook</div><div class="thesis">${m.outlook}</div>`:""}
      ${m.key_points&&m.key_points.length?`<div class="lbl">Key points</div><ul class="tight">${m.key_points.map(p=>`<li>${p}</li>`).join("")}</ul>`:""}
    </div>
  </div>`;
}

function render(){
  const v=$("#view");
  let items=[],html="";
  if(TAB==="analysts"){
    items=DATA.analysts.filter(a=>a.name.toLowerCase().includes(Q));
    html=items.map(personCard).join("");
  }else if(TAB==="brokers"){
    items=DATA.brokers.filter(a=>a.name.toLowerCase().includes(Q));
    html=items.map(personCard).join("");
  }else if(TAB==="stocks"){
    items=DATA.stocks.filter(s=>(s.company||"").toLowerCase().includes(Q)||
      (s.ticker||"").toLowerCase().includes(Q));
    html=items.map(stockCard).join("");
  }else{
    items=DATA.market.filter(m=>((m.theme||"")+(m.broker||"")).toLowerCase().includes(Q));
    html=items.map(marketCard).join("");
  }
  v.innerHTML=html||`<div class="empty">Nothing here yet.</div>`;
}
render();
</script>
</body>
</html>"""


if __name__ == "__main__":
    print("Wrote", render())
