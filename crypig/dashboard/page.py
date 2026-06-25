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
  .nav{display:flex;gap:8px;margin-left:8px}
  .nav button{background:#21262d;color:var(--mut);font-weight:600}
  .nav button.on{background:var(--accent);color:#0d1117}
  .ask{display:flex;gap:8px;margin:10px 0}
  .ask input{flex:1;background:#0d1117;border:1px solid var(--line);color:var(--fg);
             border-radius:6px;padding:9px 12px;font-size:14px}
  .dl{display:inline-block;background:var(--accent);color:#0d1117;font-weight:700;
      padding:10px 16px;border-radius:8px;text-decoration:none}
  .step{margin:6px 0;color:var(--mut);font-size:13px}
  .socbar{height:8px;background:#21262d;border-radius:999px;overflow:hidden;margin-top:4px}
  .socbar i{display:block;height:8px}
  .newschips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px}
  .newschip{background:#0d1117;border:1px solid #21262d;border-radius:8px;padding:6px 10px;font-size:13px}
  .newslist{max-height:420px;overflow:auto;border-top:1px solid #21262d;margin-top:6px}
  .newsrow{padding:9px 2px;border-bottom:1px solid #161b22}
  .newsrow a{color:#c9d1d9;text-decoration:none}
  .newsrow a:hover{color:#58a6ff;text-decoration:underline}
  .newsbadge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;border:1px solid;margin-right:8px;vertical-align:middle}
  .newscoin{display:inline-block;font-size:11px;background:#1f2937;color:#9ecbff;border-radius:5px;padding:1px 6px;margin-right:4px}
</style>
</head>
<body>
<header>
  <h1>🐷 Crypig 中台</h1>
  <span class="nav">
    <button id="nav-market" class="on" onclick="showPage('market')">📊 市場看板</button>
    <button id="nav-strategy" onclick="showPage('strategy')">🧠 策略 / Obsidian</button>
  </span>
  <span class="ts" id="ts">載入中…</span>
  <span style="flex:1"></span>
  <button id="run" onclick="runCycle()">立即跑一輪</button>
</header>
<div id="page-strategy" style="display:none"></div>
<div id="page-market">
<section id="radar" class="bt"><div class="empty">分歧雷達載入中…</div></section>
<section id="macro" class="bt"><div class="empty">宏觀載入中…</div></section>
<section id="defi" class="bt"><div class="empty">資金動向載入中…</div></section>
<section id="pos" class="bt"><div class="empty">大玩家決心載入中…</div></section>
<section id="whalechart" class="bt"><div class="empty">鯨魚每日變化載入中…</div></section>
<section id="table" class="bt"><div class="empty">幣別總表載入中…</div></section>
</div>
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
// 淨多空 + 與上一輪(20分鐘)變化；whale=true 時把「減多/加空」標成「在賣」
function netCell(net, delta, whale){
  if(net==null) return '—';
  const col = net>0.05?'#3fb950':net<-0.05?'#f85149':'#8b949e';
  const side = net>0.05?'偏多':net<-0.05?'偏空':'中性';
  let mv='';
  if(delta!=null && Math.abs(delta)>=0.02){
    if(delta>0) mv=` <span style="color:#3fb950">▲${whale?'加倉':'加多'}</span>`;
    else mv=` <span style="color:#f85149">▼${whale?'在賣':'加空'}</span>`;
  }
  return `<span style="color:${col}">${side} ${(net*100).toFixed(0)}%</span>${mv}`;
}
let MROWS=[], MSORT={col:'score',dir:-1}, MFILT='';
const MABS=new Set(['funding_ann']);   // 費率欄按絕對值排（抓最極端）
const MCOLS=[
  {k:'symbol',t:'幣別',f:r=>`<span class="symc">${r.symbol}</span>`},
  {k:'label', t:'判斷',f:r=>r.label?`<span style="color:${LBLC(r.label)}">${r.label}</span>`:'—'},
  {k:'score', t:'分數',f:r=>r.score==null?'—':r.score.toFixed(3)},
  {k:'confidence',t:'信心',f:r=>r.confidence==null?'—':(r.confidence*100).toFixed(0)+'%'},
  {k:'sm_net',t:'聰明錢多空',f:r=>netCell(r.sm_net, r.sm_delta)},
  {k:'whale_net',t:'巨鯨多空',f:r=>netCell(r.whale_net, r.whale_delta, true)},
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
  const withCap=MROWS.filter(r=>r.market_cap!=null).length;
  document.getElementById('table').innerHTML=`<div class="box">
    <div class="row" style="margin-bottom:10px;gap:12px">
      <h2 style="margin:0">📋 幣別總表 <small>共 ${MROWS.length} 幣 · BTC/ETH/SOL 完整4訊號決策、其餘為聰明錢+資金費率輕量評分 · 點標題排序</small></h2>
      <input class="filt" placeholder="搜尋幣別…" oninput="MFILT=this.value.trim().toUpperCase();renderMBody()" value="${MFILT}">
    </div>
    <div class="meta" style="margin:-4px 0 8px">ℹ️ <b>標記價／OI／溢價</b>來自 Hyperliquid，全幣皆有。<b>市值／OI&#8202;Cap／Vol&#8202;Cap</b>來自 CoinGecko，僅 ${withCap}/${MROWS.length} 幣對得上——冷門幣顯示「—」代表 <b>CoinGecko 無此幣市值資料</b>，非系統錯誤。</div>
    <div class="scroll"><table class="tbl"><thead><tr>${head}</tr></thead><tbody id="mbody">${mBodyHTML()}</tbody></table></div></div>`;
}
function posRow(name, g, color){
  if(!g||!g.total) return `<div class="meta">${name}：無資料</div>`;
  const sp=g.short_pct, lp=g.long_pct;
  const lean = sp==null?'—':sp>lp?`<b style="color:#f85149">空方 ${(sp*100).toFixed(0)}%</b>`
                                  :`<b style="color:#3fb950">多方 ${(lp*100).toFixed(0)}%</b>`;
  return `<div style="margin:8px 0">
    <span style="font-weight:700;color:${color}">${name}</span>（前 ${g.total} 名）：
    <span style="color:#3fb950">多 ${g.long}</span> ／
    <span style="color:#f85149">空 ${g.short}</span> ／
    <span style="color:#8b949e">觀望 ${g.flat}</span>
    ｜ 表態傾向 ${lean}
    ｜ 槓桿 中位 <b>${g.lev_median??'—'}x</b>（最高 ${g.lev_max??'—'}x）</div>`;
}
async function loadRadar(){
  try{
    const [r,hist]=await Promise.all([
      (await fetch('/radar')).json(),
      fetch('/radar_history').then(x=>x.json()).then(x=>x.history||[]).catch(()=>[])]);
    const m=r.market||{}, coins=r.coins||[];
    const vcol=m.diverging?(m.verdict.includes('看多')||m.verdict.includes('底部')?'#3fb950':'#f85149'):'#d29922';
    const rows=coins.map(c=>{
      const bcol=c.bias==='看多'?'#3fb950':'#f85149';
      return `<div class="sig"><div class="sigtitle"><span class="symc">${c.symbol}</span>
        <span class="chip" style="background:${bcol}22;color:${bcol}">${c.type}·${c.bias}</span></div>
        <div class="calc">群眾(費率) <b style="color:${c.crowd>0?'#3fb950':'#f85149'}">${(c.crowd*100).toFixed(0)}%</b>
          ⟷ 聰明錢 <b style="color:${c.smart>0?'#3fb950':'#f85149'}">${(c.smart*100).toFixed(0)}%</b>
          ${c.whale!=null?`｜鯨魚 ${(c.whale*100).toFixed(0)}%`:''} ｜ 分歧強度 ${c.score}</div></div>`;
    }).join('') || '<div class="meta">目前沒有明顯的群眾 vs 大戶背離（多數同向）。</div>';
    // 時間軸：背離量 gap 逐輪變化，趨 0=收斂=反轉接近
    let tl='';
    const cut=Date.now()/1000-24*3600;
    const h24=hist.filter(h=>Date.parse(h.ts)/1000>=cut);
    const use=h24.length>=2?h24:hist;          // 近 24 小時(不足則顯示已累積)
    if(use.length>=2){
      const pts=use.map(h=>({t:Date.parse(h.ts)/1000, v:h.gap}));
      const k=Math.min(5,use.length), recent=use.slice(-k), prev=use.slice(-2*k,-k);
      const am=a=>a.length?a.reduce((s,x)=>s+Math.abs(x.gap),0)/a.length:0;
      const rA=am(recent), pA=am(prev||[]);
      const conv = prev.length? (rA<pA-0.03?{t:'背離收斂中 → 群眾正在向聰明錢靠攏，接近反轉/進場時機',c:'#3fb950'}
                    : rA>pA+0.03?{t:'背離擴大中 → 分歧加劇，反轉時機未到，續觀望',c:'#d29922'}
                    : {t:'背離持平 → 僵持，等收斂訊號',c:'#8b949e'}) : null;
      const lastN=use[use.length-1];
      const span=h24.length>=2?'近 24 小時':'已累積 '+use.length+' 筆';
      tl=`<div class="sec">背離時間軸 <small>${span}｜gap=群眾−聰明錢；線趨近 0 ＝收斂＝反轉接近</small></div>
        <div class="meta">最新背離量 <b>${(lastN.gap>=0?'+':'')+lastN.gap}</b>｜背離幣數 <b>${lastN.n_div}</b>（頂 ${lastN.n_top}／底 ${lastN.n_bottom}）${conv?`<br><b style="color:${conv.c}">${conv.t}</b>`:''}</div>
        ${lineChart(pts,{color:'#d29922',includeZero:true})}`;
    } else {
      tl=`<div class="sec">背離時間軸</div><div class="meta">每 20 分鐘記一筆，目前 ${hist.length} 筆，2 筆以上開始畫線（看背離何時收斂＝進場時機）。</div>`;
    }
    document.getElementById('radar').innerHTML=`<div class="box" style="border-color:${vcol}">
      <h2>🎯 分歧雷達 <small>群眾(情緒·資金費率) vs 大戶(聰明錢·鯨魚) 反向＝alpha</small></h2>
      <div style="font-size:16px;font-weight:700;color:${vcol};margin:4px 0 8px">${m.verdict||'—'}</div>
      <div class="meta">市場層級：恐懼貪婪 <b>${m.fear_greed??'—'}</b>（${m.fg_label||''}，歷史第 ${m.fg_percentile??'—'} 百分位）= 群眾<b>${m.crowd_dir||''}</b>　⟷　聰明錢整體 <b>${m.smart_avg!=null?(m.smart_avg*100).toFixed(0)+'%':'—'}</b>（${m.smart_dir||''}）</div>
      ${tl}
      <div class="sec">背離最大的幣（alpha 候選）</div>
      ${rows}</div>`;
  }catch(e){document.getElementById('radar').innerHTML='<div class="box empty">分歧雷達載入失敗：'+e+'</div>';}
}
async function loadDefi(){
  try{
    const d=await (await fetch('/defi')).json();
    const tvl=d.tvl||{}, sc=d.stablecoin||{}, chains=d.chains||[];
    const chg=(x)=>x==null?'—':`<b style="color:${x>=0?'#3fb950':'#f85149'}">${(x*100).toFixed(1)}%</b>`;
    const chainHtml=chains.map(c=>`<span style="margin-right:14px">${c.name} <b>$${(c.tvl/1e9).toFixed(1)}B</b></span>`).join('');
    document.getElementById('defi').innerHTML=`<div class="box">
      <h2>💰 資金動向（DefiLlama）<small>TVL=風險偏好；穩定幣=場邊乾火藥</small></h2>
      <div class="kpis">
        <div class="kpi"><div class="v">$${tvl.value?(tvl.value/1e9).toFixed(1):'—'}B</div><div class="k">DeFi 總 TVL</div></div>
        <div class="kpi"><div class="v">${chg(tvl.chg_7d)}</div><div class="k">TVL 7天</div></div>
        <div class="kpi"><div class="v">${chg(tvl.chg_30d)}</div><div class="k">TVL 30天</div></div>
        <div class="kpi"><div class="v">$${sc.value?(sc.value/1e9).toFixed(0):'—'}B</div><div class="k">穩定幣總市值</div></div>
        <div class="kpi"><div class="v">${chg(sc.chg_30d)}</div><div class="k">穩定幣 30天</div></div>
      </div>
      <div class="meta" style="margin-top:8px">前 6 大鏈 TVL：${chainHtml}</div>
      <div class="meta">${lineChart((tvl.history||[]).map(h=>({t:h.t,v:h.v})), {color:'#58a6ff'})}</div>
    </div>`;
  }catch(e){document.getElementById('defi').innerHTML='<div class="box empty">資金動向載入失敗：'+e+'</div>';}
}
async function loadPositioning(){
  try{
    const p=await (await fetch('/positioning')).json();
    document.getElementById('pos').innerHTML=`<div class="box">
      <h2>🧭 大玩家決心 <small>多空人數＋槓桿（人數=表態強度，槓桿=決心）</small></h2>
      ${posRow('🧠 聰明錢(獲利前N)', p.smart, '#58a6ff')}
      ${posRow('🐋 巨鯨(淨值前N)', p.whale, '#d29922')}
      <div class="meta">註：觀望=目前無持倉；表態傾向只計有開倉者。</div>
    </div>`;
  }catch(e){document.getElementById('pos').innerHTML='<div class="box empty">決心面板載入失敗：'+e+'</div>';}
}
function fmtD(t){ if(!t) return ''; const d=new Date(t*1000); return (d.getMonth()+1)+'/'+d.getDate(); }
// 數值軸「好看」刻度間距（讓格線落在整數）
function niceStep(range, target){
  const raw=range/Math.max(1,target), mag=Math.pow(10,Math.floor(Math.log10(raw)||0));
  const norm=raw/mag; const s=norm<1.5?1:norm<3?2:norm<7?5:10; return s*mag;
}
// Catmull-Rom → 三次貝茲，畫平滑曲線
function smoothPath(P){
  if(P.length<2) return '';
  let d=`M${P[0][0].toFixed(1)},${P[0][1].toFixed(1)}`;
  for(let i=0;i<P.length-1;i++){
    const p0=P[i-1]||P[i], p1=P[i], p2=P[i+1], p3=P[i+2]||P[i+1];
    const c1x=p1[0]+(p2[0]-p0[0])/6, c1y=p1[1]+(p2[1]-p0[1])/6;
    const c2x=p2[0]-(p3[0]-p1[0])/6, c2y=p2[1]-(p3[1]-p1[1])/6;
    d+=`C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}
let _gid=0;
function lineChart(pts, opts){
  opts=opts||{};
  if(!pts||pts.length<2) return '<span class="meta">資料累積中…</span>';
  const W=1000,H=200,L=50,R=16,T=16,Bm=32,n=pts.length,vs=pts.map(p=>p.v);
  let mn=Math.min(...vs),mx=Math.max(...vs);
  if(opts.includeZero){ mn=Math.min(mn,0); mx=Math.max(mx,0); }   // 讓 0 一定在軸上(看收斂)
  // 縱軸：好看整數邊界＋格線間距（資料貼齊整數刻度＝更細）
  const step=niceStep((mx-mn)||Math.abs(mx)||1, 5);
  let lo=Math.floor(mn/step)*step, hi=Math.ceil(mx/step)*step;
  if(lo===hi) hi=lo+step;
  if(opts.zeroFloor && lo>0) lo=0;
  const xs=i=>L+i/(n-1)*(W-L-R), ys=v=>T+(1-(v-lo)/(hi-lo))*(H-T-Bm);
  const col=opts.color || (vs[n-1]>=vs[0]?'#3fb950':'#f85149');
  const fa=v=>{const a=Math.abs(v);return a>=1e9?(v/1e9).toFixed(1)+'B':a>=1e6?(v/1e6).toFixed(2)+'M':a>=1e3?(v/1e3).toFixed(1)+'K':(a<10&&a>0?v.toFixed(1):''+Math.round(v));};
  // 縱軸格線（每個整數刻度一條，比之前 3 條更細）
  let grid='';
  for(let g=lo; g<=hi+step*0.001; g+=step){ const y=ys(g), gv=Math.abs(g)<step*1e-6?0:g;
    grid+=`<line x1="${L}" y1="${y.toFixed(1)}" x2="${W-R}" y2="${y.toFixed(1)}" stroke="#1e242c" stroke-width="1"/>`
        +`<text x="${L-7}" y="${(y+4).toFixed(1)}" fill="#8b949e" font-size="12" text-anchor="end">${fa(gv)}</text>`; }
  // 零軸（淨多空翻轉分界）
  let zline='';
  if(lo<0 && hi>0){ const zy=ys(0);
    zline=`<line x1="${L}" y1="${zy.toFixed(1)}" x2="${W-R}" y2="${zy.toFixed(1)}" stroke="#6e7681" stroke-width="1.2" stroke-dasharray="5 3"/>`; }
  // 時間軸：依跨度自動格式，刻度較多＝更細
  const hasT = pts[0].t!=null && pts[n-1].t!=null;
  const spanD = hasT ? (Number(pts[n-1].t)-Number(pts[0].t))/86400 : 0;
  const pad2=x=>('0'+x).slice(-2);
  const tickLabel=i=>{ const p=pts[i];
    if(p.t!=null){ const d=new Date(Number(p.t)*1000);
      if(spanD<2) return pad2(d.getHours())+':'+pad2(d.getMinutes());
      if(spanD<=160) return d.getFullYear()+'-'+pad2(d.getMonth()+1)+'-'+pad2(d.getDate());
      if(spanD<=900) return d.getFullYear()+'-'+pad2(d.getMonth()+1);
      return ''+d.getFullYear(); }
    return p.d||''; };
  const nT=Math.min(8, n);
  const idxs=[...new Set(Array.from({length:nT},(_,k)=>Math.round(k*(n-1)/(nT-1))))];
  const ticks=idxs.map(i=>{ const tx=Math.max(L+18,Math.min(W-R-18,xs(i)));
    return `<text x="${tx.toFixed(1)}" y="${H-9}" fill="#8b949e" font-size="12" text-anchor="middle">${tickLabel(i)}</text>`; }).join('');
  // 平滑曲線＋漸層面積＋末點圓點
  const P=vs.map((v,i)=>[xs(i),ys(v)]);
  const line=smoothPath(P);
  const area=line+` L${xs(n-1).toFixed(1)},${(H-Bm).toFixed(1)} L${xs(0).toFixed(1)},${(H-Bm).toFixed(1)} Z`;
  const ex=xs(n-1), ey=ys(vs[n-1]);
  const gid='grad'+(_gid++);
  const yl=opts.ylabel?`<text x="13" y="${T+(H-T-Bm)/2}" fill="#6e7681" font-size="11" transform="rotate(-90 13 ${T+(H-T-Bm)/2})" text-anchor="middle">${opts.ylabel}</text>`:'';
  return `<svg width="100%" viewBox="0 0 ${W} ${H}">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.30"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    ${grid}${zline}
    <path d="${area}" fill="url(#${gid})" stroke="none"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="3.5" fill="${col}"/>
    ${ticks}${yl}</svg>`;
}
async function loadWhaleChart(){
  try{
    const r=await (await fetch('/whale_history?symbol=BTC&cohort=whale')).json();
    const h=r.history||[];
    if(h.length<2){document.getElementById('whalechart').innerHTML=
      '<div class="box"><h2>🐋 HL 巨鯨 BTC 合約淨持倉 <small>逐輪累積中</small></h2>'
      +'<div class="meta">每 20 分鐘記一筆，目前 '+h.length+' 筆，2 筆以上即開始畫線（看大戶部位何時翻多/翻空＝進場時機）。</div></div>';return;}
    const pts=h.map(x=>({t:Date.parse(x.ts)/1000, v:x.net_usd}));
    const last=h[h.length-1], lo=last.long_usd, sh=last.short_usd;
    const net=last.net_usd, bias=net>=0?'淨多':'淨空', col=net>=0?'#3fb950':'#f85149';
    // 是否在這段期間翻轉
    const firstNet=h[0].net_usd;
    const flip = firstNet<0&&net>=0?'　🔄 期間翻多（轉折）':firstNet>=0&&net<0?'　🔄 期間翻空（轉折）':'';
    document.getElementById('whalechart').innerHTML=`<div class="box">
      <h2>🐋 HL 巨鯨 BTC 合約淨持倉 <small>淨值前N大戶，每 20 分鐘一筆，近 ${h.length} 筆</small></h2>
      <div class="meta">最新 <b style="color:${col}">${bias} $${(Math.abs(net)/1e6).toFixed(1)}M</b>
        （多 $${(lo/1e6).toFixed(1)}M／空 $${(sh/1e6).toFixed(1)}M，${last.count} 個帳號）
        <b style="color:#d29922">${flip}</b>
        ｜ 線在零軸上＝大戶偏多、下＝偏空，穿越零軸＝部位翻轉</div>
      ${lineChart(pts)}
    </div>`;
  }catch(e){document.getElementById('whalechart').innerHTML='<div class="box empty">鯨魚圖載入失敗：'+e+'</div>';}
}
async function refresh(){
  loadRadar(); loadDefi(); loadPositioning(); loadWhaleChart();
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
    Object.assign(r, v); });   // label/score/confidence/divergence/sm_net/whale_net/…
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
// ---- 頁2：策略 / Obsidian ----
let STRATLOADED=false;
function showPage(name){
  document.getElementById('page-market').style.display = name==='market'?'block':'none';
  document.getElementById('page-strategy').style.display = name==='strategy'?'block':'none';
  document.getElementById('nav-market').className = name==='market'?'on':'';
  document.getElementById('nav-strategy').className = name==='strategy'?'on':'';
  if(name==='strategy'){ if(!STRATLOADED){ STRATLOADED=true; loadStrategy(); } else { refreshStrategy(); } }
}
// 策略頁自動刷新：只在該頁可見時重抓各面板資料(不重建結構，保留問答框)
function refreshStrategy(){
  if(!STRATLOADED) return;
  if(document.getElementById('page-strategy').style.display==='none') return;
  loadNews(); loadSocial(); loadReddit(); loadBacktest();
}
async function askKB(){
  const q=document.getElementById('kbq').value.trim(); if(!q) return;
  const out=document.getElementById('kbout'); out.textContent='思考中…';
  try{ const r=await (await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})})).json();
    out.textContent=r.answer||JSON.stringify(r); }
  catch(e){ out.textContent='問答失敗：'+e; }
}
function fgColor(v){return v<25?'#f85149':v<45?'#d29922':v<55?'#8b949e':v<75?'#3fb950':'#2ea043';}
async function loadSocial(){
  try{
    const r=await (await fetch('/social')).json();
    const fg=r.fear_greed||{};
    let fgHtml='';
    if(fg.value!=null){
      const col=fgColor(fg.value);
      const spark=lineChart((fg.history||[]).map(h=>({t:+h.t,v:h.v})), {color:'#58a6ff', zeroFloor:true});
      const pctNote = fg.percentile!=null
        ? `歷史第 <b style="color:${col}">${fg.percentile}</b> 百分位${fg.percentile<=10?'（極罕見，越低越接近大底）':fg.percentile>=90?'（極度貪婪，留意風險）':''}`
        : '';
      fgHtml=`<div class="box">
        <h2>😱 恐懼貪婪指數 <small>全市場情緒（alternative.me，全區間 ${fg.days||''} 天 2018至今）｜極度恐懼常是反向買點</small></h2>
        <div class="kpis"><div class="kpi"><div class="v" style="color:${col};font-size:34px">${fg.value}</div>
          <div class="k">${fg.label}</div></div>
          <div class="kpi"><div class="v" style="color:${col}">${fg.percentile??'—'}%</div><div class="k">歷史百分位</div></div>
          <div style="flex:1;min-width:260px">${spark}</div></div>
        <div class="meta">${pctNote}｜區間 ${fg.hist_min}–${fg.hist_max}。對照：極度恐懼+聰明錢仍做空→順勢偏空；聰明錢開始翻多→底部反向訊號。</div>
      </div>`;
    }
    // LunarCrush 各幣社群情緒：只有付費金鑰有真實資料時才顯示（無資料不放空面板）
    const soc=r.social||{};
    let lcHtml='';
    if(r.lunarcrush_enabled && Object.keys(soc).length){
      const rows=Object.entries(soc).filter(([s])=>['BTC','ETH','SOL','HYPE','DOGE','XRP','BNB'].includes(s))
        .map(([s,v])=>{const sen=v.sentiment,col=sen>=60?'#3fb950':sen>=45?'#d29922':'#f85149';
          return `<div class="sig"><div class="sigtitle"><span>${s}</span>
            <span style="color:${col}">情緒 ${sen??'—'}% ｜ Galaxy ${v.galaxy_score??'—'}</span></div>
            <div class="socbar"><i style="width:${sen||0}%;background:${col}"></i></div></div>`;}).join('');
      lcHtml=`<div class="box"><h2>💬 各幣社群情緒（LunarCrush）</h2>${rows}</div>`;
    }
    document.getElementById('social').innerHTML=fgHtml+lcHtml;
  }catch(e){document.getElementById('social').innerHTML='<div class="box empty">情緒載入失敗：'+e+'</div>';}
}
function loadStrategy(){
  document.getElementById('page-strategy').innerHTML=`
  <section class="bt"><div class="box">
    <h2>🧠 Obsidian 策略知識庫 <small>把所有訊號變成可複盤的個人知識圖，找 alpha</small></h2>
    <p><a class="dl" href="/vault.zip">⬇ 下載 Obsidian Vault (.zip)</a></p>
    <div class="step">1. 解壓 → Obsidian「開啟資料夾作為 Vault」</div>
    <div class="step">2. 看 Graph View：訊號 ↔ 幣 ↔ KOL 連成一張圖</div>
    <div class="step">3. 內含 Coins/(40幣)、Journal/(每日快照)、KOL/、Strategies/(寫假設掛回測)</div>
    <div class="step">4. 在 Strategies 寫你的策略假設，對照 Journal 複盤、找 edge</div>
  </div></section>
  <section class="bt" id="news"><div class="empty">新聞分析載入中…</div></section>
  <section class="bt" id="social"><div class="empty">社群情緒載入中…</div></section>
  <section class="bt" id="reddit"><div class="empty">Reddit 討論熱度載入中…</div></section>
  <section class="bt"><div class="box">
    <h2>🔎 知識庫問答 <small>對累積的決策/關係問答（RAG）</small></h2>
    <div class="ask"><input id="kbq" placeholder="例：聰明錢和鯨魚現在對 ETH 的態度一致嗎？" onkeydown="if(event.key==='Enter')askKB()">
      <button onclick="askKB()">問</button></div>
    <div id="kbout" class="meta"></div>
  </div></section>
  <section class="bt" id="bt"><div class="empty">回測載入中…</div></section>`;
  loadNews(); loadSocial(); loadReddit(); loadBacktest();
}
function ago(ts){ if(!ts) return ''; const m=Math.floor((Date.now()/1000-ts)/60);
  return m<60?m+'分前':m<1440?Math.floor(m/60)+'時前':Math.floor(m/1440)+'天前'; }
async function loadNews(){
  try{
    const [r,sc]=await Promise.all([
      (await fetch('/news')).json(),
      fetch('/scores').then(x=>x.json()).then(x=>x.scores||{}).catch(()=>({}))]);
    const s=r.summary||{}, items=r.items||[];
    if(!items.length){document.getElementById('news').innerHTML='<div class="box empty">新聞暫無</div>';return;}
    const biasCol=s.net>2?'#3fb950':s.net<-2?'#f85149':'#8b949e';
    // 最受關注幣：新聞淨情緒 vs 聰明錢淨多空（分歧＝潛在反指標）
    const chips=(s.top_coins||[]).map(c=>{
      const nb=c.net>0?'#3fb950':c.net<0?'#f85149':'#8b949e';
      const smn=sc[c.symbol]&&sc[c.symbol].sm_net;
      let div='';
      if(smn!=null){ const newsBull=c.net>0, smBull=smn>0.1, smBear=smn<-0.1;
        if(newsBull&&smBear) div=' <span style="color:#d29922">⚠新聞多·聰明錢空</span>';
        else if(!newsBull&&c.net<0&&smBull) div=' <span style="color:#d29922">⚠新聞空·聰明錢多</span>'; }
      return `<span class="newschip"><b>${c.symbol}</b> <span style="color:${nb}">${c.net>0?'利多':c.net<0?'利空':'中性'} ${c.bull}/${c.bear}</span><span class="meta"> ·${c.mentions}則</span>${div}</span>`;
    }).join('');
    const rows=items.slice(0,24).map(i=>{
      const b=i.sentiment, bc=b==='bull'?'#3fb950':b==='bear'?'#f85149':'#6e7681',
            bl=b==='bull'?'利多':b==='bear'?'利空':'中性';
      const coins=(i.coins||[]).map(s=>`<span class="newscoin">${s}</span>`).join('');
      return `<div class="newsrow">
        <span class="newsbadge" style="background:${bc}22;color:${bc};border-color:${bc}55">${bl}</span>
        <a href="${i.link}" target="_blank" rel="noopener">${i.title}</a>
        <div class="meta">${coins} <span style="opacity:.7">${i.source} · ${ago(i.ts)}</span></div></div>`;
    }).join('');
    document.getElementById('news').innerHTML=`<div class="box">
      <h2>📰 新聞分析 <small>${s.sources||''} 家媒體 · ${r.total} 則 · 關鍵字利多/利空＋影響幣（呈現結論非生標題）</small></h2>
      <div class="kpis">
        <div class="kpi"><div class="v" style="color:${biasCol};font-size:30px">${s.bias||'—'}</div><div class="k">整體新聞情緒</div></div>
        <div class="kpi"><div class="v" style="color:#3fb950">${s.bull||0}</div><div class="k">利多則數</div></div>
        <div class="kpi"><div class="v" style="color:#f85149">${s.bear||0}</div><div class="k">利空則數</div></div>
        <div class="kpi"><div class="v" style="color:#8b949e">${s.neutral||0}</div><div class="k">中性</div></div>
      </div>
      <div class="meta" style="margin:6px 0 4px">最受關注幣（新聞淨情緒，⚠＝與聰明錢分歧＝潛在反指標）：</div>
      <div class="newschips">${chips||'<span class="meta">本輪新聞未明確點名單一幣</span>'}</div>
      <div class="newslist">${rows}</div>
    </div>`;
  }catch(e){document.getElementById('news').innerHTML='<div class="box empty">新聞載入失敗：'+e+'</div>';}
}
async function loadReddit(){
  try{
    const r=await (await fetch('/reddit')).json();
    const coins=r.coins||{};
    if(!r.enabled || !Object.keys(coins).length){
      document.getElementById('reddit').innerHTML=`<div class="box">
        <h2>👽 Reddit 散戶討論熱度（取代推特）</h2>
        <div class="meta">尚未啟用——到 reddit.com/prefs/apps 建 script app，設
        <b>REDDIT_CLIENT_ID</b> / <b>REDDIT_CLIENT_SECRET</b> 後自動顯示各幣討論熱度與情緒。</div></div>`;
      return;
    }
    const rows=Object.entries(coins).sort((a,b)=>b[1].mentions-a[1].mentions).slice(0,10)
      .map(([s,v])=>{const sen=v.sentiment,col=sen>=70?'#3fb950':sen>=50?'#d29922':'#f85149';
        return `<div class="sig"><div class="sigtitle"><span>${s}</span>
          <span class="meta">提及 ${v.mentions} ｜ 互動 ${(v.score+v.comments).toLocaleString()} ｜ 情緒 <b style="color:${col}">${sen??'—'}%</b></span></div></div>`;}).join('');
    document.getElementById('reddit').innerHTML=`<div class="box">
      <h2>👽 Reddit 散戶討論熱度 <small>r/CryptoCurrency+CryptoMarkets 熱門 ${r.total_posts} 篇｜散戶熱炒=反指標線索</small></h2>
      <div class="meta" style="margin-bottom:8px">用法：某幣 Reddit 討論暴增＋聰明錢在做空 → 散戶 FOMO 反指標 alpha</div>
      ${rows}</div>`;
  }catch(e){document.getElementById('reddit').innerHTML='<div class="box empty">Reddit 載入失敗：'+e+'</div>';}
}
refresh(); setInterval(refresh,30000);
setInterval(refreshStrategy,180000);   // 策略頁每 3 分鐘自動重抓(僅該頁可見時)
</script>
</body>
</html>
"""
