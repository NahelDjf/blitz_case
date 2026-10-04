#!/usr/bin/env python3
"""Generate app.html - a self-contained decision tool with the data baked in.

Three views over one detail panel:

  Matrix      convertibility against market opportunity, one screen
  List        the same mechanics as a sortable-by-score table
  Eliminated  the mechanics that failed a gate, and which gate they failed

Eliminated is a view rather than a strip below the matrix because a section
below the fold cannot share a detail panel that sits above it - selecting a
mechanic there meant scrolling up to read it. As a view, nothing scrolls.

Why a static file rather than a server: "a working application, easy to run
locally" is a grading criterion, and nothing is easier than a file that opens
on a double-click. The only logic duplicated in JavaScript is the final
weighted sum - four multiplications - so the scoring cannot drift between
Python and the page.

Colour and type follow Blitz's own site: deep violet ground, gold from the
logo, and the green/pink pairing from their fairness chart where green is
"You" and pink is an opponent.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from common import DATA_DIR, read_jsonl

OUT_PATH = Path(__file__).resolve().parents[1] / "app.html"
MAX_QUOTES = 3


def build_payload() -> dict:
    rubric = json.loads((DATA_DIR / "rubric.json").read_text(encoding="utf-8"))
    scores = read_jsonl(DATA_DIR / "mechanics" / "scores.jsonl")
    metadata = {r["app_id"]: r for r in read_jsonl(DATA_DIR / "apps" / "metadata.jsonl")}
    mechanics = {r["mechanic_id"]: r for r in read_jsonl(DATA_DIR / "mechanics" / "mechanics.jsonl")}

    voice_by_app = {}
    for path in (DATA_DIR / "voice").glob("*.json"):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("sufficient"):
            voice_by_app[record["app_id"]] = record

    dimension_meta = {
        d["id"]: {"label": d["label"], "type": d["type"], "weight": d.get("weight")}
        for d in rubric["dimensions"]
    }
    for flag in rubric["risk_flags"]:
        dimension_meta[flag["id"]] = {"label": flag["label"], "type": "flag", "weight": None}

    rows = []
    for row in scores:
        mech = mechanics.get(row["mechanic_id"], {})
        cash_names = set(mech.get("cash_carrier_names") or [])
        carriers = []
        for app_id in row["app_ids"]:
            app = metadata.get(app_id)
            if not app:
                continue
            carriers.append(
                {
                    "name": app.get("trackName"),
                    "ratings": app.get("userRatingCount") or 0,
                    "cash": app.get("trackName") in cash_names,
                }
            )
        carriers.sort(key=lambda c: -c["ratings"])

        quotes, seen = [], set()
        for app_id in row["app_ids"]:
            record = voice_by_app.get(app_id)
            if not record:
                continue
            for label in ("unfair", "ads", "paywall", "wants_competition"):
                if label in seen:
                    continue
                for example in (record.get("examples") or {}).get(label, [])[:1]:
                    text = (example.get("quote") or "").strip()
                    if len(text) > 40:
                        seen.add(label)
                        quotes.append(
                            {
                                "label": label,
                                "text": text,
                                "app": (metadata.get(app_id) or {}).get("trackName"),
                            }
                        )
            if len(quotes) >= MAX_QUOTES:
                break

        rows.append({**row, "carrier_apps": carriers[:8], "quotes": quotes[:MAX_QUOTES]})

    return {
        "snapshot": scores[0]["snapshot_date"] if scores else "",
        "dimensionMeta": dimension_meta,
        "defaultWeights": scores[0]["weights"] if scores else {},
        "rows": rows,
    }


CSS = """
:root{
  /* Blitz's palette: their panel violet as the ground - the site's full
     #6322E8 is built for large marketing type, not dense data - gold from the
     logo as the accent, and the green/pink pairing from their own fairness
     chart, where green is "You" and pink is an opponent. */
  --bg:#1A0847; --panel:#24105E; --raise:#2F1878; --line:#412A8E;
  --ink:#FCFCFA; --muted:#B6A8E0; --dim:#8878C4;
  --accent:__ACCENT__; --rival:#FF6B8A; --mine:#5BE49B;
  --head:"Barlow Condensed",ui-sans-serif,system-ui,sans-serif;
  --body:"Archivo",ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:var(--body);font-size:14px;
  line-height:1.5;-webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
h1,h2,h3{font-family:var(--head);text-transform:uppercase;letter-spacing:.01em;font-weight:700;line-height:1}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px}

