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
</style>
</head>
<body>
<header>
  <h1>🐷 Crypig 決策看板</h1>
  <span class="ts" id="ts">載入中…</span>
  <span style="flex:1"></span>
  <button id="run" onclick="runCycle()">立即跑一輪</button>
</header>
<section id="bt" class="bt"><div class="empty">回測載入中…</div></section>
<main id="cards"><div class="empty">載入中…</div></main>
<script>
const C={bull:'#3fb950',bear:'#f85149',neutral:'#8b949e'};
const LBLC=l=>l.includes('多')?C.bull:l.includes('空')?C.bear:l==='訊號分歧'?'#d29922':C.neutral;

function gauge(score){ // score -1..1
  const pct=Math.min(Math.abs(score),1)*50;
  const col=score>0?C.bull:score<0?C.bear:C.neutral;
  const style=score>=0?`left:50%;width:${pct}%`:`right:50%;width:${pct}%`;
  return `<div class="gauge"><div class="mid"></div>
          <div class="fill" style="${style};background:${col}"></div></div>`;
}
const SRC={smart_money:'🧠 聰明錢',whale_flow:'🐋 巨鯨持有者',
           divergence:'📊 量價',lth_supply:'💎 長期持有者'};
const DIRZH={bull:'偏多',bear:'偏空',neutral:'中性'};
function money(x){
  if(x==null) return '—';
  const n=Number(x);
  return '$'+n.toLocaleString('en-US',{maximumFractionDigits:n<10?4:n<1000?2:0});
}
function sigbar(s){
  const name=SRC[s.source]||s.source;
  // 無資料／不適用：忠實標示，不假裝有分析
  if(s.status==='no_data'){
    return `<div class="sig nodata">
      <div class="sigtitle"><span>${name}</span>
        <span class="chip" style="background:#8b949e22;color:#8b949e">⛔ 無資料／不適用</span></div>
      <div class="meta">${s.summary}</div></div>`;
  }
  const col=C[s.direction], sign=s.contribution>=0?'+':'';
  const w=Math.min(Math.abs(s.contribution)*200,100);
  const chip = s.status==='warming'
    ? `<span class="chip" style="background:#d2992222;color:#d29922">⏳ 蒐集中</span>`
    : `<span class="chip" style="background:${col}22;color:${col}">${DIRZH[s.direction]}</span>`;
  return `<div class="sig">
    <div class="sigtitle"><span>${name}</span>${chip}</div>
    <div class="calc">權重 ${s.weight} × 強度 ${s.magnitude} = 貢獻 <b style="color:${col}">${sign}${s.contribution}</b></div>
    <div class="bar"><i style="width:${Math.max(w,3)}%;background:${col}"></i></div>
    <div class="meta">${s.summary}</div></div>`;
}
function cbar(con){
  const b=con.bull||0,s=con.bear||0,n=con.neutral||0,t=b+s+n||1;
  return `<div class="cbar">
    <i style="width:${b/t*100}%;background:${C.bull}"></i>
    <i style="width:${s/t*100}%;background:${C.bear}"></i>
    <i style="width:${n/t*100}%;background:${C.neutral}"></i></div>`;
}
function spark(hist){
  if(hist.length<2) return '';
  const W=300,H=40,n=hist.length;
  const xs=i=>i/(n-1)*W, ys=v=>H/2-(Math.max(-1,Math.min(1,v)))*(H/2-2);
  const pts=hist.map((h,i)=>`${xs(i).toFixed(1)},${ys(h.score).toFixed(1)}`).join(' ');
  return `<svg class="spark" width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <line x1="0" y1="${H/2}" x2="${W}" y2="${H/2}" stroke="#30363d" stroke-width="1"/>
    <polyline points="${pts}" fill="none" stroke="#58a6ff" stroke-width="1.5"/></svg>`;
}
function pspark(hist){
  const pts=hist.filter(h=>h.price!=null);
  if(pts.length<2) return '';
  const W=300,H=36,n=pts.length,vs=pts.map(h=>h.price);
  const mn=Math.min(...vs),mx=Math.max(...vs),pad=(mx-mn)*0.1||1;
  const xs=i=>i/(n-1)*W, ys=v=>H-(v-(mn-pad))/((mx+pad)-(mn-pad))*H;
  const poly=vs.map((v,i)=>`${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ');
  const up=vs[vs.length-1]>=vs[0];
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline points="${poly}" fill="none" stroke="${up?C.bull:C.bear}" stroke-width="1.5"/></svg>`;
}
async function loadCard(d){
  let hist=[];
  try{hist=(await (await fetch(`/decisions/history?symbol=${d.symbol}&limit=50`)).json()).history;}catch(e){}
  const con=d.consensus||{}, ssp=spark(hist), psp=pspark(hist);
  return `<div class="card">
    <div class="row"><span class="sym">${d.symbol}</span>
      <span class="badge" style="background:${LBLC(d.label)}22;color:${LBLC(d.label)}">${d.label}</span></div>
    <div class="price">參考價 ${money(d.price)} ｜ 更新 ${new Date(d.ts).toLocaleString()}</div>
    ${gauge(d.score)}
    <div class="stats">
      <div class="stat"><div class="v" style="color:${LBLC(d.label)}">${d.score}</div><div class="k">綜合分數 −1~+1</div></div>
      <div class="stat"><div class="v">${(d.confidence*100).toFixed(0)}%</div><div class="k">信心度</div></div>
      <div class="stat"><div class="v">${money(d.price)}</div><div class="k">參考價</div></div>
    </div>
    <div class="action" style="color:${LBLC(d.label)}">${d.action}</div>
    <div class="reason">${d.reason}</div>
    <div class="sec">多空共識（加權佔比）</div>
    ${cbar(con)}
    <div class="meta">多 ${con.bull??0} ｜ 空 ${con.bear??0} ｜ 中 ${con.neutral??0}</div>
    <div class="sec">訊號明細（${(d.signals||[]).length} 項）</div>
    ${(d.signals||[]).map(sigbar).join('')}
    ${(d.alerts&&d.alerts.length)?`<div class="alerts">⚠ ${d.alerts.join('<br>⚠ ')}</div>`:''}
    ${ssp?`<div class="sec">分數走勢</div>${ssp}`:''}
    ${psp?`<div class="sec">參考價走勢</div>${psp}`:''}
  </div>`;
}
function pct(x){return x==null?'—':(x*100).toFixed(1)+'%';}
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
async function refresh(){
  loadBacktest();
  try{
    const {decisions}=await (await fetch('/decisions')).json();
    document.getElementById('ts').textContent=decisions[0]?('更新：'+new Date(decisions[0].ts).toLocaleString()):'';
    if(!decisions.length){document.getElementById('cards').innerHTML='<div class="empty">尚無決策，點「立即跑一輪」。</div>';return;}
    const html=await Promise.all(decisions.map(loadCard));
    document.getElementById('cards').innerHTML=html.join('');
  }catch(e){document.getElementById('cards').innerHTML='<div class="empty">載入失敗：'+e+'</div>';}
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
