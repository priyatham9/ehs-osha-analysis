"""Build docs/ontology_explorer.html, a static Workshop-style page over the ontology.

The page is one self-contained file (no CDN, no network) that embeds a compact
JSON of committed data only:

    src/ehs_osha/ontology/spec.json      object types, link types, actions, functions
    outputs/tables/quality_by_year.csv   ReportingYear
    outputs/tables/metrics_by_year.csv   ReportingYear rates and function outputs
    outputs/tables/quality_by_naics2.csv Sector
    outputs/tables/peer_percentiles_pooled.csv  PeerGroup, Industry
    outputs/tables/quality_flag_prevalence.csv  QualityFlag
    outputs/tables/detectability_by_size_band.csv  size-band aggregate TRIR

Establishment and Filing objects are not embedded: they need establishment-level
data, which is not committed. The page says so. Output is deterministic (no
timestamps), so a test can compare the committed page with a fresh build.

Usage::

    python scripts/build_ontology_explorer.py
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ehs_osha.naics import naics3_title  # noqa: E402

TABLES = ROOT / "outputs" / "tables"
SPEC = ROOT / "src" / "ehs_osha" / "ontology" / "spec.json"
OUT = ROOT / "docs" / "ontology_explorer.html"

DATA_MARKER = "/*__DATA__*/"


def _rows(name: str) -> list:
    with open(TABLES / name, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _f(v: str):
    """Parse a CSV float; an empty cell stays null (never imputed)."""
    return None if v == "" else float(v)


def _i(v: str):
    return None if v == "" else int(float(v))


def _table(cols: list, rows: list) -> dict:
    return {"cols": cols, "rows": rows}


def build_data() -> dict:
    """Assemble the embedded JSON payload from committed files only."""
    spec = json.loads(SPEC.read_text(encoding="utf-8"))

    qy = {_i(r["label"]): r for r in _rows("quality_by_year.csv")}
    my = {_i(r["label"]): r for r in _rows("metrics_by_year.csv")}
    year_cols = [
        "year", "n_filings", "n_implausible", "implausible_share", "hours_share_implausible",
        "aggregate_trir_unscreened", "aggregate_trir_screened", "ratio_screened_to_unscreened",
        "dart_unscreened", "dart_screened", "ltir_unscreened", "ltir_screened",
        "severity_unscreened", "severity_screened",
    ]
    years = []
    for y in sorted(qy):
        q, m = qy[y], my[y]
        years.append([
            y, _i(q["n_filings"]), _i(q["n_implausible"]),
            _f(q["implausible_share"]), _f(q["hours_share_implausible"]),
            _f(q["aggregate_trir_unscreened"]), _f(q["aggregate_trir_screened"]),
            _f(q["ratio_screened_to_unscreened"]),
            _f(m["dart_unscreened"]), _f(m["dart_screened"]),
            _f(m["ltir_unscreened"]), _f(m["ltir_screened"]),
            _f(m["severity_unscreened"]), _f(m["severity_screened"]),
        ])

    sector_cols = [
        "naics2", "n_filings", "implausible_share", "hours_share_implausible",
        "aggregate_trir_unscreened", "aggregate_trir_screened",
    ]
    sectors = [
        [r["label"], _i(r["n_filings"]), _f(r["implausible_share"]),
         _f(r["hours_share_implausible"]), _f(r["aggregate_trir_unscreened"]),
         _f(r["aggregate_trir_screened"])]
        for r in _rows("quality_by_naics2.csv")
    ]

    pg_cols = [
        "naics3", "size_band", "n", "n_with_metric", "zero_share", "aggregate_trir",
        "p10", "p25", "p50", "p75", "p90", "p95", "publishable",
    ]
    peers = _rows("peer_percentiles_pooled.csv")
    peer_groups = [
        [r["naics3"], r["size_band"], _i(r["n"]), _i(r["n_with_metric"]),
         _f(r["zero_share"]), _f(r["aggregate_trir"]),
         *[_f(r[p]) for p in ("p10", "p25", "p50", "p75", "p90", "p95")],
         r["publishable"] == "True"]
        for r in peers
    ]
    codes = sorted({r["naics3"] for r in peers})
    industries = [[c, naics3_title(c) or "", naics3_title(c) is not None, c[:2]] for c in codes]

    flags = [
        [r["flag"], _i(r["n"]), _f(r["share"]), _f(r["hours_share"])]
        for r in _rows("quality_flag_prevalence.csv")
    ]
    size_bands = [
        [r["size_band"], _i(r["n_filings"]), _f(r["aggregate_trir"])]
        for r in _rows("detectability_by_size_band.csv")
    ]

    return {
        "ontology": spec["ontology"],
        "object_types": spec["object_types"],
        "link_types": spec["link_types"],
        "action_types": spec["action_types"],
        "functions": spec["functions"],
        "tables": {
            "ReportingYear": _table(year_cols, years),
            "Sector": _table(sector_cols, sectors),
            "Industry": _table(["naics3", "title", "has_official_title", "naics2"], industries),
            "PeerGroup": _table(pg_cols, peer_groups),
            "QualityFlag": _table(["flag", "pooled_n", "pooled_share", "pooled_hours_share"], flags),
            "SizeBand": _table(["size_band", "n_filings", "aggregate_trir"], size_bands),
        },
        "sources": [
            "src/ehs_osha/ontology/spec.json",
            "outputs/tables/quality_by_year.csv",
            "outputs/tables/metrics_by_year.csv",
            "outputs/tables/quality_by_naics2.csv",
            "outputs/tables/peer_percentiles_pooled.csv",
            "outputs/tables/quality_flag_prevalence.csv",
            "outputs/tables/detectability_by_size_band.csv",
        ],
    }


def render() -> str:
    """Return the full page text for the current committed data."""
    payload = json.dumps(build_data(), separators=(",", ":"), sort_keys=True)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return PAGE.replace(DATA_MARKER, payload)


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ontology Explorer</title>
<style>
:root{--bg:#f6f7f9;--panel:#fff;--ink:#1c2430;--mut:#5b6675;--line:#d9dee5;--acc:#1f5fbf;--accbg:#e8f0fc;--warn:#8a5a00;--warnbg:#fff4d6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12161c;--panel:#1a2029;--ink:#e6eaf0;--mut:#9aa6b6;--line:#2c3542;--acc:#7fb0ff;--accbg:#1d2a40;--warn:#f0c46a;--warnbg:#3a2f12}}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}
header{padding:14px 16px;border-bottom:1px solid var(--line);background:var(--panel)}
h1{font-size:18px;margin:0 0 4px}h2{font-size:16px;margin:0 0 8px}h3{font-size:14px;margin:12px 0 6px}
.sub{color:var(--mut);font-size:13px}
nav{display:flex;gap:4px;flex-wrap:wrap;padding:8px 16px;background:var(--panel);border-bottom:1px solid var(--line)}
nav button{border:1px solid var(--line);background:var(--bg);color:var(--ink);padding:6px 12px;border-radius:6px;cursor:pointer;font:inherit}
nav button[aria-selected="true"]{background:var(--accbg);border-color:var(--acc);color:var(--acc)}
main{padding:16px;max-width:1200px;margin:0 auto}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px;margin-bottom:14px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.card{border:1px solid var(--line);border-radius:8px;padding:10px;background:var(--panel);cursor:pointer;text-align:left;font:inherit;color:inherit}
.card:hover{border-color:var(--acc)}
.tag{display:inline-block;font-size:12px;padding:1px 7px;border-radius:10px;background:var(--accbg);color:var(--acc);margin-right:4px}
.tag.warn{background:var(--warnbg);color:var(--warn)}
.note{background:var(--warnbg);color:var(--warn);padding:8px 10px;border-radius:6px;font-size:13px}
table{border-collapse:collapse;width:100%;font-size:13px}
th,td{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}
th{cursor:pointer;white-space:nowrap;position:sticky;top:0;background:var(--panel)}
.scroll{overflow:auto;max-height:480px}
tr.sel{background:var(--accbg)}
tr.row{cursor:pointer}
input,select{font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
a.lk,button.lk{color:var(--acc);background:none;border:0;padding:0;cursor:pointer;font:inherit;text-decoration:underline}
code{font-size:12px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media (max-width:800px){.two{grid-template-columns:1fr}}
</style>
</head>
<body>
<header>
<h1>OSHA ITA ontology explorer</h1>
<div class="sub">Static, read-only view of the ontology spec and the committed aggregate tables. No establishment-level data is included. Independent design in the style of a Foundry Workshop app; not affiliated with Palantir.</div>
</header>
<nav id="tabs" role="tablist"></nav>
<main id="view"></main>
<script id="data" type="application/json">/*__DATA__*/</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var T=D.tables;
var HAS={ReportingYear:1,Sector:1,Industry:1,PeerGroup:1,QualityFlag:1};
var KEY={ReportingYear:"year",Sector:"naics2",Industry:"naics3",QualityFlag:"flag"};
var state={tab:"types",type:"ReportingYear",q:"",sort:null,desc:false,sel:null,pgOnly:false,sector:"",size:""};

function el(tag,attrs,kids){var e=document.createElement(tag);
  for(var k in (attrs||{})){if(k==="text")e.textContent=attrs[k];else if(k.slice(0,2)==="on")e.addEventListener(k.slice(2),attrs[k]);else e.setAttribute(k,attrs[k]);}
  (kids||[]).forEach(function(c){e.appendChild(typeof c==="string"?document.createTextNode(c):c);});return e;}
function fmt(v,col){
  if(v===null||v===undefined)return "";
  if(typeof v==="boolean")return v?"yes":"no";
  if(typeof v==="number"){
    if(/share|zero_share/.test(col))return (v*100).toFixed(2)+"%";
    if(Number.isInteger(v))return v.toLocaleString("en-US");
    return v.toFixed(3);}
  return String(v);}
function objs(type){var t=T[type];return t.rows.map(function(r){var o={};t.cols.forEach(function(c,i){o[c]=r[i];});
  if(type==="PeerGroup")o.peer_group_key=o.naics3+"|"+o.size_band;
  if(type==="Sector")o.naics2=String(o.naics2);
  return o;});}
var CACHE={};function get(type){return CACHE[type]||(CACHE[type]=objs(type));}
function keyOf(type,o){return type==="PeerGroup"?o.peer_group_key:o[KEY[type]];}
function titleOf(type,o){
  if(type==="Industry")return o.naics3+(o.title?" "+o.title:" (no official title)");
  if(type==="PeerGroup")return o.naics3+" / "+o.size_band;
  if(type==="Sector")return "Sector "+o.naics2;
  if(type==="ReportingYear")return "Reporting year "+o.year;
  return keyOf(type,o);}
function typeDef(n){return D.object_types.filter(function(t){return t.api_name===n;})[0];}

function tabs(){
  var names=[["types","Object types"],["browse","Browse objects"],["links","Links"],["functions","Functions"],["actions","Actions"],["about","Sources"]];
  var nav=document.getElementById("tabs");nav.textContent="";
  names.forEach(function(n){nav.appendChild(el("button",{role:"tab","aria-selected":String(state.tab===n[0]),text:n[1],onclick:function(){state.tab=n[0];render();}}));});}

function typesView(v){
  v.appendChild(el("div",{"class":"panel"},[el("h2",{text:D.ontology.display_name+" (v"+D.ontology.version+")"}),el("div",{"class":"sub",text:D.ontology.description})]));
  var g=el("div",{"class":"grid"});
  D.object_types.forEach(function(t){
    var has=HAS[t.api_name];
    var n=has?T[t.api_name].rows.length+" committed objects":"no committed rows";
    g.appendChild(el("button",{"class":"card",onclick:function(){state.type=t.api_name;state.tab="browse";state.sel=null;state.q="";state.sort=null;render();}},[
      el("strong",{text:t.display_name}),el("div",{"class":"sub",text:t.properties.length+" properties, key "+t.primary_key}),
      el("div",{},[el("span",{"class":"tag"+(has?"":" warn"),text:n})]),
      el("div",{"class":"sub",text:t.description})]));});
  v.appendChild(g);
  v.appendChild(el("p",{"class":"note",text:"Establishment and Filing need establishment-level data, which is not committed to this repository. Their definitions are shown, but no objects are embedded."}));}

function propsTable(t){
  var tb=el("table");tb.appendChild(el("tr",{},["property","type","nullable","description"].map(function(h){return el("th",{text:h});})));
  t.properties.forEach(function(p){tb.appendChild(el("tr",{},[el("td",{},[el("code",{text:p.api_name})]),el("td",{text:p.type}),el("td",{text:p.nullable?"yes":"no"}),el("td",{text:p.description||""})]));});
  return el("div",{"class":"scroll"},[tb]);}

function browseView(v){
  var bar=el("div",{"class":"bar"});
  var sel=el("select",{"aria-label":"Object type",onchange:function(e){state.type=e.target.value;state.sel=null;state.q="";state.sort=null;state.sector="";state.size="";state.pgOnly=false;render();}});
  D.object_types.forEach(function(t){var o=el("option",{value:t.api_name,text:t.display_name+(HAS[t.api_name]?"":" (no rows)")});if(t.api_name===state.type)o.selected=true;sel.appendChild(o);});
  bar.appendChild(sel);
  var td=typeDef(state.type);
  if(!HAS[state.type]){
    v.appendChild(bar);
    v.appendChild(el("p",{"class":"note",text:td.display_name+" objects require establishment-level data that is not committed, so none are embedded. The definition is below."}));
    v.appendChild(el("div",{"class":"panel"},[el("div",{text:td.description}),el("div",{"class":"sub",text:"Backing dataset: "+td.backing_dataset}),propsTable(td)]));
    return;}
  var q=el("input",{type:"search",placeholder:"Search objects",value:state.q,"aria-label":"Search",oninput:function(e){state.q=e.target.value;state.sel=null;list();}});
  bar.appendChild(q);
  if(state.type==="PeerGroup"){
    var sec=el("select",{"aria-label":"Sector filter",onchange:function(e){state.sector=e.target.value;list();}});
    sec.appendChild(el("option",{value:"",text:"All sectors"}));
    T.Sector.rows.forEach(function(r){var o=el("option",{value:String(r[0]),text:"Sector "+r[0]});if(String(r[0])===state.sector)o.selected=true;sec.appendChild(o);});
    var sz=el("select",{"aria-label":"Size band filter",onchange:function(e){state.size=e.target.value;list();}});
    sz.appendChild(el("option",{value:"",text:"All size bands"}));
    T.SizeBand.rows.forEach(function(r){var o=el("option",{value:r[0],text:r[0]});if(r[0]===state.size)o.selected=true;sz.appendChild(o);});
    var pub=el("label",{},[el("input",{type:"checkbox",onchange:function(e){state.pgOnly=e.target.checked;list();}}),document.createTextNode(" publishable only")]);
    if(state.pgOnly)pub.firstChild.checked=true;
    bar.appendChild(sec);bar.appendChild(sz);bar.appendChild(pub);}
  var count=el("span",{"class":"sub"});bar.appendChild(count);
  v.appendChild(bar);
  var two=el("div",{"class":"two"});var left=el("div",{"class":"panel"}),right=el("div",{"class":"panel"});
  two.appendChild(left);two.appendChild(right);v.appendChild(two);
  function filtered(){
    var rows=get(state.type),s=state.q.trim().toLowerCase();
    rows=rows.filter(function(o){
      if(state.type==="PeerGroup"){
        if(state.pgOnly&&!o.publishable)return false;
        if(state.sector&&o.naics3.slice(0,2)!==state.sector)return false;
        if(state.size&&o.size_band!==state.size)return false;}
      if(!s)return true;
      return (titleOf(state.type,o)+" "+Object.keys(o).map(function(k){return o[k];}).join(" ")).toLowerCase().indexOf(s)>=0;});
    if(state.sort){var c=state.sort,d=state.desc?-1:1;rows=rows.slice().sort(function(a,b){var x=a[c],y=b[c];return (x<y?-1:x>y?1:0)*d;});}
    return rows;}
  function list(){
    var rows=filtered();count.textContent=rows.length+" of "+get(state.type).length+" objects";
    left.textContent="";
    var cols=T[state.type].cols.filter(function(c){return c!=="has_official_title";});
    var tb=el("table");
    tb.appendChild(el("tr",{},cols.map(function(c){return el("th",{"class":typeof get(state.type)[0][c]==="number"?"n":"",text:c+(state.sort===c?(state.desc?" ▼":" ▲"):""),onclick:function(){if(state.sort===c)state.desc=!state.desc;else{state.sort=c;state.desc=false;}list();}});})));
    rows.slice(0,300).forEach(function(o){
      var k=keyOf(state.type,o);
      tb.appendChild(el("tr",{"class":"row"+(state.sel===k?" sel":""),onclick:function(){state.sel=k;list();},tabindex:"0",onkeydown:function(e){if(e.key==="Enter"){state.sel=k;list();}}},
        cols.map(function(c){return el("td",{"class":typeof o[c]==="number"?"n":"",text:fmt(o[c],c)});})));});
    left.appendChild(el("div",{"class":"scroll"},[tb]));
    if(rows.length>300)left.appendChild(el("div",{"class":"sub",text:"Showing the first 300; narrow with search or filters."}));
    detail();}
  function detail(){
    right.textContent="";
    var o=get(state.type).filter(function(x){return keyOf(state.type,x)===state.sel;})[0];
    if(!o){right.appendChild(el("div",{"class":"sub",text:"Select an object to see its properties and follow its links."}));return;}
    right.appendChild(el("h2",{text:titleOf(state.type,o)}));
    var tb=el("table");Object.keys(o).forEach(function(k){tb.appendChild(el("tr",{},[el("td",{},[el("code",{text:k})]),el("td",{"class":"n",text:fmt(o[k],k)})]));});
    right.appendChild(tb);
    right.appendChild(el("h3",{text:"Links"}));
    var any=false;
    related(state.type,o).forEach(function(r){any=true;
      var d=el("div",{},[el("strong",{text:r.name+" ("+r.target+"): "})]);
      if(!r.items.length)d.appendChild(document.createTextNode(r.note||"none in committed data"));
      r.items.slice(0,40).forEach(function(it){d.appendChild(el("button",{"class":"lk",onclick:function(){state.type=r.target;state.sel=it.key;state.q="";state.sort=null;state.sector="";state.size="";state.pgOnly=false;render();},text:it.title}));d.appendChild(document.createTextNode("; "));});
      if(r.items.length>40)d.appendChild(document.createTextNode(" and "+(r.items.length-40)+" more"));
      right.appendChild(d);});
    if(!any)right.appendChild(el("div",{"class":"sub",text:"No links."}));
    if(state.type==="PeerGroup"||state.type==="Sector"||state.type==="ReportingYear"){}
  }
  list();}

function related(type,o){
  var out=[];
  function items(t,f){return get(t).filter(f).map(function(x){return {key:keyOf(t,x),title:titleOf(t,x)};});}
  if(type==="PeerGroup")out.push({name:"industry",target:"Industry",items:items("Industry",function(x){return x.naics3===o.naics3;})});
  if(type==="Industry"){
    out.push({name:"sector",target:"Sector",items:items("Sector",function(x){return x.naics2===o.naics2;})});
    out.push({name:"peer_groups",target:"PeerGroup",items:items("PeerGroup",function(x){return x.naics3===o.naics3;})});}
  if(type==="Sector")out.push({name:"industries",target:"Industry",items:items("Industry",function(x){return x.naics2===o.naics2;})});
  var fl=["Filing"];
  if(type==="ReportingYear"||type==="Industry"||type==="PeerGroup"||type==="QualityFlag")out.push({name:"filings",target:"Filing",items:[],note:"Filing objects are not committed; this link resolves only when establishment-level data is loaded."});
  return out;}

function linksView(v){
  var p=el("div",{"class":"panel"},[el("h2",{text:"Link types"})]);
  var tb=el("table");tb.appendChild(el("tr",{},["link","source","target","cardinality","key","names (forward / reverse)","description"].map(function(h){return el("th",{text:h});})));
  D.link_types.forEach(function(l){tb.appendChild(el("tr",{},[el("td",{},[el("code",{text:l.api_name})]),el("td",{text:l.source}),el("td",{text:l.target}),el("td",{text:l.cardinality}),el("td",{text:l.foreign_key||l.join_rule||""}),el("td",{text:l.source_link_name+" / "+l.target_link_name}),el("td",{text:l.description||""})]));});
  p.appendChild(el("div",{"class":"scroll"},[tb]));v.appendChild(p);}

function table(t,fmtcols){var tb=el("table");tb.appendChild(el("tr",{},t.cols.map(function(c,i){return el("th",{"class":i?"n":"",text:c});})));
  t.rows.forEach(function(r){tb.appendChild(el("tr",{},r.map(function(x,i){return el("td",{"class":i?"n":"",text:fmt(x,t.cols[i])});})));});return el("div",{"class":"scroll"},[tb]);}

function functionsView(v){
  var p=el("div",{"class":"panel"},[el("h2",{text:"Functions"})]);
  D.functions.forEach(function(f){p.appendChild(el("div",{},[el("strong",{text:f.api_name}),document.createTextNode(" : "+f.input+" to "+f.output+". "+f.description+" "),el("span",{"class":"sub",text:"(reuses "+f.reuses+")"})]));});
  v.appendChild(p);
  var a=el("div",{"class":"panel"},[el("h2",{text:"aggregate_rates by reporting year (committed output)"}),el("div",{"class":"sub",text:"Ratio-of-sums TRIR, DART, LTIR and severity, unscreened against screened, as stored in outputs/tables/metrics_by_year.csv and quality_by_year.csv. Shares are percentages."}),table(T.ReportingYear)]);
  v.appendChild(a);
  v.appendChild(el("div",{"class":"panel"},[el("h2",{text:"Aggregate TRIR by size band (committed output)"}),table(T.SizeBand)]));
  v.appendChild(el("div",{"class":"panel"},[el("h2",{text:"Quality flag prevalence (pooled)"}),table(T.QualityFlag)]));
  var pp=el("div",{"class":"panel"},[el("h2",{text:"peer_position"}),el("div",{"class":"sub",text:"Place a TRIR value against the committed percentiles of a peer group. Refuses non-publishable cells. This view only compares your number with the stored percentiles."})]);
  var ind=el("select",{"aria-label":"NAICS3"}),sz=el("select",{"aria-label":"Size band"}),inp=el("input",{type:"number",step:"any",min:"0",placeholder:"TRIR","aria-label":"TRIR"}),res=el("div",{"class":"sub"});
  T.Industry.rows.forEach(function(r){ind.appendChild(el("option",{value:r[0],text:r[0]+(r[1]?" "+r[1]:"")}));});
  T.SizeBand.rows.forEach(function(r){sz.appendChild(el("option",{value:r[0],text:r[0]}));});
  function upd(){
    var g=get("PeerGroup").filter(function(x){return x.naics3===ind.value&&x.size_band===sz.value;})[0];
    if(!g){res.textContent="No peer group for this combination in the committed table.";return;}
    if(!g.publishable){res.textContent="Not publishable: this cell has "+g.n+" filings, below the publication threshold. No placement given.";return;}
    if(inp.value===""){res.textContent="Enter a TRIR.";return;}
    var x=parseFloat(inp.value),ps=["p10","p25","p50","p75","p90","p95"],s;
    if(x<g.p10)s="below p10 ("+g.p10.toFixed(3)+")";
    else if(x>g.p95)s="above p95 ("+g.p95.toFixed(3)+")";
    else{for(var i=0;i<5;i++){if(x<=g[ps[i+1]]){s="between "+ps[i]+" ("+g[ps[i]].toFixed(3)+") and "+ps[i+1]+" ("+g[ps[i+1]].toFixed(3)+")";break;}}}
    res.textContent="TRIR "+x+" is "+s+" in peer group "+g.naics3+" / "+g.size_band+" (n="+g.n+").";}
  [ind,sz].forEach(function(e){e.addEventListener("change",upd);});inp.addEventListener("input",upd);
  pp.appendChild(el("div",{"class":"bar"},[ind,sz,inp]));pp.appendChild(res);v.appendChild(pp);upd();}

function actionsView(v){
  D.action_types.forEach(function(a){
    var p=el("div",{"class":"panel"},[el("h2",{text:a.display_name}),el("div",{text:a.description}),el("div",{"class":"sub",text:"Edits: "+JSON.stringify(a.edits)})]);
    var tb=el("table");tb.appendChild(el("tr",{},["parameter","type","required","notes"].map(function(h){return el("th",{text:h});})));
    a.parameters.forEach(function(q){var n=[];if(q.object_type)n.push(q.object_type);if(q.allowed_values)n.push("one of "+q.allowed_values.join(", "));if(q.max_length)n.push("max "+q.max_length+" chars");if(q.required_when)n.push("required when "+q.required_when.parameter+" = "+q.required_when.equals);
      tb.appendChild(el("tr",{},[el("td",{},[el("code",{text:q.api_name})]),el("td",{text:q.type}),el("td",{text:q.required?"yes":"no"}),el("td",{text:n.join("; ")})]));});
    p.appendChild(tb);
    if(a.submission_criteria&&a.submission_criteria.length){p.appendChild(el("h3",{text:"Submission criteria"}));
      a.submission_criteria.forEach(function(c){p.appendChild(el("div",{"class":"sub",text:c.parameter+"."+c.property+" "+c.operator+" "+c.value+": "+c.failure_message}));});}
    v.appendChild(p);});
  v.appendChild(el("p",{"class":"note",text:"Actions need a writable object store. This static page lists their definitions only and cannot apply them."}));}

function aboutView(v){
  var p=el("div",{"class":"panel"},[el("h2",{text:"Sources"}),el("div",{"class":"sub",text:"Every figure on this page is read from these committed files at build time by scripts/build_ontology_explorer.py."})]);
  var ul=el("ul");D.sources.forEach(function(s){ul.appendChild(el("li",{},[el("code",{text:s})]));});p.appendChild(ul);
  p.appendChild(el("div",{"class":"sub",text:"Establishment and Filing objects are not included. They need establishment-level data that is not committed."}));v.appendChild(p);}

function render(){tabs();var v=document.getElementById("view");v.textContent="";
  ({types:typesView,browse:browseView,links:linksView,functions:functionsView,actions:actionsView,about:aboutView})[state.tab](v);}
render();
})();
</script>
</body>
</html>
"""


def main() -> None:
    OUT.write_text(render(), encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