.top{border-bottom:1px solid var(--line);padding:18px 24px;display:flex;gap:28px;
  align-items:center;flex-wrap:wrap}
.top h1{font-size:26px}
.top h1 em{font-style:normal;color:var(--accent)}
.sub{color:var(--muted);font-size:12.5px;max-width:62ch;margin-top:5px}
.tallies{display:flex;gap:22px;margin-left:auto}
.tallies div{text-align:right}
.tallies b{font-family:var(--head);font-size:26px;display:block;line-height:1}
.tallies span{color:var(--dim);font-size:11px}
.tallies .a b{color:var(--accent)} .tallies .r b{color:var(--rival)}

.bar{display:flex;gap:20px;align-items:center;padding:10px 24px;
  border-bottom:1px solid var(--line);flex-wrap:wrap}
.bar .lbl{color:var(--dim);font-size:12px}
.ctl{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--muted)}
.ctl input{width:84px;accent-color:var(--accent)}
.ctl b{color:var(--ink);font-weight:500;min-width:28px;font-size:12px}
.reset{border:1px solid var(--line);color:var(--muted);padding:4px 11px;font-size:11.5px}
.reset:hover{color:var(--ink);border-color:var(--dim)}
.views{margin-left:auto;display:flex;border:1px solid var(--line)}
.views button{padding:5px 13px;font-size:12px;color:var(--muted)}
.views button.on{background:var(--accent);color:#1A0847;font-weight:600}

.main{display:grid;grid-template-columns:1fr 400px;min-height:calc(100vh - 136px)}
.left{padding:14px 24px 24px;border-right:1px solid var(--line);overflow:auto}
.right{padding:20px;background:var(--panel);overflow:auto;max-height:calc(100vh - 136px)}
@media(max-width:980px){.main{grid-template-columns:1fr}.right{max-height:none;border-top:1px solid var(--line)}}

.legend{display:flex;gap:18px;flex-wrap:wrap;align-items:center;padding:9px 12px;
  margin-bottom:12px;border:1px solid var(--line);font-size:11.5px;color:var(--dim)}
.legend span{display:flex;align-items:center;gap:6px}
.legend i{width:9px;height:9px;border-radius:50%;display:inline-block}
.legend .sz i:first-child{width:5px;height:5px;background:var(--dim)}
.legend .sz i:nth-child(2){width:11px;height:11px;background:var(--dim)}
.legend b{color:var(--muted);font-weight:500;border:1px solid var(--line);padding:0 5px}

svg{width:100%;height:auto;display:block}
.gridline{stroke:var(--line);stroke-width:1}
.axlab{fill:var(--dim);font-size:10.5px;font-family:var(--body)}
.zone{fill:var(--dim);font-size:10px;font-family:var(--head);text-transform:uppercase;letter-spacing:.06em;opacity:.7}
.dot{cursor:pointer;stroke:var(--bg);stroke-width:1.5}
.dot.sel{stroke:var(--ink);stroke-width:2.5}
.dlab{fill:var(--muted);font-size:10px;pointer-events:none;font-family:var(--body)}
.dlab.on{fill:var(--ink)}
.foot{color:var(--dim);font-size:12px;margin-top:12px;border-top:1px solid var(--line);padding-top:11px}
.foot button{color:var(--accent);text-decoration:underline;text-underline-offset:2px}

.intro{color:var(--muted);font-size:12.5px;margin-bottom:12px;max-width:85ch;line-height:1.55}
.intro b{color:var(--ink);font-weight:500}
table{width:100%;border-collapse:collapse;font-size:13px}
th{text-align:left;color:var(--dim);font-weight:400;font-size:11px;padding:6px 8px;
  border-bottom:1px solid var(--line)}
th.n,td.n{text-align:right}
td{padding:7px 8px;border-bottom:1px solid var(--line);cursor:pointer}
tr:hover td{background:var(--raise)}
tr.sel td{background:var(--raise)}
tr.out td{color:var(--dim)}
.sval{color:var(--accent);font-weight:600}
.gate{color:var(--rival);font-size:12px}
.pill{font-size:10.5px;padding:1px 6px;border:1px solid currentColor;margin-left:6px}
.pill.rival{color:var(--rival)} .pill.mine{color:var(--mine)} .pill.thin{color:var(--dim)}

.dh{border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:14px}
.dh h2{font-size:22px}
.dh .verdict{font-size:11.5px;margin-top:5px;color:var(--accent)}
.dh .verdict.no{color:var(--rival)}
.nums{display:flex;gap:16px;margin-top:12px}
.nums div b{font-family:var(--head);font-size:21px;display:block;line-height:1}
.nums div span{color:var(--dim);font-size:10.5px}
h4{font-size:11px;color:var(--dim);font-weight:400;margin:18px 0 7px;
  text-transform:uppercase;letter-spacing:.05em}
.dim{display:grid;grid-template-columns:1fr 58px;gap:8px;padding:7px 0;border-top:1px solid var(--line)}
.dim .dn{font-size:12.5px}
.dim .dj{color:var(--muted);font-size:11.5px;margin-top:2px;line-height:1.45}
.pips{display:flex;gap:3px;justify-content:flex-end;align-items:center;height:14px}
.pips u{width:6px;height:6px;background:var(--line);text-decoration:none}
.pips u.on{background:var(--accent)}
.pips.gate u.on{background:var(--mine)}
.pips.fail u.on{background:var(--rival)}
.sp{color:var(--dim);font-size:10px;text-align:right;margin-top:2px}
.app{display:flex;justify-content:space-between;gap:8px;padding:4px 0;font-size:12.5px;
  border-top:1px solid var(--line)}
.app span{color:var(--dim);font-size:11px}
.app.cash{color:var(--rival)}
blockquote{border-left:2px solid var(--line);padding-left:11px;margin-bottom:9px;
  color:var(--muted);font-size:12px;line-height:1.45}
blockquote cite{display:block;color:var(--dim);font-size:10.5px;font-style:normal;margin-top:3px}
.gatebox{background:var(--raise);border-left:3px solid var(--rival);padding:11px;
  font-size:12.5px;color:var(--muted);margin-bottom:14px}
"""

JS = """
const W={...DATA.defaultWeights}, META=DATA.dimensionMeta;
let view="matrix", sel=null;
const esc=s=>String(s==null?"":s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function opp(r){
  const t=W.demand+W.openness+W.fatigue||1;
  return (W.demand*r.demand+W.openness*r.openness+W.fatigue*(r.fatigue||0))/t;
}
const score=r=>r.convertibility*opp(r);
const live=()=>DATA.rows.filter(r=>r.verdict==="VIABLE");
const dead=()=>DATA.rows.filter(r=>r.verdict!=="VIABLE");
const colour=r=>r.quadrant==="proven_by_competitor"?"var(--rival)"
  :r.quadrant==="already_operated"?"var(--mine)":"var(--accent)";
const gateNames=r=>(r.failed_gates||[]).map(g=>esc((META[g]||{}).label||g)).join(" and ");

const YMIN=0.5;  // nothing scores below this, so plotting 0-1 would waste half the chart

function matrixLegend(){
  return `<div class="legend">
    <span><i style="background:var(--accent)"></i>Open field</span>
    <span><i style="background:var(--rival)"></i>A rival runs it for cash</span>
    <span><i style="background:var(--mine)"></i>Blitz already runs it</span>
    <span class="sz"><i></i><i></i>Dot size = charting apps</span>
  </div>`;
}

function tableLegend(){
  return `<div class="legend">
    <span><b class="pill rival">rival</b> a competitor already runs it for cash</span>
    <span><b class="pill mine">yours</b> Blitz already operates it</span>
    <span><b class="pill thin">thin</b> fewer than 3 charting apps, so demand and openness are weakly evidenced</span>
    <span>Best rank = the highest US top-free position any app with this mechanic reached</span>
  </div>`;
}

function matrix(){
  const w=700,h=430,pl=46,pr=18,pt=22,pb=46;
  const X=v=>pl+v*(w-pl-pr);
  const Y=v=>h-pb-((Math.max(v,YMIN)-YMIN)/(1-YMIN))*(h-pt-pb);
  let s=`<svg viewBox="0 0 ${w} ${h}" role="img" aria-label="Mechanics plotted by convertibility against market opportunity">`;
  for(let i=0;i<=4;i++){
    const xv=i/4, yv=YMIN+(i/4)*(1-YMIN);
    s+=`<line class="gridline" x1="${pl}" x2="${w-pr}" y1="${Y(yv)}" y2="${Y(yv)}"/>`;
    s+=`<line class="gridline" x1="${X(xv)}" x2="${X(xv)}" y1="${pt}" y2="${h-pb}"/>`;
    s+=`<text class="axlab" x="${pl-8}" y="${Y(yv)+3}" text-anchor="end">${yv.toFixed(2)}</text>`;
    s+=`<text class="axlab" x="${X(xv)}" y="${h-pb+15}" text-anchor="middle">${xv.toFixed(1)}</text>`;
  }
  s+=`<text class="axlab" x="${pl}" y="${h-8}">Market opportunity: demand, open field, player frustration</text>`;
  s+=`<text class="axlab" transform="translate(13,${(h-pb+pt)/2}) rotate(-90)" text-anchor="middle">Convertibility: can Blitz run it?</text>`;
  s+=`<text class="zone" x="${w-pr-8}" y="${pt-6}" text-anchor="end">Act on these</text>`;
  s+=`<text class="zone" x="${pl}" y="${pt-6}">Convertible, quiet market</text>`;

  const rows=live().slice().sort((a,b)=>b.carriers-a.carriers);
  const placed=[]; let dots="",labels="";
  for(const r of rows){
    const x=X(opp(r)), y=Y(r.convertibility), rad=4+Math.min(r.carriers,10)*0.7;
    const on=sel===r.mechanic_id;
    dots+=`<circle class="dot ${on?"sel":""}" cx="${x}" cy="${y}" r="${rad}"
      fill="${colour(r)}" fill-opacity="${on?1:.8}" data-id="${r.mechanic_id}"><title>${esc(r.label)}</title></circle>`;
    if(!(on||r.cash_carriers>0||r.carriers>=5)) continue;
    let ly=y+3;
    while(placed.some(p=>Math.abs(p.y-ly)<11&&Math.abs(p.x-x)<190)) ly+=11;
    placed.push({x,y:ly});
    labels+=`<text class="dlab ${on?"on":""}" x="${x+rad+5}" y="${ly}">${esc(r.label)}</text>`;
  }
  return matrixLegend()+s+dots+labels+"</svg>"
    +`<p class="foot">${dead().length} more mechanics were eliminated at a gate and cannot be plotted -
       a mechanic that can't be run fairly has no convertibility.
       <button data-v="killed">See which gate each one failed</button></p>`;
}

function list(){
  const rows=[...live().sort((a,b)=>score(b)-score(a))];
  return tableLegend()+`<table><thead><tr><th>Mechanic</th><th class="n">Apps</th>
    <th class="n">Best rank</th><th class="n">Convertibility</th>
    <th class="n">Opportunity</th><th class="n">Score</th></tr></thead><tbody>`
    + rows.map(r=>`<tr class="${sel===r.mechanic_id?"sel":""}" data-id="${r.mechanic_id}">
      <td>${esc(r.label)}${r.cash_carriers?'<span class="pill rival">rival</span>':""}${
        r.quadrant==="already_operated"?'<span class="pill mine">yours</span>':""}${
        r.evidence_tier==="watchlist"?'<span class="pill thin">thin</span>':""}</td>
      <td class="n">${r.carriers}</td><td class="n">${r.best_rank_free?"#"+r.best_rank_free:"—"}</td>
      <td class="n">${r.convertibility.toFixed(2)}</td>
      <td class="n">${opp(r).toFixed(2)}</td>
      <td class="n sval">${score(r).toFixed(3)}</td>
    </tr>`).join("")+"</tbody></table>";
}

function killedView(){
  const rows=dead().sort((a,b)=>b.demand-a.demand);
  return `<p class="intro">Two of the eight rubric dimensions are <b>gates</b> rather than weights.
    <b>Symmetric randomness</b> asks whether both players can be handed an identical instance, so luck
    cancels and the score gap is skill. <b>Score comparability</b> asks whether a round produces a single
    number that can be ranked against an opponent's. Failing either one disqualifies a mechanic outright,
    however popular it is - these are not low scores, they are structural blockers.
    Sorted by the demand each would have scored on: this is roughly what a generic App Store trends tool
    would put at the top of its recommendations.</p>
    <table><thead><tr><th>Mechanic</th><th class="n">Apps</th>
    <th class="n">Best rank</th><th class="n">Demand</th><th>Blocked by</th></tr></thead><tbody>`
    + rows.map(r=>`<tr class="out ${sel===r.mechanic_id?"sel":""}" data-id="${r.mechanic_id}">
      <td>${esc(r.label)}</td><td class="n">${r.carriers}</td>
      <td class="n">${r.best_rank_free?"#"+r.best_rank_free:"—"}</td><td class="n">${r.demand.toFixed(2)}</td>
      <td class="gate">${gateNames(r)}</td></tr>`).join("")+"</tbody></table>";
}

function detail(){
  const r=DATA.rows.find(x=>x.mechanic_id===sel);
  if(!r) return `<p style="color:var(--dim)">Select a mechanic to see why it scored what it did.</p>`;
  const ok=r.verdict==="VIABLE";

  const gate=ok?"":`<div class="gatebox">Eliminated at the ${gateNames(r)} gate.
    It scored ${r.demand.toFixed(2)} on demand, which changes nothing - a mechanic that can't be run
    fairly isn't partly convertible.</div>`;

  const dims=Object.entries(r.dimensions||{}).map(([k,d])=>{
    const m=META[k]||{label:k,type:"weighted"};
    const failed=(r.failed_gates||[]).includes(k);
    return `<div class="dim"><div>
      <div class="dn">${esc(m.label)}${m.type==="gate"?" - gate":(m.weight?` - weight ${m.weight}`:" - risk")}</div>
      <div class="dj">${esc(d.justification)}</div></div>
      <div><span class="pips ${failed?"fail":(m.type==="gate"?"gate":"")}">${
        [1,2,3,4,5].map(i=>`<u class="${i<=d.score?"on":""}"></u>`).join("")}</span>
      ${d.spread>1?`<div class="sp">spread ${d.spread}</div>`:""}</div></div>`;
  }).join("");

  const apps=(r.carrier_apps||[]).map(c=>`<div class="app ${c.cash?"cash":""}">
    <span style="color:inherit">${esc(c.name)}${c.cash?" - cash":""}</span>
    <span>${c.ratings.toLocaleString()} ratings</span></div>`).join("");

  const quotes=(r.quotes||[]).map(q=>`<blockquote>${esc(q.text)}…
    <cite>${esc(q.label)} - ${esc(q.app)}</cite></blockquote>`).join("")
    || `<p style="color:var(--dim);font-size:12px">No carrier cleared the 50-review threshold.</p>`;

  const v=r.voice_rates||{}, pct=x=>x==null?"—":Math.round(x*100)+"%";

  return `<div class="dh"><h2>${esc(r.label)}</h2>
    <div class="verdict ${ok?"":"no"}">${ok?"Could be run as a tournament":"Eliminated at a gate"}
      - ${r.carriers} charting app${r.carriers>1?"s":""}
      ${r.cash_carriers?` - ${r.cash_carriers} rival already runs it for cash`:""}
      ${r.convertibility_confidence?` - ${r.convertibility_confidence} confidence`:""}</div>
    <div class="nums">
      <div><b style="color:${ok?"var(--accent)":"var(--dim)"}">${ok?score(r).toFixed(3):"—"}</b><span>score</span></div>
      <div><b>${ok?r.convertibility.toFixed(2):"0"}</b><span>convertibility</span></div>
      <div><b>${r.demand.toFixed(2)}</b><span>demand</span></div>
      <div><b>${r.openness.toFixed(2)}</b><span>open field</span></div>
      <div><b>${r.fatigue==null?"—":r.fatigue.toFixed(2)}</b><span>frustration</span></div>
    </div></div>
    ${gate}
    <h4>Rubric</h4>${dims}
    <h4>Charting apps</h4>${apps}
    <h4>Player complaints - ${pct(v.ads)} ads, ${pct(v.paywall)} paywall, ${pct(v.unfair)} unfair</h4>${quotes}`;
}

function render(keepScroll){
  const panel=document.getElementById("right");
  const y=panel.scrollTop;
  document.getElementById("left").innerHTML =
    view==="matrix" ? matrix() : view==="list" ? list() : killedView();
  panel.innerHTML = detail();
  // Choosing a different mechanic means reading from the top, not from
  // wherever the previous one's panel happened to be scrolled to.
  panel.scrollTop = keepScroll ? y : 0;
}

function setView(v){
  view=v;
  document.querySelectorAll(".views button").forEach(b=>b.classList.toggle("on",b.dataset.v===v));
  render(true);
}

document.addEventListener("click",e=>{
  const v=e.target.closest("[data-v]");
  if(v){ setView(v.dataset.v); return; }
  const hit=e.target.closest("[data-id]");
  if(hit){ sel=hit.dataset.id; render(false); }
});
document.querySelectorAll(".ctl input").forEach(i=>i.addEventListener("input",()=>{
  W[i.dataset.k]=+i.value/100;
  i.nextElementSibling.textContent=(+i.value/100).toFixed(2);
  render(true);
}));
document.querySelector(".reset").addEventListener("click",()=>{
  Object.assign(W,DATA.defaultWeights);
  document.querySelectorAll(".ctl input").forEach(i=>{
    i.value=DATA.defaultWeights[i.dataset.k]*100;
    i.nextElementSibling.textContent=DATA.defaultWeights[i.dataset.k].toFixed(2);
  });
  render(true);
});

sel = live().sort((a,b)=>score(b)-score(a))[0]?.mechanic_id || null;
render(false);
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the static interface.")
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--name", default="GameSonar", help="product name shown in the title")
    parser.add_argument("--accent", default="#FFC63A", help="Blitz accent colour, hex")
    args = parser.parse_args()

    payload = build_payload()
    if not payload["rows"]:
        print("No scores found. Run build_scores.py first.", file=sys.stderr)
        return 1

    live = [r for r in payload["rows"] if r["verdict"] == "VIABLE"]
    dead = [r for r in payload["rows"] if r["verdict"] != "VIABLE"]
    rivals = [r for r in live if r["quadrant"] == "proven_by_competitor"]

    try:
        snap = date.fromisoformat(payload["snapshot"]).strftime("%m/%d/%Y")
    except ValueError:
        snap = payload["snapshot"]

    title = f"{args.name} - Identifying emerging mechanics or genres"
    weights = payload["defaultWeights"]
    controls = "".join(
        f'<label class="ctl">{label}'
        f'<input type="range" min="0" max="100" value="{int(weights[key] * 100)}" data-k="{key}">'
        f"<b>{weights[key]:.2f}</b></label>"
        for key, label in (("demand", "Demand"), ("openness", "Open field"), ("fatigue", "Frustration"))
    )

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=Barlow+Condensed:wght@600;700&display=swap">
<style>{CSS.replace("__ACCENT__", args.accent)}</style></head><body>

<header class="top">
  <div>
    <h1><em>{args.name}</em> - Identifying emerging mechanics or genres</h1>
    <p class="sub">Every game mechanic in the US top 100, {snap}, scored on whether two players could
      compete fairly and then on the market opportunity it represents.</p>
  </div>
  <div class="tallies">
    <div class="a"><b>{len(live)}</b><span>could be run</span></div>
    <div><b>{len(dead)}</b><span>fail a gate</span></div>
    <div class="r"><b>{len(rivals)}</b><span>a rival already runs</span></div>
  </div>
</header>

<div class="bar">
  <span class="lbl">What matters to you</span>{controls}
  <button class="reset">Reset</button>
  <div class="views">
    <button data-v="matrix" class="on">Matrix</button>
    <button data-v="list">List</button>
    <button data-v="killed">Eliminated ({len(dead)})</button>
  </div>
</div>

<div class="main"><div class="left" id="left"></div><div class="right" id="right"></div></div>

<script>const DATA = {json.dumps(payload, ensure_ascii=False)};</script>
<script>{JS}</script>
</body></html>
"""

    Path(args.out).write_text(html, encoding="utf-8")
    print(
        f"{args.out} written ({Path(args.out).stat().st_size / 1024:.0f} KB, "
        f"{len(live)} viable / {len(dead)} eliminated). Open it by double-clicking.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
