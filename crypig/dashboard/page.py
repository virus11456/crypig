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
  main{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));
       gap:16px;padding:24px;max-width:1200px;margin:0 auto}
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
  .sig{margin:6px 0}
  .sig .lbl{display:flex;justify-content:space-between;font-size:12px;color:var(--mut)}
  .sig .bar{height:6px;background:#21262d;border-radius:999px;margin-top:3px;overflow:hidden}
  .sig .bar i{display:block;height:6px;border-radius:999px}
  .alerts{margin-top:8px;font-size:12px;color:var(--bear)}
  .spark{margin-top:10px}
  .empty{color:var(--mut);padding:40px;text-align:center}
</style>
</head>
<body>
<header>
  <h1>🐷 Crypig 決策看板</h1>
  <span class="ts" id="ts">載入中…</span>
  <span style="flex:1"></span>
  <button id="run" onclick="runCycle()">立即跑一輪</button>
</header>
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
function sigbar(s){
  const w=Math.min(Math.abs(s.contribution)*200,100);
  return `<div class="sig"><div class="lbl"><span>${s.source}</span>
    <span style="color:${C[s.direction]}">${s.direction} · 貢獻 ${s.contribution}</span></div>
    <div class="bar"><i style="width:${Math.max(w,4)}%;background:${C[s.direction]}"></i></div>
    <div class="meta">${s.summary}</div></div>`;
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
async function loadCard(d){
  let hist=[];
  try{hist=(await (await fetch(`/decisions/history?symbol=${d.symbol}&limit=50`)).json()).history;}catch(e){}
  const con=d.consensus||{};
  return `<div class="card">
    <div class="row"><span class="sym">${d.symbol}</span>
      <span class="badge" style="background:${LBLC(d.label)}22;color:${LBLC(d.label)}">${d.label}</span></div>
    ${gauge(d.score)}
    <div class="meta">分數 ${d.score} ｜ 信心度 ${(d.confidence*100).toFixed(0)}%
      ｜ 共識 多${con.bull??0}/空${con.bear??0}/中${con.neutral??0}</div>
    <div class="action" style="color:${LBLC(d.label)}">${d.action}</div>
    <div class="reason">${d.reason}</div>
    ${(d.signals||[]).map(sigbar).join('')}
    ${(d.alerts&&d.alerts.length)?`<div class="alerts">⚠ ${d.alerts.join('<br>⚠ ')}</div>`:''}
    ${spark(hist)}
  </div>`;
}
async function refresh(){
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
