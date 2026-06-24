"""看板頁（自帶 HTML/CSS/JS，零前端建置）。

純前端輪詢 /decisions 與 /decisions/history 渲染：
  - 每幣一張卡片：方向標籤、分數量表、信心度、操作建議、理由
  - 各訊號明細條（多/空/中性著色，寬度＝貢獻度）
  - 分數歷史 sparkline（SVG）
  - 「立即跑一輪」按鈕觸發 POST /cycle
"""

INDEX_HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Crypig 決策看板</title>
<style>
  :root{--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--mut:#8b949e;
        --bull:#3fb950;--bear:#f85149;--neu:#8b949e;--accent:#58a6ff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:-apple-system,Segoe UI,Roboto,"Noto Sans TC",sans-serif}
  header{display:flex;align-items:center;gap:16px;padding:16px 24px;
         border-bottom:1px solid var(--line)}
  header h1{font-size:18px;margin:0}
  header .ts{color:var(--mut);font-size:13px}
  button{background:var(--accent);color:#0d1117;border:0;border-radius:6px;
         padding:8px 14px;font-weight:600;cursor:pointer}
  button:disabled{opacity:.5;cursor:wait}
  /* 電腦版寬、三欄並排（短）；窄螢幕自動堆疊成單欄 */
  main{display:grid;grid-template-columns:repeat(auto-fit,minmax(360px,1fr));
       gap:16px;padding:24px;max-width:1400px;margin:0 auto;align-items:start}
  .card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
  .row{display:flex;justify-content:space-between;align-items:center}
  .sym{font-size:20px;font-weight:700}
  .badge{padding:3px 10px;border-radius:999px;font-size:13px;font-weight:700}
  .gauge{height:8px;background:#21262d;border-radius:999px;margin:12px 0 4px;position:relative}
  .gauge .mid{position:absolute;left:50%;top:-2px;width:1px;height:12px;background:var(--line)}
  .gauge .fill{position:absolute;top:0;height:8px;border-radius:999px}
  .meta{color:var(--mut);font-size:13px;margin:2px 0}
  .action{margin:8px 0;font-weight:600}
  .reason{color:var(--mut);font-size:13px;margin-bottom:10px}
  .sig{margin:8px 0;padding:10px 12px;background:#0d1117;
       border:1px solid var(--line);border-radius:8px}
  .sig.nodata{opacity:.55;border-style:dashed}
  .sigtitle{display:flex;justify-content:space-between;align-items:center;
            font-size:15px;font-weight:700;color:var(--fg);margin-bottom:6px}
  .sig .bar{height:6px;background:#21262d;border-radius:999px;margin-top:6px;overflow:hidden}
  .sig .bar i{display:block;height:6px;border-radius:999px}
  .alerts{margin-top:8px;font-size:12px;color:var(--bear)}
  .spark{margin-top:10px}
  .empty{color:var(--mut);padding:40px;text-align:center}
  .bt{max-width:1400px;margin:16px auto 0;padding:0 24px}
  .bt .box{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px}
  .bt h2{font-size:15px;margin:0 0 10px}
  .bt h2 small{color:var(--mut);font-weight:400}
  .kpis{display:flex;flex-wrap:wrap;gap:24px;align-items:flex-end}
  .kpi .v{font-size:24px;font-weight:700}
  .kpi .k{color:var(--mut);font-size:12px}
  .conf{display:flex;gap:16px;margin-top:10px;color:var(--mut);font-size:12px}
  .price{font-size:12px;color:var(--mut);margin-top:2px}
  .stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:12px 0 4px}
  .stat{background:#0d1117;border:1px solid var(--line);border-radius:8px;padding:8px;text-align:center}
  .stat .v{font-size:16px;font-weight:700}
  .stat .k{color:var(--mut);font-size:11px;margin-top:2px}
  .sec{font-size:12px;color:var(--mut);font-weight:600;margin:14px 0 6px;
       border-top:1px solid var(--line);padding-top:10px}
  .cbar{display:flex;height:10px;border-radius:999px;overflow:hidden}
  .cbar i{display:block;height:10px}
  .sig .name{font-weight:600;color:var(--fg)}
  .chip{font-size:11px;padding:1px 8px;border-radius:999px;font-weight:700}
  .calc{color:var(--mut);font-size:11px;margin-top:2px}
  .ratios{display:flex;gap:18px;font-size:13px;margin:6px 0 2px;color:var(--mut);flex-wrap:wrap}
  .ratios b{font-size:15px}
  .tbl{width:100%;border-collapse:collapse;font-size:13px}
  .tbl th{text-align:right;color:var(--mut);font-weight:600;padding:8px 10px;cursor:pointer;
          user-select:none;border-bottom:1px solid var(--line);white-space:nowrap}
  .tbl th:first-child,.tbl td:first-child{text-align:left}
  .tbl td{text-align:right;padding:8px 10px;border-bottom:1px solid #21262d;white-space:nowrap}
  .tbl th:hover{color:var(--fg)}
  .tbl tbody tr:hover{background:#1c2230}
  .tbl .symc{font-weight:700;font-size:14px}
  .scroll{max-height:540px;overflow:auto;border-radius:8px}
  .scroll thead th{position:sticky;top:0;background:#161b22;z-index:1}
  .filt{background:#0d1117;border:1px solid var(--line);color:var(--fg);border-radius:6px;
        padding:6px 10px;font-size:13px;margin-left:auto}
</style>
</head>
<body>
<header>
  <h1>🐷 Crypig 決策看板</h1>
  <span class="ts" id="ts">載入中…</span>
  <span style="flex:1"></span>
  <button id="run" onclick="runCycle()">立即跑一輪</button>
</header>
<section id="macro" class="bt"><div class="empty">宏觀載入中…</div></section>
<section id="table" class="bt"><div class="empty">幣別總表載入中…</div></section>
<section id="bt" class="bt"><div class="empty">回測載入中…</div></section>
<script>
const C={bull:'#3fb950',bear:'#f85149',neutral:'#8b949e'};
const LBLC=l=>l.includes('多')?C.bull:l.includes('空')?C.bear:l==='訊號分歧'?'#d29922':C.neutral;

function money(x){
  if(x==null) return '—';
  const n=Number(x);
  return '$'+n.toLocaleString('en-US',{maximumFractionDigits:n<10?4:n<1000?2:0});
}
function pct(x){return x==null?'—':(x*100).toFixed(1)+'%';}
function bigMoney(x){
  if(x==null) return '—';
  const a=Math.abs(x);
  if(a>=1e12) return '$'+(x/1e12).toFixed(2)+'T';
  if(a>=1e9) return '$'+(x/1e9).toFixed(1)+'B';
  if(a>=1e6) return '$'+(x/1e6).toFixed(1)+'M';
  return '$'+Math.round(x);
}
async function loadMacro(){
  try{
    const m=await (await fetch('/macro')).json();
    const g=m.global;
    if(!g){document.getElementById('macro').innerHTML='<div class="box empty">宏觀資料暫無（外部 API 失敗）</div>';return {};}
    document.getElementById('macro').innerHTML=`<div class="box">
      <h2>🌐 全市場宏觀 <small>整體槓桿與換手環境（來源 CoinGecko 聚合）</small></h2>
      <div class="kpis">
        <div class="kpi"><div class="v">${bigMoney(g.market_cap)}</div><div class="k">總市值</div></div>
        <div class="kpi"><div class="v">${bigMoney(g.volume_24h)}</div><div class="k">24h 成交量</div></div>
        <div class="kpi"><div class="v">${bigMoney(g.open_interest)}</div><div class="k">全市場未平倉 OI</div></div>
        <div class="kpi"><div class="v" style="color:#58a6ff">${g.oi_cap==null?'—':(g.oi_cap*100).toFixed(2)+'%'}</div><div class="k">OI/Cap 槓桿水位</div></div>
        <div class="kpi"><div class="v" style="color:#58a6ff">${g.vol_cap==null?'—':(g.vol_cap*100).toFixed(2)+'%'}</div><div class="k">Vol/Cap 換手率</div></div>
        <div class="kpi"><div class="v">${(g.btc_dominance||0).toFixed(1)}%</div><div class="k">BTC 市佔</div></div>
      </div>
    </div>`;
    return m.per_symbol||{};
  }catch(e){document.getElementById('macro').innerHTML='<div class="box empty">宏觀載入失敗：'+e+'</div>';return {};}
}
function eqspark(eq){
  if(!eq||eq.length<2) return '<span class="meta">交易筆數不足，無法畫曲線</span>';
  const W=600,H=60,n=eq.length,vs=eq.map(e=>e.equity),mn=Math.min(1,...vs),mx=Math.max(1,...vs),pad=(mx-mn)*0.1||0.01;
  const xs=i=>i/(n-1)*W, ys=v=>H-(v-(mn-pad))/((mx+pad)-(mn-pad))*H;
  const pts=vs.map((v,i)=>`${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ');
  const base=ys(1), last=vs[vs.length-1], col=last>=1?'#3fb950':'#f85149';
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="margin-top:8px">
    <line x1="0" y1="${base}" x2="${W}" y2="${base}" stroke="#30363d" stroke-dasharray="3"/>
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
}
async function loadBacktest(){
  try{
    const b=await (await fetch('/backtest')).json();
    const o=b.overall, hr=o.hit_rate, col=hr==null?'#8b949e':hr>=0.5?'#3fb950':'#f85149';
    const cb=o.by_confidence||{};
    const cbtxt=['low','mid','high'].map(k=>`${({low:'低',mid:'中',high:'高'})[k]}信心 ${pct(cb[k]?.hit_rate)}(${cb[k]?.trades||0})`).join(' ｜ ');
    document.getElementById('bt').innerHTML=`<div class="box">
      <h2>📈 回測 <small>持有期 ${b.horizon_hours}h｜跟隨訊號方向進出｜價源 ${b.price_source==='ohlcv'?'真實K線':'決策落地價'}</small></h2>
      <div class="kpis">
        <div class="kpi"><div class="v" style="color:${col}">${pct(hr)}</div><div class="k">方向命中率</div></div>
        <div class="kpi"><div class="v" style="color:${o.total_return>=0?'#3fb950':'#f85149'}">${o.total_return==null?'—':(o.total_return*100).toFixed(1)+'%'}</div><div class="k">累積損益</div></div>
        <div class="kpi"><div class="v">${o.avg_return==null?'—':(o.avg_return*100).toFixed(2)+'%'}</div><div class="k">平均單筆</div></div>
        <div class="kpi"><div class="v">${o.trades}</div><div class="k">交易筆數</div></div>
        <div class="kpi"><div class="v" style="color:#8b949e">${o.pending}</div><div class="k">未到期</div></div>
      </div>
      <div class="conf">依信心度分層命中率： ${cbtxt}</div>
      ${eqspark(o.equity)}
    </div>`;
  }catch(e){document.getElementById('bt').innerHTML='<div class="box empty">回測載入失敗：'+e+'</div>';}
}
// ---- 全市場幣別總表（合併：決策 + CoinGecko 宏觀 + Hyperliquid 場內）----
const FFLAG={hot:{t:'🔴 過熱',c:'#f85149'},warm:{t:'🟠 偏擁擠',c:'#d29922'},
             squeeze:{t:'🟢 空方擁擠',c:'#3fb950'},normal:{t:'正常',c:'#8b949e'}};
function fundFmt(ann, flag){
  if(ann==null) return '—';
  const fl=FFLAG[flag]||FFLAG.normal, sign=ann>=0?'+':'';
  const badge=flag&&flag!=='normal'
    ? ` <span class="chip" style="background:${fl.c}22;color:${fl.c}">${fl.t}</span>`:'';
  return `<span style="color:${fl.c}">${sign}${(ann*100).toFixed(1)}%</span>${badge}`;
}
const fundCell=r=>fundFmt(r.funding_ann, r.funding_flag);
let MROWS=[], MSORT={col:'score',dir:-1}, MFILT='';
const MABS=new Set(['funding_ann']);   // 費率欄按絕對值排（抓最極端）
const MCOLS=[
  {k:'symbol',t:'幣別',f:r=>`<span class="symc">${r.symbol}</span>`},
  {k:'label', t:'判斷',f:r=>r.label?`<span style="color:${LBLC(r.label)}">${r.label}</span>`:'—'},
  {k:'score', t:'分數',f:r=>r.score==null?'—':r.score.toFixed(3)},
  {k:'confidence',t:'信心',f:r=>r.confidence==null?'—':(r.confidence*100).toFixed(0)+'%'},
  {k:'divergence',t:'日線背離',f:r=>{
    if(!r.divergence) return '—';
    if(r.divergence==='bull') return '<span style="color:#3fb950">📈 底背離</span>';
    if(r.divergence==='bear') return '<span style="color:#f85149">📉 頂背離</span>';
    return '<span style="color:#8b949e">無</span>';}},
  {k:'price',t:'標記價',f:r=>money(r.price)},
  {k:'oi_cap',t:'OI/Cap',f:r=>r.oi_cap==null?'—':(r.oi_cap*100).toFixed(2)+'%'},
  {k:'vol_cap',t:'Vol/Cap',f:r=>r.vol_cap==null?'—':(r.vol_cap*100).toFixed(2)+'%'},
  {k:'funding_ann',t:'資金費率(年化)',f:fundCell},
  {k:'open_interest',t:'OI',f:r=>bigMoney(r.open_interest)},
  {k:'premium',t:'溢價',f:r=>r.premium==null?'—':(r.premium*100).toFixed(3)+'%'},
  {k:'market_cap',t:'市值',f:r=>bigMoney(r.market_cap)},
];
function mRows(){
  let rows=MFILT?MROWS.filter(r=>r.symbol.includes(MFILT)):MROWS;
  return [...rows].sort((a,b)=>{
    let va=MABS.has(MSORT.col)?(a[MSORT.col]==null?null:Math.abs(a[MSORT.col])):a[MSORT.col];
    let vb=MABS.has(MSORT.col)?(b[MSORT.col]==null?null:Math.abs(b[MSORT.col])):b[MSORT.col];
    if(va==null&&vb==null) return 0;
    if(va==null) return 1; if(vb==null) return -1;
    if(typeof va==='string') return MSORT.dir*va.localeCompare(vb);
    return MSORT.dir*(va-vb);
  });
}
function mBodyHTML(){return mRows().map(r=>`<tr>${MCOLS.map(c=>`<td>${c.f(r)}</td>`).join('')}</tr>`).join('');}
function renderMBody(){const el=document.getElementById('mbody'); if(el) el.innerHTML=mBodyHTML();}
function mSort(col){ if(MSORT.col===col) MSORT.dir*=-1; else {MSORT.col=col;MSORT.dir=-1;} renderTable(); }
function renderTable(){
  if(!MROWS.length){document.getElementById('table').innerHTML='<div class="box empty">幣別資料暫無</div>';return;}
  const arrow=k=>MSORT.col===k?(MSORT.dir<0?' ▼':' ▲'):'';
  const head=MCOLS.map(c=>`<th onclick="mSort('${c.k}')">${c.t}${arrow(c.k)}</th>`).join('');
  document.getElementById('table').innerHTML=`<div class="box">
    <div class="row" style="margin-bottom:10px;gap:12px">
      <h2 style="margin:0">📋 幣別總表 <small>共 ${MROWS.length} 幣 · BTC/ETH/SOL 完整4訊號決策、其餘為聰明錢+資金費率輕量評分 · 點標題排序</small></h2>
      <input class="filt" placeholder="搜尋幣別…" oninput="MFILT=this.value.trim().toUpperCase();renderMBody()" value="${MFILT}">
    </div>
    <div class="scroll"><table class="tbl"><thead><tr>${head}</tr></thead><tbody id="mbody">${mBodyHTML()}</tbody></table></div></div>`;
}
async function refresh(){
  loadBacktest();
  await loadMacro();
  let decisions=[], hlcoins=[], scores={};
  try{ decisions=(await (await fetch('/decisions')).json()).decisions||[]; }catch(e){}
  try{ hlcoins=(await (await fetch('/hl_market')).json()).coins||[]; }catch(e){}
  try{ scores=(await (await fetch('/scores')).json()).scores||{}; }catch(e){}
  // 合併：HL+CoinGecko 已整合為底；輕量全幣評分疊上；watchlist 完整決策最後覆蓋。
  const bySym={};
  hlcoins.forEach(c=>bySym[c.symbol]={symbol:c.symbol, price:c.price,
    funding_ann:c.funding_ann, funding_flag:c.funding_flag,
    open_interest:c.open_interest_usd, premium:c.premium,
    market_cap:c.market_cap, oi_cap:c.oi_cap, vol_cap:c.vol_cap});
  Object.entries(scores).forEach(([s,v])=>{ const r=bySym[s]||(bySym[s]={symbol:s});
    r.label=v.label; r.score=v.score; r.confidence=v.confidence; r.divergence=v.divergence; });
  decisions.forEach(d=>{ const r=bySym[d.symbol]||(bySym[d.symbol]={symbol:d.symbol});
    r.label=d.label; r.score=d.score; r.confidence=d.confidence; if(r.price==null)r.price=d.price; });
  MROWS=Object.values(bySym);
  renderTable();
  document.getElementById('ts').textContent=decisions[0]?('更新：'+new Date(decisions[0].ts).toLocaleString()):'';
}
async function runCycle(){
  const b=document.getElementById('run');b.disabled=true;b.textContent='跑一輪中…';
  try{await fetch('/cycle',{method:'POST'});await refresh();}
  finally{b.disabled=false;b.textContent='立即跑一輪';}
}
refresh(); setInterval(refresh,30000);
</script>
</body>
</html>
"""
