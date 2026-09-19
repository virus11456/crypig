"""看板頁（自帶 HTML/CSS/JS，零前端建置）。

純前端輪詢 /decisions 與 /decisions/history 渲染：
  - 每幣一張卡片：方向標籤、分數量表、信心度、操作建議、理由
  - 各訊號明細條（多/空/中性著色，寬度＝貢獻度）
  - 分數歷史 sparkline（SVG）
  - 背景排程每輪自動更新並快取，頁面只讀快取；表頭顯示「最後更新：時刻（X 秒前）」持續跳動
"""

INDEX_HTML = r"""<!doctype html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover"/>
<title>Crypig 量化交易分析中台</title>
<link rel="manifest" href="/manifest.webmanifest"/>
<meta name="theme-color" content="#0d1117"/>
<meta name="apple-mobile-web-app-capable" content="yes"/>
<meta name="mobile-web-app-capable" content="yes"/>
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"/>
<meta name="apple-mobile-web-app-title" content="Crypig"/>
<link rel="apple-touch-icon" href="/static/icon-192.png"/>
<link rel="icon" type="image/png" href="/static/icon-192.png"/>
<style>
  :root{color-scheme:dark;--bg:#0d1117;--card:#161b22;--line:#30363d;--fg:#e6edf3;--mut:#8b949e;
        --bull:#3fb950;--bear:#f85149;--neu:#8b949e;--accent:#58a6ff}
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:-apple-system,Segoe UI,Roboto,"Noto Sans TC",sans-serif}
  header{display:flex;align-items:center;flex-wrap:wrap;gap:12px 16px;padding:16px 24px;
         border-bottom:1px solid var(--line);position:sticky;top:0;z-index:5;
         background:var(--bg);padding-top:max(16px,env(safe-area-inset-top))}
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
  .meta a,.meta a:visited{color:#8cc8ff;text-decoration:underline;text-decoration-color:#52789a;text-underline-offset:3px;text-decoration-thickness:1px}
  .meta a:hover,.meta a:active{color:#c3e3ff;text-decoration-color:currentColor}
  .meta a:focus-visible{outline:2px solid #8cc8ff;outline-offset:3px;border-radius:2px}
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
  .sites{display:flex;flex-wrap:wrap;align-items:center;gap:4px 14px}
  .sites a{display:inline-flex;align-items:center;color:#9eacba;text-decoration:none;
           font-size:13px;font-weight:600;padding:6px 2px;border-bottom:1px solid transparent}
  .sites a:hover,.sites a:active{color:var(--accent);border-bottom-color:var(--accent)}
  .sites a:focus-visible{outline:2px solid #9ad5ff;outline-offset:3px;border-radius:2px}
  .sites > span{color:#6e7681;font-size:12px;font-weight:600;letter-spacing:.04em;white-space:nowrap}
  header .sites{margin-left:4px;padding-left:14px;border-left:1px solid var(--line)}
  header .sites.related{width:100%;margin-left:0;padding-left:0;border-left:0}
  footer{border-top:1px solid var(--line);padding:12px 24px;
         padding-bottom:max(12px,env(safe-area-inset-bottom));
         display:flex;flex-wrap:wrap;align-items:center;gap:8px 18px;background:var(--bg)}
  footer .simples{margin-left:auto;color:#6e7681;font-size:12px;text-decoration:none;letter-spacing:.04em}
  footer .simples:hover,footer .simples:active{color:var(--mut)}
  footer .simples:focus-visible{outline:2px solid #9ad5ff;outline-offset:3px;border-radius:2px}
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
  table.vt{width:100%;border-collapse:collapse;font-size:13px;margin-top:4px}
  table.vt th{text-align:right;color:#8b949e;font-weight:500;padding:4px 6px;border-bottom:1px solid #21262d}
  table.vt th:first-child{text-align:left}
  table.vt td{padding:4px 6px;border-bottom:1px solid #161b22}
  table.vt td:first-child{text-align:left;color:#c9d1d9}
  .newslist{max-height:420px;overflow:auto;border-top:1px solid #21262d;margin-top:6px}
  .newsrow{padding:9px 2px;border-bottom:1px solid #161b22}
  .newsrow a{color:#c9d1d9;text-decoration:none}
  .newsrow a:hover{color:#58a6ff;text-decoration:underline}
  .newsbadge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:6px;border:1px solid;margin-right:8px;vertical-align:middle}
  .newscoin{display:inline-block;font-size:11px;background:#1f2937;color:#9ecbff;border-radius:5px;padding:1px 6px;margin-right:4px}
  .posrow{margin:10px 0;padding:10px 12px;background:#0d1117;border:1px solid var(--line);border-radius:8px}
  .posname{font-size:15px;margin-bottom:7px}
  .posstats{display:flex;flex-wrap:wrap;gap:6px 8px;font-size:13px}
  .pchip{background:#161b22;border:1px solid #21262d;border-radius:6px;padding:3px 9px;white-space:nowrap}
  /* ---- RWD：平板/手機 ---- */
  @media (max-width:820px){
    main{grid-template-columns:1fr;padding:14px;gap:14px}
    .bt{padding:0 14px;margin-top:14px}
  }
  @media (max-width:560px){
    header{padding:12px 14px;gap:8px 10px}
    header h1{font-size:16px;width:100%}
    header .nav{margin-left:0}
    header .sites{margin-left:0;padding-left:0;border-left:0;width:100%}
    header .ts{font-size:11px;order:3;width:100%}
    footer{padding:12px 14px}
    footer .simples{margin-left:0}
    .nav button{padding:7px 10px;font-size:13px}
    main{padding:10px;gap:10px}
    .bt{padding:0 10px;margin-top:10px}
    .bt .box{padding:13px}
    .bt h2{font-size:14px}
    .kpis{display:grid;grid-template-columns:repeat(3,1fr);gap:10px 8px}
    .kpis>div[style*="flex:1"]{grid-column:1/-1}   /* 圖表那格獨佔整列 */
    .kpi .v{font-size:18px}
    .kpi .k{font-size:11px}
    .posrow{padding:9px 10px}
    .posstats{font-size:12px;gap:5px 6px}
    .pchip{padding:3px 7px}
    .ratios{gap:10px 14px}
    .ask{flex-wrap:wrap}
    .ask input{min-width:0}
    .tbl{font-size:12px}
    .tbl th,.tbl td{padding:6px 7px}
    .scroll{max-height:62vh}
    .newslist{max-height:60vh}
  }
  @media (max-width:380px){ .kpi .v{font-size:18px} .tbl{font-size:11px} }
  /* ===== 重新設計：進場機會 hero + 可折疊摘要卡 ===== */
  .wrap{max-width:1400px;margin:0 auto;padding:18px 24px;display:flex;flex-direction:column;gap:14px}
  .hero{background:linear-gradient(160deg,#161b22,#11161d);border:1px solid var(--line);
        border-radius:14px;padding:18px 20px}
  .hero h2{margin:0 0 2px;font-size:14px;color:var(--mut);font-weight:600;letter-spacing:.3px}
  .hero .verdict{font-size:21px;font-weight:800;line-height:1.35;margin:6px 0}
  .hero .conv{font-size:14px;font-weight:700;margin:4px 0 2px}
  .heroline{display:flex;flex-wrap:wrap;gap:10px;margin-top:10px}
  .htag{background:#0d1117;border:1px solid var(--line);border-radius:999px;
        padding:6px 12px;font-size:13px;white-space:nowrap}
  .opps{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px;margin-top:14px}
  .opp{background:#0d1117;border:1px solid var(--line);border-radius:10px;padding:12px;cursor:default}
  .opp .ot{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:4px 6px;margin-bottom:8px}
  .opp .osym{font-size:16px;font-weight:800;min-width:0;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
  .opp .ot .chip{flex:none;white-space:nowrap}
  .vs{display:flex;align-items:center;gap:6px;font-size:12px;margin:7px 0}
  .vs .lab{width:38px;color:var(--mut)}
  .vsbar{flex:1;height:7px;background:#21262d;border-radius:999px;position:relative;overflow:hidden}
  .vsbar i{position:absolute;top:0;height:7px;border-radius:999px}
  .vsbar .mid{position:absolute;left:50%;top:-2px;width:1px;height:11px;background:#3a4250}
  /* 訊號驗證：白話結論＋視覺 edge 長條 */
  .vsig{border-top:1px solid var(--line);padding-top:12px;margin-top:14px}
  .vsig:first-of-type{border-top:0;padding-top:0;margin-top:0}
  .vhead{font-weight:700;font-size:14px;margin-bottom:4px}
  .vsub{color:var(--mut);font-weight:400;font-size:12px}
  .vverdict{font-size:13px;margin:6px 0 10px;padding:8px 11px;border-radius:8px;
            background:#0d1117;border-left:3px solid var(--accent);line-height:1.5}
  .ctip{position:fixed;z-index:50;pointer-events:none;background:#0d1117;border:1px solid var(--line);
        border-radius:6px;padding:5px 9px;font-size:12px;color:#e6edf3;white-space:nowrap;display:none;
        box-shadow:0 4px 14px rgba(0,0,0,.5)}
  .combo{background:linear-gradient(180deg,#161b22,#11161d);border:1px solid;border-left-width:5px;
         border-radius:12px;padding:13px 16px;font-size:14px;line-height:1.55}
  .combo .ct{font-weight:800;margin-right:6px;white-space:nowrap}
  .rtoggle{display:inline-flex;border:1px solid var(--line);border-radius:7px;overflow:hidden;flex:none}
  .rtoggle button{background:#0d1117;color:var(--mut);font-weight:600;font-size:12px;
        padding:5px 12px;border:0;border-radius:0;white-space:nowrap}
  .rtoggle button.on{background:var(--accent);color:#0d1117}
  .vsec{font-size:12px;color:var(--mut);font-weight:700;margin:16px 0 8px;
        border-top:1px solid var(--line);padding-top:12px}
  .acc{font-size:13px;line-height:1.55;padding:9px 12px;border-radius:8px;background:#11161d;
       border-left:4px solid #6e7681;color:#c9d1d9}
  .vline{font-size:13px;line-height:1.5;margin:0 0 12px;padding:9px 12px;border-radius:8px;
         background:#11161d;border-left:4px solid var(--accent)}
  .nowbox{font-size:13px;line-height:1.55;margin:8px 0 10px;padding:10px 12px;border-radius:8px;
          background:#11161d;border:1px solid;border-left-width:4px}
  .nowtag{font-size:10px;background:#1f6feb;color:#fff;border-radius:4px;padding:1px 5px;margin-left:5px;vertical-align:middle}
  .wrow.now{background:#1c2230;border-radius:5px;padding:3px 4px;margin:0 -4px}
  .wrhead{font-size:12px;color:var(--mut);margin:2px 0 8px}
  .ebars{display:flex;flex-direction:column;gap:6px}
  .wrow{display:flex;align-items:center;gap:10px;font-size:12px}
  .wlab{width:128px;flex:none;color:#c9d1d9;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .wtrack{flex:1;height:18px;background:#0d1117;border:1px solid var(--line);border-radius:4px;position:relative;overflow:hidden}
  .wfill{position:absolute;left:0;top:0;bottom:0;border-radius:3px 0 0 3px;opacity:.85}
  .wbase{position:absolute;top:-2px;bottom:-2px;width:2px;background:#c9d1d9;z-index:2}
  .wpct{width:40px;flex:none;text-align:right;font-weight:700}
  .wret{width:74px;flex:none;text-align:right;color:var(--mut)}
  .wtag{width:104px;flex:none;text-align:right;font-weight:600}
  .en{width:44px;flex:none;text-align:right;color:var(--mut);font-size:11px}
  @media (max-width:680px){ .wlab{width:88px} .wret,.wtag{display:none} }
  .moredt{margin-top:8px}
  .moredt>summary{cursor:pointer;color:var(--accent);font-size:12px;user-select:none}
  @media (max-width:560px){ .eblab{width:104px;font-size:11px} .vsub{display:block;margin-top:2px} }
  /* 折疊卡：<details> 摘要＋點開細節 */
  details.ccard{background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
  details.ccard>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:12px;
        padding:14px 18px;user-select:none}
  details.ccard>summary::-webkit-details-marker{display:none}
  details.ccard>summary:hover{background:#1a212b}
  .ctitle{font-weight:700;font-size:15px;white-space:nowrap}
  .csum{color:var(--mut);font-size:13px;flex:1;min-width:0;overflow:hidden;
        text-overflow:ellipsis;white-space:nowrap}
  .chev{color:var(--mut);transition:transform .2s;font-size:12px}
  details.ccard[open]>summary{border-bottom:1px solid var(--line)}
  details.ccard[open]>summary .chev{transform:rotate(180deg)}
  /* 卡內沿用既有渲染，但去掉內層 box 的框/底色避免雙重邊框 */
  details.ccard .box{background:transparent;border:0;border-radius:0;padding:14px 18px 18px}
  details.ccard .box>h2:first-child,
  details.ccard .box .row>h2{display:none}   /* 標題已在卡頭，內層 h2 隱藏免重複(含幣別總表包在 .row 裡的) */
  details.ccard .box.empty{padding:28px;display:block}
  @media (max-width:560px){
    .wrap{padding:12px 12px}
    .hero{padding:14px 14px;border-radius:12px}
    .hero .verdict{font-size:18px}
    details.ccard>summary{padding:12px 14px;gap:8px}
    details.ccard .box{padding:12px 14px 14px}
    .opps{grid-template-columns:1fr 1fr;gap:8px}
  }
.behavior-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.behavior-card{padding:16px;background:#101820;border:1px solid #303943;border-radius:10px;line-height:1.8}.behavior-card strong{font-size:23px}.activity-controls{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}.activity-controls select{background:#161f28;color:#e6edf3;border:1px solid #465363;padding:8px;border-radius:6px}.activity-table{overflow:auto}.activity-table table{width:100%;white-space:nowrap}.activity-table button{color:#79b8ff;background:none;border:0;cursor:pointer}.activity-kpis{display:flex;gap:24px;flex-wrap:wrap;margin:16px 0}.activity-kpis strong{font-size:22px;display:block}@media(max-width:800px){.behavior-grid{grid-template-columns:1fr}}

.reading-guide{padding:24px 0 30px}.reading-guide h2{font-size:clamp(23px,3vw,32px);margin:8px 0 14px;line-height:1.5}.reading-guide p{max-width:780px;color:#aab8c6;line-height:1.8}.eyebrow{font-size:12px;letter-spacing:.14em}.reading-guide nav{display:flex;flex-wrap:wrap;gap:10px;margin-top:20px}.reading-guide a,.detail-link{display:inline-block;color:#a7d5ff;background:#182430;border:1px solid #35475a;border-radius:8px;padding:10px 14px;text-decoration:none;font-size:14px;cursor:pointer}.population{padding:24px;margin-bottom:24px;border:1px solid #344453;border-radius:16px;background:#101820;scroll-margin-top:90px}.population-heading{display:flex;gap:16px;align-items:flex-start;margin-bottom:20px}.population-number{font-size:14px;color:#91b5d2;padding:8px;border:1px solid #35475a;border-radius:8px}.population h2{font-size:26px;margin:0 0 8px}.population-heading p{margin:0;color:#aab8c6;line-height:1.6}.population h3{font-size:14px;color:#aab8c6;margin:0 0 12px}.brief-main{font-size:19px;line-height:1.8;margin:0 0 12px;color:#edf5fc}.brief-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px}.reading-hint{border-top:1px solid #2b3b49;padding-top:16px;margin:18px 0;color:#b2c3d1;line-height:1.8;font-size:14px}.population .ccard{margin:12px 0;background:#0d141c}.population .detail-link{margin:8px 8px 0 0}.market-support{padding-top:20px;scroll-margin-top:90px}.market-support>h2{font-size:23px}.market-support>.meta{margin-bottom:24px}#account-inspector{scroll-margin-top:90px}a:focus-visible,button:focus-visible,summary:focus-visible{outline:2px solid #9ad5ff;outline-offset:4px}@media(max-width:700px){.population{padding:18px 14px}.brief-grid{grid-template-columns:1fr;gap:20px}.brief-grid>div+div{border-top:1px solid #2b3b49;padding-top:20px}.population .csum{display:none}.brief-main{font-size:17px}.reading-guide h2{font-size:24px}}

/* Responsive layout: preserve content, contain wide tables, wrap card controls. */
html{-webkit-text-size-adjust:100%;scroll-padding-top:100px}
.wrap>* ,.population-heading>div,.brief-grid>div,.box,.row>*{min-width:0}
.brief-grid{grid-template-columns:repeat(2,minmax(0,1fr))}
.row{flex-wrap:wrap;gap:8px}
.ctitle{white-space:normal;overflow-wrap:anywhere;min-width:0}
.chev{flex:none;margin-left:auto}
.meta,.reason,.step,.reading-hint,.brief-main{overflow-wrap:anywhere}
.pchip,.htag{white-space:normal;overflow-wrap:anywhere;max-width:100%}
.scroll,.activity-table{max-width:100%;overscroll-behavior-x:contain}
.activity-controls select,.filt{max-width:100%;min-width:0}
.kpis>*{min-width:0;max-width:100%}
.kpis .chart-kpi{flex:1 1 260px;min-width:0;max-width:100%}
.ctip{max-width:calc(100vw - 20px);white-space:normal;overflow-wrap:anywhere}
@media(max-width:1024px){
 header{position:relative;padding-left:max(14px,env(safe-area-inset-left));padding-right:max(14px,env(safe-area-inset-right));padding-top:max(12px,env(safe-area-inset-top))}
 footer{padding-left:max(14px,env(safe-area-inset-left));padding-right:max(14px,env(safe-area-inset-right));padding-bottom:max(12px,env(safe-area-inset-bottom))}
 .wrap{padding-left:max(14px,env(safe-area-inset-left));padding-right:max(14px,env(safe-area-inset-right));padding-bottom:max(18px,env(safe-area-inset-bottom))}
 .ctitle{flex:1}.csum{flex-basis:100%;order:3;white-space:normal}
 details.ccard>summary{flex-wrap:wrap;gap:8px;align-items:flex-start}
 .population .csum{display:none}
 button,.rtoggle button,.activity-controls select,.filt,.dl,.detail-link,.reading-guide a,.sites a{min-height:44px}
 input,select{font-size:16px!important}
 .reading-guide{padding:12px 0 18px}
 .population{padding:20px;margin-bottom:10px}
 .brief-grid{grid-template-columns:1fr}
 .brief-grid>div+div{border-top:1px solid #2b3b49;padding-top:20px}
 .population,#account-inspector,.market-support{scroll-margin-top:16px}
 html{scroll-padding-top:0}
}
@media(max-width:560px){
 .population{padding:16px 12px}.population-heading{gap:10px}.population h2{font-size:23px}
 .nav{flex-wrap:wrap;margin-left:0;max-width:100%}.nav button{padding:8px 10px}
 .kpis{grid-template-columns:repeat(2,minmax(0,1fr))}.kpis .chart-kpi{grid-column:1/-1}
 .activity-controls label{display:flex;flex-wrap:wrap;gap:6px;align-items:center;max-width:100%}
 .activity-controls select{width:100%}
 .stats{grid-template-columns:repeat(2,minmax(0,1fr))}
 .opps{grid-template-columns:minmax(0,1fr)}
 .ask input{flex-basis:100%}.conf{flex-wrap:wrap;gap:8px}
 .reading-guide nav{gap:8px}.reading-guide a{flex:1 1 calc(50% - 8px);text-align:center}
}

/* Group balances: distinct overview, comparison, and history. */
.balance-panel{font-variant-numeric:tabular-nums}
details.ccard .box.balance-panel{padding:24px}
.balance-overview{padding:0 0 24px}.balance-kicker{font-size:12px;color:#8ea9bf;letter-spacing:.1em}.balance-overview>p{font-size:21px;line-height:1.6;margin:8px 0}
.balance-desktop{overflow-x:auto;border:1px solid #2b3947;border-radius:10px}
.balance-table{width:100%;border-collapse:collapse;font-size:14px;white-space:nowrap}
.balance-table caption{text-align:left;padding:16px 20px;background:#141f2a;font-weight:600}.balance-table caption span{float:right;color:#93a4b5;font-size:12px;font-weight:400}
.balance-table th,.balance-table td{padding:18px 20px;text-align:right;border-bottom:1px solid #263340}
.balance-table thead th{color:#9eafbf;font-size:12px;font-weight:500;background:#111b24}
.balance-table th:first-child{text-align:left}.balance-table tbody th{font-weight:500}.balance-value{font-weight:650;color:#eef4fa}
.balance-total{background:#172636}.balance-table .balance-total th,.balance-table .balance-total td{font-weight:650;border-bottom:0}
.balance-change{white-space:nowrap}.balance-change.increase{color:#79d8ad}.balance-change.decrease{color:#ff9a9a}.balance-change.missing{color:#9eafbf;font-size:12px}
.balance-mobile{display:none}.balance-trend-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin:32px 0 20px}.balance-trend-heading h3{color:#e6edf3;font-size:17px;margin:0 0 6px}
.balance-chart{padding:20px;margin:16px 0;background:#101923;border:1px solid #263340;border-radius:10px}.balance-chart h4{font-size:14px;margin:0 0 6px}.balance-chart .meta{margin-bottom:18px}
.balance-chart-scroll{overflow-x:auto}.balance-chart-scroll svg{display:block;min-width:560px}
.balance-notes{margin-top:24px;border-top:1px solid #2b3947;padding-top:18px;color:#9eafbf;font-size:13px;line-height:1.8}.balance-notes summary{cursor:pointer;color:#a9bdd0}.balance-notes a{color:#91c8f7}
.activity-table{border:1px solid #2b3947;border-radius:9px;margin:16px 0;font-variant-numeric:tabular-nums}.activity-table table{border-collapse:collapse;font-size:14px}.activity-table th,.activity-table td{padding:14px 18px;text-align:right;border-bottom:1px solid #263340}.activity-table th{background:#15212c;color:#a9bdd0;font-size:12px;font-weight:500}.activity-table th:first-child,.activity-table td:first-child{text-align:left}.activity-table button{padding:6px 0}.activity-table tbody tr:last-child td{border-bottom:0}
@media(max-width:900px){.balance-desktop{display:none}.balance-mobile{display:grid;gap:12px}.balance-card{padding:20px;border:1px solid #2b3947;border-radius:10px;background:#111c26}.balance-card.balance-total{background:#172636}.balance-card h4{font-size:14px;margin:0 0 18px;color:#c6d6e5}.balance-current{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;margin:0 0 18px}.balance-current>span{font-size:12px;color:#9eafbf}.balance-current strong{font-size:24px}.balance-current small{font-size:12px;color:#9eafbf;font-weight:400}.balance-card dl{margin:0;border-top:1px solid #2b3947;padding-top:10px}.balance-card dl>div{display:flex;justify-content:space-between;align-items:center;padding:8px 0;gap:16px}.balance-card dt{font-size:13px;color:#9eafbf}.balance-card dd{margin:0;font-size:15px}.balance-chart{padding:16px}.balance-chart-scroll:after{content:'左右滑動圖表查看完整日期';display:block;color:#9eafbf;font-size:11px;margin-top:12px}}
@media(max-width:560px){details.ccard .box.balance-panel{padding:16px 12px}.balance-overview>p{font-size:18px}.balance-card{padding:16px}.balance-trend-heading{flex-wrap:wrap}.balance-chart{padding:12px}.balance-chart h4{line-height:1.6}}

/* Shared reading rhythm across market and strategy panels. */
.wrap{max-width:1280px;gap:20px}.box{line-height:1.65}.meta{line-height:1.75;color:#9eacba}.box>.meta{margin:10px 0 16px}
.market-support>details.ccard{margin:16px 0}.ctitle{font-size:16px;line-height:1.6}.csum{font-size:13px;line-height:1.65}
details.ccard>summary{padding:18px 22px}details.ccard .box{padding:22px}details.ccard[open]>summary{background:#14202b}
.kpis{gap:14px;align-items:stretch;margin:18px 0}.kpis>.kpi{flex:1 1 140px;padding:16px;background:#101a24;border:1px solid #263340;border-radius:9px}.kpi .v{font-variant-numeric:tabular-nums;font-size:24px;line-height:1.3}.kpi .k{margin-top:8px;line-height:1.6;font-size:12px}
.activity-kpis{gap:14px}.activity-kpis>div{padding:16px;background:#111c26;border:1px solid #2b3947;border-radius:9px;flex:1 1 160px}.activity-controls{padding:14px;background:#101a24;border-radius:8px;gap:16px}.activity-controls label{line-height:2}
.tbl th,.tbl td{padding:13px 16px;font-variant-numeric:tabular-nums}.tbl th{font-size:12px}.scroll{border:1px solid #263340}.tbl tbody tr:nth-child(even){background:#111b25}
table.vt{font-variant-numeric:tabular-nums;table-layout:fixed}table.vt th,table.vt td{padding:10px 8px;line-height:1.7;overflow-wrap:anywhere}table.vt tbody tr:nth-child(even){background:#111b25}
.posrow{padding:18px;margin:16px 0}.posname{margin-bottom:14px}.posstats{gap:10px}.pchip{padding:8px 12px}.newsrow{padding:16px 4px;line-height:1.7}.newsrow a{font-size:15px}.newslist{padding-right:10px}.sig,.nowbox,.vline,.vverdict{padding:14px 16px;line-height:1.8}.vsig{padding-top:24px;margin-top:24px}.vhead{font-size:16px;line-height:1.7}
.chart-scroll{overflow-x:auto;max-width:100%;margin:18px 0;overscroll-behavior-x:contain}.chart-scroll>svg{display:block;min-width:680px}.chart-scroll:focus-visible{outline:2px solid #91c8f7;outline-offset:3px}
@media(max-width:900px){.chart-scroll:after{content:'左右滑動查看日期與數值 · 點圖查看明細';display:block;color:#9eacba;font-size:12px;margin-top:10px;line-height:1.6}.balance-chart-scroll:after{content:none}}
@media(max-width:560px){.wrap{gap:16px}details.ccard>summary{padding:16px 14px}details.ccard .box{padding:18px 14px}.ctitle{font-size:14px}.kpis>.kpi{padding:12px}.kpi .v{font-size:21px}.pchip{padding:6px 9px}.activity-kpis>div{flex-basis:100%}.tbl th,.tbl td{padding:12px}.posrow{padding:14px}.activity-table th,.activity-table td{padding:12px 14px}}
.strategy-table-scroll{overflow-x:auto;margin:16px 0;border:1px solid #263340;border-radius:8px}.strategy-table-scroll table.vt{min-width:580px;table-layout:auto;margin:0}.strategy-table-scroll table.vt td,.strategy-table-scroll table.vt th{white-space:nowrap;padding:14px 18px;overflow-wrap:normal}.strategy-table-scroll table.vt td:not(:first-child){text-align:right}@media(max-width:680px){.strategy-table-scroll:after{content:'左右滑動查看完整欄位';display:block;font-size:12px;color:#9eacba;padding:10px}}
*{scrollbar-color:#465b6e #111b25;scrollbar-width:thin}

.replay-panel{background:linear-gradient(140deg,#142634,#101923);border:1px solid #385166;border-radius:16px;padding:24px;overflow:hidden}.replay-heading{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}.replay-heading h2{margin:8px 0;font-size:24px}.replay-heading .eyebrow{margin:0;color:#a7cadb}.replay-controls{display:flex;gap:12px;align-items:center;flex-wrap:wrap;margin:24px 0 16px}.replay-controls label{font-size:13px;color:#aabaca;display:flex;gap:8px;align-items:center}.replay-controls select{min-height:44px;padding:8px;color:#e6edf3;background:#101923;border:1px solid #476174;border-radius:6px;max-width:100%}.replay-controls button,.replay-heading button{min-height:44px}.replay-time{font-variant-numeric:tabular-nums;line-height:1.8;color:#c8dce9;font-size:14px}#replay-slider{width:100%;min-height:44px;accent-color:#67d6e8;cursor:pointer}#replay-chart{max-width:100%;overflow-x:auto}#replay-chart svg{width:100%;min-width:460px;display:block;max-height:330px}.replay-details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.replay-details article{padding:16px;background:#101b26;border:1px solid #304454;border-radius:10px;line-height:1.7}.replay-details h3{font-size:14px;margin:0 0 10px;color:#c9e1ed}.replay-details p{margin:8px 0;font-size:14px}@media(max-width:700px){.replay-panel{padding:18px 14px}.replay-heading h2{font-size:21px}.replay-details{grid-template-columns:1fr}.replay-controls label{flex-wrap:wrap}.replay-controls{gap:10px}#replay-chart:after{content:'左右滑動看完整多空長條';font-size:12px;color:#9eacba;display:block;margin:8px 0}}
.replay-axis,.replay-values{display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap;font-variant-numeric:tabular-nums}.replay-axis{font-size:13px;color:#aabaca;margin:20px 0}.replay-track-row{margin:22px 0}.replay-track-row h4{margin:0 0 12px;font-size:15px}.replay-tracks{display:grid;grid-template-columns:1fr 1fr;gap:2px}.replay-tracks>div{height:32px;background:#243644;display:flex;align-items:center;min-width:0}.replay-tracks .replay-short{justify-content:flex-end;border-right:1px solid #c2d7e3}.replay-tracks i{height:24px;display:block;border-radius:3px}.replay-tracks span{font-size:12px;color:#aabaca;padding:4px}.replay-values{font-size:15px;margin-top:10px}.replay-details .meta{font-size:12px}#replay-chart:after{content:none}
</style>
</head>
<body>
<header>
  <h1>🐷 大戶行為觀察台</h1>
  <span class="nav">
    <button id="nav-market" class="on" onclick="stopReplay();showPage('market')">📊 行為觀察</button>
    <button id="nav-strategy" onclick="stopReplay();showPage('strategy')">🧠 策略 / Obsidian</button>
  </span>
  <nav class="sites" aria-label="其他工具">
    <a href="https://warhubs.com/" title="WARHUBS" rel="noopener noreferrer">戰情觀測站</a>
    <a href="https://stocktools.cc/" title="Stocktools" rel="noopener noreferrer">美股雙重分析</a>
    <a href="https://toolist.cc/" title="Toolist" rel="noopener noreferrer">分頁工作區</a>
  </nav>
  <nav class="sites" aria-label="交易所開戶">
    <a href="https://okx.com/join/75395880" title="OKX" target="_blank" rel="noopener noreferrer">OKX 開戶</a>
    <a href="https://www.pionex.com/zh-TW/signUp?r=0rcgGsu5GKg" title="派網" target="_blank" rel="noopener noreferrer">派網開戶</a>
  </nav>
  <span style="flex:1"></span>
  <span class="ts" id="ts">載入中…</span>
  <nav class="sites related" aria-label="相關工具">
    <span>相關工具</span>
    <a href="https://www.stocktools.cc/tw/us-fee-calculator" title="Stocktools 美股手續費" target="_blank" rel="noopener noreferrer">美股手續費</a>
    <a href="https://www.stocktools.cc/tw/us-etf" title="Stocktools 美股 ETF" target="_blank" rel="noopener noreferrer">美股 ETF</a>
    <a href="https://www.stocktools.cc/tw/us-deposit" title="Stocktools 美股入金" target="_blank" rel="noopener noreferrer">美股入金</a>
    <a href="https://www.stocktools.cc/tw/us-open-account" title="Stocktools 美股開戶" target="_blank" rel="noopener noreferrer">美股開戶</a>
    <a href="https://www.stocktools.cc/tw/us-dividend" title="Stocktools 美股配息" target="_blank" rel="noopener noreferrer">美股配息</a>
    <a href="https://www.stocktools.cc/tw/us-first-buy" title="Stocktools 第一次買美股" target="_blank" rel="noopener noreferrer">第一次買美股</a>
    <a href="https://www.stocktools.cc/tw/us-premarket" title="Stocktools 美股盤前盤後" target="_blank" rel="noopener noreferrer">美股盤前盤後</a>
    <a href="https://www.stocktools.cc/tw/us-order-types" title="Stocktools 市價／限價" target="_blank" rel="noopener noreferrer">市價／限價</a>
    <a href="https://www.stocktools.cc/tw/us-adr" title="Stocktools 美股 ADR" target="_blank" rel="noopener noreferrer">美股 ADR</a>
    <a href="https://www.stocktools.cc/tw/us-fx" title="Stocktools 美股匯損" target="_blank" rel="noopener noreferrer">美股匯損</a>
  </nav>
</header>
<div id="ctip" class="ctip"></div>
<div id="page-strategy" style="display:none"></div>
<div id="page-market"><div class="wrap">
  <div id="bigmoney"></div>
  <section class="replay-panel" aria-labelledby="replay-heading">
    <div class="replay-heading"><div><p class="eyebrow">BTC 合約 · 歷史快照</p><h2 id="replay-heading">巨鯨 × 聰明錢｜持倉回放</h2></div><button id="replay-load" onclick="loadReplay()">開啟回放</button></div>
    <p class="meta">看多倉與空倉如何隨時間變動。只播放已保存的 BTC 數量；不代表現貨買賣或資金在群體之間流動。群體可能重疊，不加總。</p>
    <div id="replay-content" hidden>
      <div class="replay-controls"><button id="replay-play" onclick="toggleReplay()">播放</button><label>期間 <select id="replay-range" onchange="setReplayRange(this.value)"><option value="24h">近24小時</option><option value="7d">近7天</option></select></label><label>聰明錢分組 <select id="replay-group" onchange="setReplayGroup(this.value)"><option value="smart_verified">已驗證組</option><option value="smart_pnl_only">歷史獲利補入組</option></select></label><label>速度 <select id="replay-speed" onchange="REPLAY_SPEED=Number(this.value)"><option value="1000">每秒1筆</option><option value="2000">每2秒1筆</option><option value="500">每秒2筆</option></select></label></div>
      <p id="replay-time" class="replay-time"></p>
      <input id="replay-slider" type="range" min="0" max="0" value="0" step="1" aria-label="選擇已保存快照" oninput="seekReplay(this.value)"/>
      <div id="replay-chart"></div><div id="replay-details" class="replay-details"></div>
    </div><p id="replay-status" class="meta">按「開啟回放」讀取歷史，不會重新抓取持倉。</p>
  </section>
  <section class="population" id="group-whales" aria-labelledby="heading-whales">
    <div class="population-heading"><span class="population-number">01</span><div><h2 id="heading-whales">巨鯨</h2><p>先分清現貨地址，再看合約大額帳號。</p></div></div>
    <div id="brief-whales" class="population-brief">資料載入中…</div>
  <details class="ccard">
    <summary><span class="ctitle">🪙 BTC 現貨地址餘額分組 <small style="opacity:.7">鏈上現貨</small></span><span class="csum" id="sum-onchain">載入中…</span><span class="chev">▾</span></summary>
    <div id="onchainwhale"><div class="box empty">鏈上巨鯨持幣量載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">🐋 合約大額帳號 BTC 淨持倉變化 <small style="opacity:.7">合約</small></span><span class="csum" id="sum-whale">載入中…</span><span class="chev">▾</span></summary>
    <div id="whalechart"><div class="box empty">大額帳號 BTC 合約部位載入中…</div></div>
  </details>
    <button class="detail-link" onclick="openAccountGroup('whale')">查閱大額帳號異動 →</button>
  </section>
  <section class="population" id="group-smart" aria-labelledby="heading-smart">
    <div class="population-heading"><span class="population-number">02</span><div><h2 id="heading-smart">聰明錢</h2><p>先看同一批帳號的 BTC 合約數量，再看群體趨勢。</p></div></div>
    <div id="brief-smart" class="population-brief">資料載入中…</div>
  <details class="ccard">
    <summary><span class="ctitle">🧠 聰明錢 BTC 淨持倉變化 <small style="opacity:.7">合約</small></span><span class="csum" id="sum-smartbtc">載入中…</span><span class="chev">▾</span></summary>
    <div id="smartbtc"><div class="box empty">聰明錢 BTC 合約分析載入中…</div></div>
  </details>
    <button class="detail-link" onclick="openAccountGroup('smart_verified')">查閱已驗證帳號異動 →</button>
    <button class="detail-link" onclick="openAccountGroup('smart_pnl_only')">查看歷史獲利補入組 →</button>
  </section>
  <section class="population" id="group-lth" aria-labelledby="heading-lth">
    <div class="population-heading"><span class="population-number">03</span><div><h2 id="heading-lth">長期持有者</h2><p>看舊幣供給如何變化，先比較近 7 天與近 30 天。</p></div></div>
    <div id="brief-lth" class="population-brief">資料載入中…</div>
  <details class="ccard">
    <summary><span class="ctitle">⏳ 長期持有者 BTC 供給變化</span><span class="csum" id="sum-lth">載入中…</span><span class="chev">▾</span></summary>
    <div id="lth"><div class="box empty">長期持有者日資料載入中…</div></div>
  </details>
  </section>
  <details class="ccard" id="account-inspector"><summary><span class="ctitle">同帳號異動明細</span><span class="chev">▾</span></summary>
    <section id="account-activity" class="box"><h2>同帳號 BTC 合約異動</h2><p class="meta">載入中…</p></section>
  </details>
  <section id="market-support" class="market-support" aria-labelledby="heading-support">
    <h2 id="heading-support">市場背景與其他資料</h2>
    <p class="meta">看完三類群體，再用行情、資金與情緒補充背景；這些指標不能代替群體的實際動作。</p>
  <details class="ccard">
    <summary><span class="ctitle">🌐 全市場宏觀</span><span class="csum" id="sum-macro">載入中…</span><span class="chev">▾</span></summary>
    <div id="macro"><div class="box empty">宏觀載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">💰 資金動向</span><span class="csum" id="sum-defi">載入中…</span><span class="chev">▾</span></summary>
    <div id="defi"><div class="box empty">資金動向載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">💵 穩定幣總供應</span><span class="csum" id="sum-stable">載入中…</span><span class="chev">▾</span></summary>
    <div id="stablecoins"><div class="box empty">穩定幣總供應載入中…</div></div>
  </details>
<details class="ccard"><summary><span class="ctitle">情緒與合約部位分歧</span><span class="chev">▾</span></summary>  <section id="opp" class="hero"><h2>🎯 情緒與合約部位分歧</h2><div class="meta">載入中…</div></section></details>
  <details class="ccard">
    <summary><span class="ctitle">🎯 分歧雷達</span><span class="csum" id="sum-radar">載入中…</span><span class="chev">▾</span></summary>
    <div id="radar"><div class="box empty">分歧雷達載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">🧭 合約帳號部位比較</span><span class="csum" id="sum-pos">載入中…</span><span class="chev">▾</span></summary>
    <div id="pos"><div class="box empty">大玩家決心載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">📋 幣別總表</span><span class="csum" id="sum-table">載入中…</span><span class="chev">▾</span></summary>
    <div id="table"><div class="box empty">幣別總表載入中…</div></div>
  </details>
  </section>
</div></div>
<footer>
  <nav class="sites" aria-label="其他工具">
    <a href="https://warhubs.com/" title="WARHUBS" rel="noopener noreferrer">戰情觀測站</a>
    <a href="https://stocktools.cc/" title="Stocktools" rel="noopener noreferrer">美股雙重分析</a>
    <a href="https://toolist.cc/" title="Toolist" rel="noopener noreferrer">分頁工作區</a>
  </nav>
  <nav class="sites related" aria-label="相關工具">
    <span>相關工具</span>
    <a href="https://www.stocktools.cc/tw/us-fee-calculator" title="Stocktools 美股手續費" target="_blank" rel="noopener noreferrer">美股手續費</a>
    <a href="https://www.stocktools.cc/tw/us-etf" title="Stocktools 美股 ETF" target="_blank" rel="noopener noreferrer">美股 ETF</a>
    <a href="https://www.stocktools.cc/tw/us-deposit" title="Stocktools 美股入金" target="_blank" rel="noopener noreferrer">美股入金</a>
    <a href="https://www.stocktools.cc/tw/us-open-account" title="Stocktools 美股開戶" target="_blank" rel="noopener noreferrer">美股開戶</a>
    <a href="https://www.stocktools.cc/tw/us-dividend" title="Stocktools 美股配息" target="_blank" rel="noopener noreferrer">美股配息</a>
    <a href="https://www.stocktools.cc/tw/us-first-buy" title="Stocktools 第一次買美股" target="_blank" rel="noopener noreferrer">第一次買美股</a>
    <a href="https://www.stocktools.cc/tw/us-premarket" title="Stocktools 美股盤前盤後" target="_blank" rel="noopener noreferrer">美股盤前盤後</a>
    <a href="https://www.stocktools.cc/tw/us-order-types" title="Stocktools 市價／限價" target="_blank" rel="noopener noreferrer">市價／限價</a>
    <a href="https://www.stocktools.cc/tw/us-adr" title="Stocktools 美股 ADR" target="_blank" rel="noopener noreferrer">美股 ADR</a>
    <a href="https://www.stocktools.cc/tw/us-fx" title="Stocktools 美股匯損" target="_blank" rel="noopener noreferrer">美股匯損</a>
  </nav>
  <a class="simples" href="https://simples.com.tw/" rel="noopener noreferrer">SIMPLES 工具網</a>
</footer>
<script>

const API_INFLIGHT = new Map(), API_CACHE = new Map();
const API_TTLS = {'/account_activity':60000,'/stablecoins':300000, '/onchain_whale':300000, '/lth_history':300000,
  '/defi':300000, '/macro':60000, '/radar_history':60000,
  '/whale_history?symbol=BTC&cohort=smart&limit=2500':1200000,
  '/whale_history?symbol=BTC&cohort=whale&limit=2500':1200000};
function apiJSON(url, timeoutMs=12000){
  const cached=API_CACHE.get(url);
  if(cached && cached.expires>Date.now()) return Promise.resolve(cached.data);
  if(API_INFLIGHT.has(url)) return API_INFLIGHT.get(url);
  const controller=new AbortController();
  const timer=setTimeout(()=>controller.abort(),timeoutMs);
  const task=(async()=>{
    try{
      const response=await fetch(url,{signal:controller.signal});
      if(!response.ok) throw new Error('資料服務回應 '+response.status);
      const data=await response.json();
      if(!data || typeof data!=='object' || data.error) throw new Error('資料服務暫時不可用');
      if(API_TTLS[url]) API_CACHE.set(url,{data,expires:Date.now()+API_TTLS[url]});
      return data;
    }finally{ clearTimeout(timer); API_INFLIGHT.delete(url); }
  })();
  API_INFLIGHT.set(url,task);
  return task;
}
function orderedPoints(points,valueKey){
  return points.filter(p=>Number.isFinite(p.t)&&Number.isFinite(p[valueKey]))
    .sort((a,b)=>a.t-b.t).filter((p,i,a)=>i===a.length-1||p.t!==a[i+1].t);
}
function onchainWindow(all,days){
  if(!all.length) return [];
  const cutoff=all[all.length-1].t-days*86400;
  return all.filter(p=>p.t>=cutoff);
}

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
function setSum(id, html){ const el=document.getElementById(id); if(el) el.innerHTML=html; }
const sgn=v=>v>0?'#3fb950':v<0?'#f85149':'#8b949e';
// 進場機會 hero：把分歧雷達的結論＋alpha候選做成一眼看懂的對比視覺
function renderHero(m, coins, conv){
  const el=document.getElementById('opp'); if(!el) return;
  const vcol='#d29922';
  const bar=(v,col)=>{const w=Math.min(50,Math.abs(v||0)*50);const left=(v||0)>=0;
    return `<div class="vsbar"><span class="mid"></span><i style="${left?'left:50%':'right:50%'};width:${w}%;background:${col}"></i></div>`;};
  const opps=(coins||[]).slice(0,6).map(c=>{
    const bcol='#d29922';
    return `<div class="opp">
      <div class="ot"><span class="osym">${c.symbol}</span><span class="chip" style="background:${bcol}22;color:${bcol}">${c.type}·${c.bias}</span></div>
      <div class="vs"><span class="lab">費率</span>${bar(c.crowd,sgn(c.crowd))}<b style="width:44px;text-align:right;color:${sgn(c.crowd)}">${(c.crowd*100).toFixed(0)}%</b></div>
      <div class="vs"><span class="lab">樣本</span>${bar(c.smart,sgn(c.smart))}<b style="width:44px;text-align:right;color:${sgn(c.smart)}">${(c.smart*100).toFixed(0)}%</b></div>
      <div class="meta" style="margin-top:6px">分歧強度 ${c.score}${c.whale!=null?`｜鯨魚 ${(c.whale*100).toFixed(0)}%`:''}</div>
    </div>`;}).join('');
  el.innerHTML=`<h2>🎯 情緒與合約部位分歧 <span class="meta">情緒／費率與追蹤合約樣本分開觀察</span></h2>
    <div class="verdict" style="color:${vcol}">${m.verdict||'—'}</div>
    ${conv?`<div class="conv" style="color:${conv.c}">⏱ ${conv.t}</div>`:''}
    <div class="meta">費率百分比為縮放指標，不是交易人數比例；合約指標為各幣淨多空比等權平均。分歧不確認頂底或現貨買賣。</div>
    <div class="heroline">
      <span class="htag">😱 恐懼貪婪 <b>${m.fear_greed??'—'}</b> ${m.fg_label||''}</span>
      <span class="htag">🧠 合約樣本各幣平均 <b style="color:${sgn(m.smart_avg)}">${m.smart_avg!=null?(m.smart_avg*100).toFixed(0)+'%':'—'}</b></span>
      <span class="htag">背離 <b>${m.n_div??'—'}</b> 幣（正費率／樣本空 ${m.n_top??0}；負費率／樣本多 ${m.n_bottom??0}）</span>
    </div>
    <div style="font-weight:700;font-size:13px;color:var(--mut);margin:14px 0 2px">分歧較大的幣（依指標差距排序）</div>
    <div class="opps">${opps||'<div class="meta">目前沒有符合門檻的分歧；缺資料的幣不列入。</div>'}</div>`;
}
async function loadMacro(){
  try{
    const m=await apiJSON('/macro');
    const g=m.global;
    if(!g){document.getElementById('macro').innerHTML='<div class="box empty">宏觀資料暫無（外部 API 失敗）</div>';return {};}
    const oc=g.oi_cap;
    const mc=oc==null?null:{
      t:`槓桿水位 OI/Cap <b>${(oc*100).toFixed(2)}%</b> → ${oc>0.03?'<b>偏高</b>，市場槓桿擁擠，留意過熱／插針洗盤':oc<0.015?'<b>偏低</b>，槓桿不高、尚有加倉空間，較不易連環爆倉':'中性，槓桿環境正常'}`,
      c:oc>0.03?'#f85149':oc<0.015?'#3fb950':'#8b949e'};
    document.getElementById('macro').innerHTML=`<div class="box">
      <h2>🌐 全市場宏觀 <small>整體槓桿與換手環境（來源 CoinGecko 聚合）</small></h2>
      ${mc?`<div class="vline" style="border-left-color:${mc.c}">📍 現在：${mc.t}</div>`:''}
      <div class="meta">${g.oi_coverage||''}</div>
      <div class="kpis">
        <div class="kpi"><div class="v">${bigMoney(g.market_cap)}</div><div class="k">總市值</div></div>
        <div class="kpi"><div class="v">${bigMoney(g.volume_24h)}</div><div class="k">24h 成交量</div></div>
        <div class="kpi"><div class="v">${bigMoney(g.open_interest)}</div><div class="k">已覆蓋永續合約 OI</div></div>
        <div class="kpi"><div class="v" style="color:#58a6ff">${g.oi_cap==null?'—':(g.oi_cap*100).toFixed(2)+'%'}</div><div class="k">OI/Cap（樣本範圍不同時不計算）</div></div>
        <div class="kpi"><div class="v" style="color:#58a6ff">${g.vol_cap==null?'—':(g.vol_cap*100).toFixed(2)+'%'}</div><div class="k">Vol/Cap 換手率</div></div>
        <div class="kpi"><div class="v">${(g.btc_dominance||0).toFixed(1)}%</div><div class="k">BTC 市佔</div></div>
      </div>
    </div>`;
    setSum('sum-macro', `總市值 ${bigMoney(g.market_cap)} ｜ OI/Cap ${g.oi_cap==null?'—':(g.oi_cap*100).toFixed(2)+'%'} ｜ BTC 市佔 ${(g.btc_dominance||0).toFixed(1)}%`);
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
    const b=await apiJSON('/backtest');
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
    if(delta>0) mv=` <span style="color:#3fb950">▲淨多空比上升</span>`;
    else mv=` <span style="color:#f85149">▼淨多空比下降</span>`;
  }
  return `<span style="color:${col}">${side} ${(net*100).toFixed(0)}%</span>${mv}`;
}
let MROWS=[], MSORT={col:'score',dir:-1}, MFILT='';
const MABS=new Set(['funding_ann']);   // 費率欄按絕對值排（抓最極端）
const MCOLS=[
  {k:'symbol',t:'幣別',f:r=>`<span class="symc">${r.symbol}</span>`},
  {k:'label', t:'判斷',f:r=>r.label?`<span style="color:${LBLC(r.label)}">${r.label}</span> <span class="meta">${r.score_source||''}</span>`:'—'},
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
  {k:'oi_cap',t:'OI/Cap',f:r=>r.oi_cap==null?'—':(r.oi_cap*100).toFixed(2)+'% '+(r.oi_source==='hyperliquid'?'（HL）':r.oi_source==='coingecko_aggregated'?'（跨所）':'（來源未標）')},
  {k:'vol_cap',t:'Vol/Cap',f:r=>r.vol_cap==null?'—':(r.vol_cap*100).toFixed(2)+'%'},
  {k:'funding_ann',t:'資金費率(年化)',f:fundCell},
  {k:'open_interest',t:'OI',f:r=>bigMoney(r.open_interest)},
  {k:'premium',t:'溢價',f:r=>r.premium==null?'—':(r.premium*100).toFixed(3)+'%'},
  {k:'market_cap',t:'市值',f:r=>bigMoney(r.market_cap)+(r.market_cap!=null && r.cap_match!=='asset_id'?'（代號配對）':'')},
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
    <div class="meta" style="margin:-4px 0 8px">ℹ️ <b>標記價／溢價</b>來自 Hyperliquid，目前清單排除已下架市場。OI 優先採 CoinGecko 跨交易所聚合，缺資料時採 HL；來源見 OI/Cap 標示。<b>市值／OI&#8202;Cap／Vol&#8202;Cap</b>來自 CoinGecko，僅 ${withCap}/${MROWS.length} 幣取得資料。「代號配對」尚未逐幣核實身分；同名有歧義、資料缺漏或來源價格相差超過 20% 時不採用。跨所 OI 僅涵蓋近 24 小時有成交的有效永續合約樣本，不能視為所有交易所總額。目前抓取市值前 250 名。日線背離使用已收盤日線，與綜合決策中的其他週期訊號不同。</div>
    <div class="scroll"><table class="tbl"><thead><tr>${head}</tr></thead><tbody id="mbody">${mBodyHTML()}</tbody></table></div></div>`;
  setSum('sum-table', `共 <b>${MROWS.length}</b> 幣 · 判斷·聰明錢/巨鯨多空·背離·費率·市值 · 點開可排序/篩選`);
}
function posRow(name, sub, g, color){
  if(!g||!g.total) return `<div class="posrow"><div class="posname"><b style="color:${color}">${name}</b> <span class="meta">${sub}</span></div><div class="meta">無資料</div></div>`;
  const sp=g.short_pct, lp=g.long_pct;
  const lean = sp==null?'—':sp>lp?`<b style="color:#f85149">空 ${(sp*100).toFixed(0)}%</b>`
                                  :sp===lp?'多空人數相同':`<b style="color:#3fb950">多 ${(lp*100).toFixed(0)}%</b>`;
  return `<div class="posrow">
    <div class="posname"><b style="color:${color}">${name}</b> <span class="meta">${sub}・取得 ${g.total} 個帳號</span></div>
    <div class="posstats">
      <span class="pchip"><span style="color:#3fb950">多 ${g.long}</span> · <span style="color:#f85149">空 ${g.short}</span> · <span style="color:#8b949e">${g.no_positions!=null?`無持倉 ${g.no_positions} · 有持倉淨額為零 ${g.offset_positions}${g.flat_unknown?' · 狀態未知 '+g.flat_unknown:''}`:`淨額為零 ${g.flat}（持倉狀態未細分）`}</span></span>
      <span class="pchip">傾向 ${lean}</span>
      <span class="pchip">槓桿 <b>${g.lev_median??'—'}x</b></span>
      ${g.winrate_median!=null?`<span class="pchip">獲利紀錄比例中位數 <b>${g.winrate_median}%</b>（${g.winrate_accounts??'涵蓋數未知'}${g.winrate_accounts!=null?'/'+g.total+' 帳號':''}）</span>`:''}
    </div>
  </div>`;
}
async function loadRadar(){
  try{
    const [r,hist]=await Promise.all([
      apiJSON('/radar'),
      apiJSON('/radar_history').then(x=>x.history||[]).catch(()=>[])]);
    const m=r.market||{}, coins=r.coins||[];
    const vcol='#d29922';
    const rows=coins.map(c=>{
      const bcol='#d29922';
      return `<div class="sig"><div class="sigtitle"><span class="symc">${c.symbol}</span>
        <span class="chip" style="background:${bcol}22;color:${bcol}">${c.type}·${c.bias}</span></div>
        <div class="calc">費率指標 <b style="color:${c.crowd>0?'#3fb950':'#f85149'}">${(c.crowd*100).toFixed(0)}%</b>
          ⟷ 聰明錢 <b style="color:${c.smart>0?'#3fb950':'#f85149'}">${(c.smart*100).toFixed(0)}%</b>
          ${c.whale!=null?`｜鯨魚 ${(c.whale*100).toFixed(0)}%`:''} ｜ 分歧強度 ${c.score}</div></div>`;
    }).join('') || '<div class="meta">目前沒有符合門檻的分歧；缺資料的幣不列入。</div>';
    // 時間軸：背離量 gap 逐輪變化，趨 0=收斂=反轉接近
    let tl='', conv=null;
    const cut=Date.now()/1000-24*3600;
    const validTail=hist.slice(hist.map(h=>typeof h.gap==='number' && Number.isFinite(h.gap)).lastIndexOf(false)+1);
    const h24=validTail.filter(h=>Date.parse(h.ts)/1000>=cut);
    const use=h24.length>=2?h24:validTail;          // 近 24 小時(不足則顯示已累積)
    if(use.length>=2){
      const pts=use.map(h=>({t:Date.parse(h.ts)/1000, v:h.gap}));
      const k=Math.min(5,use.length), recent=use.slice(-k), prev=use.slice(-2*k,-k);
      const am=a=>a.length?a.reduce((s,x)=>s+Math.abs(x.gap),0)/a.length:0;
      const rA=am(recent), pA=am(prev||[]);
      conv = prev.length? (rA<pA-0.03?{t:'背離幅度縮小；不能單憑收斂確認價格反轉',c:'#3fb950'}
                    : rA>pA+0.03?{t:'背離幅度擴大；情緒與合約方向差距增加',c:'#d29922'}
                    : {t:'背離幅度大致持平；無法據此判定進場時機',c:'#8b949e'}) : null;
      const lastN=use[use.length-1];
      const span=spanLabel(Date.parse(use[0].ts)/1000, Date.parse(lastN.ts)/1000);
      tl=`<div class="sec">背離時間軸 <small>${span}｜gap=群眾−聰明錢；線趨近 0 表示指標差距縮小，不代表價格必然反轉</small></div>
        <div class="meta">最新背離量 <b>${(lastN.gap>=0?'+':'')+lastN.gap}</b>｜背離幣數 <b>${lastN.n_div}</b>（正費率／樣本空 ${lastN.n_top}；負費率／樣本多 ${lastN.n_bottom}）${conv?`<br><b style="color:${conv.c}">${conv.t}</b>`:''}</div>
        ${lineChart(pts,{color:'#d29922',includeZero:true,tip:p=>'背離量 '+(p.v>=0?'+':'')+(+p.v).toFixed(2)})}`;
    } else {
      tl=`<div class="sec">背離時間軸</div><div class="meta">每 20 分鐘記一筆，最近連續有效 ${validTail.length} 筆，至少 2 筆才畫線；缺資料不當成零。</div>`;
    }
    document.getElementById('radar').innerHTML=`<div class="box" style="border-color:${vcol}">
      <h2>🎯 分歧雷達 <small>情緒／費率與追蹤合約樣本分開觀察</small></h2>
      <div style="font-size:16px;font-weight:700;color:${vcol};margin:4px 0 8px">${m.verdict||'—'}</div>
      <div class="meta">市場層級：恐懼貪婪 <b>${m.fear_greed??'—'}</b>（${m.fg_label||''}，歷史第 ${m.fg_percentile??'—'} 百分位）= 群眾<b>${m.crowd_dir||''}</b>　⟷　合約樣本各幣平均 <b>${m.smart_avg!=null?(m.smart_avg*100).toFixed(0)+'%':'—'}</b>（${m.smart_dir||''}）</div>
      ${tl}
      <div class="sec">分歧較大的幣（依指標差距排序）</div>
      ${rows}</div>`;
    renderHero(m, coins, conv);
    setSum('sum-radar', `<b style="color:${vcol}">${(m.verdict||'').slice(0,18)}</b> ｜ 恐懼貪婪 ${m.fear_greed??'—'} ⟷ 聰明錢 ${m.smart_avg!=null?(m.smart_avg*100).toFixed(0)+'%':'—'} ｜ 背離 ${m.n_div??'—'} 幣`);
  }catch(e){document.getElementById('radar').innerHTML='<div class="box empty">分歧雷達載入失敗：'+e+'</div>';}
}
// 💵 穩定幣總供應：完整歷史走勢＋近1月/近1年/全部切換（增發=資金進場、縮減=撤離）
let SC_ALL=[], SC_RANGE='1y', SC_ERR=null;
function setSCRange(rg){ SC_RANGE=rg; renderStable(); pruneLineData(); }
async function loadStablecoins(){
  try{
    const r=await apiJSON('/stablecoins');
    SC_ALL=(r.history||[]).map(x=>({t:x.t, v:x.v})); SC_ERR=r.meta?.stale?'來源更新延遲，顯示上次資料':null;
    renderStable();
  }catch(e){SC_ERR='更新失敗，稍後重試';renderStable();}
}
// 30 天滾動淨流入/流出：某日供應 − 30 天前供應（正=淨增發/流入、負=贖回/流出）
function scNetFlow(all){
  const secs=30*86400, out=[];
  for(let i=0;i<all.length;i++){
    const target=all[i].t-secs; let j=-1,a=0,b=i;
    while(a<=b){const m=(a+b)>>1; if(all[m].t<=target){j=m;a=m+1;}else b=m-1;}
    if(j>=0) out.push({t:all[i].t, v:all[i].v-all[j].v});
  }
  return out;
}
function downsample(arr, cap){ if(arr.length<=cap) return arr;
  const k=Math.ceil(arr.length/cap), out=[]; for(let i=0;i<arr.length;i+=k) out.push(arr[i]);
  if(out[out.length-1]!==arr[arr.length-1]) out.push(arr[arr.length-1]); return out; }
function renderStable(){
  const all=orderedPoints(SC_ALL||[],'v');
  const toggle=`<span class="rtoggle">
    <button class="${SC_RANGE==='1m'?'on':''}" onclick="setSCRange('1m')">近1月</button>
    <button class="${SC_RANGE==='1y'?'on':''}" onclick="setSCRange('1y')">近1年</button>
    <button class="${SC_RANGE==='all'?'on':''}" onclick="setSCRange('all')">全部</button></span>`;
  if(all.length<2){
    document.getElementById('stablecoins').innerHTML='<div class="box"><div class="row" style="justify-content:flex-end">'+toggle+'</div><div class="meta">'+(SC_ERR?('DefiLlama 暫時取不到（'+SC_ERR+'）'):'載入中…')+'</div></div>';
    setSum('sum-stable','—');return;}
  const now=Date.now()/1000;
  const cutoff = SC_RANGE==='1m'?now-30*86400 : SC_RANGE==='1y'?now-365*86400 : 0;
  let pts=all.filter(p=>p.t>=cutoff);
  // Do not silently display older dates when the selected window has no data.
  const last=all[all.length-1];
  const bil=x=>'$'+(x/1e9).toFixed(1)+'B';
  // 結論用「當前 30 天淨流入/流出」(全序列最後一筆，最能反映此刻資金進出)
  const flowAll=scNetFlow(all), curFlow=flowAll.length?flowAll[flowAll.length-1].v:0;
  let concl;
  if(curFlow>1e8) concl={t:`近30天穩定幣總市值<b>增加 +${bil(curFlow)}</b>`,c:'#2ea043'};
  else if(curFlow<-1e8) concl={t:`近30天穩定幣總市值<b>減少 -${bil(-curFlow)}</b>`,c:'#da3633'};
  else concl={t:`近30天穩定幣總市值變化接近 0（${curFlow>=0?'+':''}${bil(curFlow)}）`,c:'#8b949e'};
  // 下圖：淨流入/流出，依區間篩選＋降採樣(避免全區間上千根)
  const flow=downsample(flowAll.filter(p=>p.t>=cutoff), 400);
  document.getElementById('stablecoins').innerHTML=`<div class="box">
    <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:6px"><span class="meta">💵 穩定幣總市值與變化（DefiLlama）</span>${toggle}</div>
    <div class="meta">${SC_ERR||''} 資料截至 ${new Date(last.t*1000).toISOString().slice(0,10)}；市值變化包含幣價與匯率影響，並非實際交易流入。</div>
    <div class="vline" style="border-left-color:${concl.c}">📍 現在：${concl.t}｜最新總市值 <b>${bil(last.v)}</b></div>
    <div class="meta" style="margin-top:6px">① 總市值走勢</div>
    ${lineChart(pts,{color:'#58a6ff', tip:p=>'總供應 $'+(p.v/1e9).toFixed(1)+'B'})}
    <div class="meta" style="margin-top:10px">② 30 天市值變化（<b style="color:#3fb950">綠=增加</b>、<b style="color:#f85149">紅=減少</b>）</div>
    ${flow.length>=2?barChart(flow,{up:'#3fb950',down:'#f85149',tip:p=>(p.v>=0?'市值增加 +':'市值減少 ')+(p.v/1e9).toFixed(1)+'B'}):'<span class="meta">此區間資料不足</span>'}
  </div>`;
  setSum('sum-stable', `${concl.t.replace(/<[^>]+>/g,'')}`.slice(0,42));
}
function defiSourceStatus(sources){
  return [['tvl','TVL'],['stablecoin','穩定幣'],['chains','各鏈 TVL']].map(([key,label])=>{
    const m=sources?.[key]||{}, now=Date.now()/1000;
    const fetched=Number.isFinite(m.fetched_at)?m.fetched_at:null;
    const observed=Number.isFinite(m.observed_at)?m.observed_at:null;
    const delayed=fetched==null || now-fetched>2400 || (observed!=null && now-observed>172800);
    return label+'：'+(observed?'資料日期 '+new Date(observed*1000).toISOString().slice(0,10)+'（UTC）；':'')+
      (fetched?'取得 '+new Date(fetched*1000).toLocaleString():'取得時間未知')+
      (m.refresh_failed?' ⚠ 更新失敗，保留上次有效資料／無資料':delayed?' ⚠ 更新延遲或時間未知':'');
  }).join(' ｜ ');
}
async function loadDefi(){
  try{
    const d=await apiJSON('/defi');
    const tvl=d.tvl||{}, sc=d.stablecoin||{}, chains=d.chains||[];
    const chg=(x)=>x==null?'—':`<b style="color:${x>=0?'#3fb950':'#f85149'}">${(x*100).toFixed(1)}%</b>`;
    const chainHtml=chains.map(c=>`<span style="margin-right:14px">${String(c.name).replace(/[&<>"']/g, x=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[x]))} <b>$${(c.tvl/1e9).toFixed(1)}B</b></span>`).join('');
    const t7=tvl.chg_7d;
    const dc=t7==null?null:{
      t:`TVL 近7天美元估值變化 <b>${(t7*100).toFixed(1)}%</b>；變化包含資產價格與涵蓋範圍，不能直接當作資金淨流入或流出。`,
      c:'#8b949e'};
    document.getElementById('defi').innerHTML=`<div class="box">
      <h2>💰 鏈上資產估值（DefiLlama）<small>TVL 與穩定幣市值變化</small></h2>
      <div class="meta">${defiSourceStatus(d.sources)}</div>
      <div class="meta">7／30 天變化按 UTC 日期對照，缺少對照日顯示 —。穩定幣美元市值也包含價格與匯率影響，不能直接等同增發或買盤。</div>
      ${dc?`<div class="vline" style="border-left-color:${dc.c}">📍 現在：${dc.t}</div>`:''}
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
    setSum('sum-defi', `DeFi TVL $${tvl.value?(tvl.value/1e9).toFixed(1):'—'}B ｜ 穩定幣 $${sc.value?(sc.value/1e9).toFixed(0):'—'}B`);
  }catch(e){document.getElementById('defi').innerHTML='<div class="box empty">資金動向載入失敗：'+e+'</div>';}
}
function qualificationDetails(q){
  if(!q)return '';
  if(q.refreshing)return '<p class="meta">帳號資格背景檢查中；本輪名單保持固定。</p>';
  if(!q.completed_at)return '<p class="meta">'+(q.failed?'本次資格檢查失敗，尚無完成結果。':'本程序尚未完成資格檢查。')+'</p>';
  const labels={ok:'有可用損益統計',no_fills:'來源回傳空成交紀錄',no_scored_closes:'未找到非零平倉損益',rate_limited:'來源限流',request_failed:'讀取失敗',invalid_data:'資料格式異常'};
  const criteria={too_few_trades:'樣本筆數不足',nonpositive_pnl:'樣本獲利未大於零',short_span:'交易時間跨度不足'};
  return `<p class="meta">最近背景檢查：${new Date(q.completed_at*1000).toLocaleString()}｜${q.requested??'—'} 個帳號。${q.failed?'本次資格檢查失敗。':q.partial_failure?'部分來源讀取失敗或資料異常。':''}<br>${Object.entries(q.reasons||{}).map(([k,v])=>(labels[k]||'其他')+' '+v+' 個').join('；')}<br>${Object.entries(q.criteria||{}).map(([k,v])=>(criteria[k]||'其他')+' '+v+' 個').join('；')}。合格 ${q.qualified??'—'} 個。<br>空紀錄只代表來源最近可回傳的範圍；本統計採非零平倉損益紀錄，不代表完整交易歷史或完整帳戶報酬。讀取失敗與無可用統計者保留尚未過期資格的原時間。</p>`;
}
function qualificationSplit(p){
  if(!p.smart_verified||!p.smart_pnl_only)return '<p class="meta">資格分組部位等待下一輪完整分析；舊快照不推算分組。</p>';
  const row=(name,g)=>{
    const b=g.btc;
    return posRow(name,'本輪資格分組',g,'#8b949e')+(b?`<p class="meta">BTC 合約 ${b.accounts} 個帳號｜多單 $${(b.long_usd/1e6).toFixed(2)+'M'}｜空單 $${(b.short_usd/1e6).toFixed(2)+'M'}｜名目淨額 $${((b.long_usd-b.short_usd)/1e6).toFixed(2)+'M'}</p>`:'');
  };
  return row('通過交易資格',p.smart_verified)+row('僅歷史獲利補入',p.smart_pnl_only)+'<p class="meta">以上多空人數按帳號全部合約的淨方向；BTC 金額只計 BTC 合約。獲利紀錄比例採有統計帳號的中位數，非整組交易勝率或未來獲利機率。分組目前部位不等於加倉／減倉；尚無各組歷史對照。</p>';
}
async function loadPositioning(){
  try{
    const p=await apiJSON('/positioning');
    const pdir=g=>(!g||!g.total||g.short_pct==null)?null:(g.short_pct>g.long_pct?'空':g.long_pct>g.short_pct?'多':'中性');
    const sd=pdir(p.smart), wd=pdir(p.whale);
    let pc=null;
    if(sd&&wd){
      if((sd==='多'&&wd==='空')||(sd==='空'&&wd==='多'))
        pc={t:`⚠️ <b>分歧訊號</b>：聰明錢偏<b>${sd}</b>、巨鯨偏<b>${wd}</b>（方向相反）→ 兩種合約樣本的部位方向不同`,c:'#d29922'};
      else if(sd===wd)
        pc={t:`聰明錢與巨鯨<b>同向偏${sd}</b> → 兩種合約樣本方向相同，未涵蓋現貨或長期持有者`,c:sd==='多'?'#3fb950':sd==='空'?'#f85149':'#8b949e'};
      else pc={t:`聰明錢偏${sd}、巨鯨${wd} → 一方中性，方向未明、續觀望`,c:'#8b949e'};
    }
    document.getElementById('pos').innerHTML=`<div class="box">
      <h2>🧭 合約帳號部位比較 <small>多空人數＋帳號槓桿</small></h2>
      ${pc?`<div class="vline" style="border-left-color:${pc.c}">📍 現在：${pc.t}</div>`:''}
      ${posRow('🧠 聰明錢', '交易資格篩選＋歷史獲利補入', p.smart, '#58a6ff')}
      ${p.qualification?`<p class="meta">本輪名單 ${p.qualification.selected} 個：已驗證 ${p.qualification.qualified} 個、僅歷史獲利補入 ${p.qualification.pnl_only} 個。實際取得持倉 ${p.qualification.positions_received} 個（已驗證 ${p.qualification.positions_qualified}、補入 ${p.qualification.positions_pnl_only}）。<br>名單選定：${new Date(p.qualification.selected_at*1000).toLocaleString()}${p.qualification.oldest_verified_at?'｜最早資格檢查：'+new Date(p.qualification.oldest_verified_at*1000).toLocaleString():''}。新資格結果下一輪套用。</p>`:''}
      ${qualificationSplit(p)}
      ${qualificationDetails(p.qualification_check)}
      ${posRow('🐋 合約大額帳號', '候選樣本淨值前N', p.whale, '#d29922')}
      <div class="meta">註：兩群依不同規則篩選、可能重疊；聰明錢含近期交易資格篩選與歷史獲利補入，大額帳號依候選帳號淨值排序${p.overlap!=null?`（目前重疊 <b>${p.overlap}</b> 人）`:''}；不代表全市場投資人。無持倉指本次成功回應沒有合約部位；持倉互抵仍列為有持倉。傾向比例只計淨額非零帳號，並非 BTC 現貨方向。<br>👉 聰明錢與巨鯨方向相反時＝值得注意的分歧訊號。</div>
    </div>`;
    const leanS=g=>{ if(!g||!g.total) return '無資料'; const sp=g.short_pct,lp=g.long_pct;
      return sp==null?'—':sp===lp?'多空人數相同':(sp>lp?`<b style="color:#f85149">空 ${(sp*100).toFixed(0)}%</b>`:`<b style="color:#3fb950">多 ${(lp*100).toFixed(0)}%</b>`); };
    setSum('sum-pos', `🧠 聰明錢 ${leanS(p.smart)} ｜ 🐋 巨鯨 ${leanS(p.whale)}${p.overlap!=null?` ｜ 重疊 ${p.overlap} 人`:''}`);
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
// 時間軸實際跨度標籤（誠實顯示「近 X 小時/分鐘」，資料未滿 24h 就不謊稱近 24 小時）
function spanLabel(firstT, lastT){
  const h=(Number(lastT)-Number(firstT))/3600;
  if(h>=23.5) return '近 24 小時';
  if(h>=1.5) return '近 '+Math.round(h)+' 小時';
  return '近 '+Math.max(1,Math.round(h*60))+' 分鐘';
}
let _gid=0; const LINE_DATA={};
function pruneLineData(){
  for(const id of Object.keys(LINE_DATA)) if(!document.getElementById('lc-'+id)) delete LINE_DATA[id];
}
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
      if(spanD<=160) return (d.getMonth()+1)+'/'+d.getDate();
      if(spanD<=900) return d.getFullYear()+'-'+pad2(d.getMonth()+1);
      return ''+d.getFullYear(); }
    return p.d||''; };
  const nT=Math.min(6, n);
  const idxs=[...new Set(Array.from({length:nT},(_,k)=>Math.round(k*(n-1)/(nT-1))))];
  const ticks=idxs.map(i=>{ const tx=Math.max(L+18,Math.min(W-R-18,xs(i)));
    return `<text x="${tx.toFixed(1)}" y="${H-9}" fill="#8b949e" font-size="12" text-anchor="middle">${tickLabel(i)}</text>`; }).join('');
  // 平滑曲線＋漸層面積＋末點圓點
  const P=vs.map((v,i)=>[xs(i),ys(v)]);
  const line=smoothPath(P);
  const area=line+` L${xs(n-1).toFixed(1)},${(H-Bm).toFixed(1)} L${xs(0).toFixed(1)},${(H-Bm).toFixed(1)} Z`;
  const ex=xs(n-1), ey=ys(vs[n-1]);
  const gid='g'+(_gid++);
  const yl=opts.ylabel?`<text x="13" y="${T+(H-T-Bm)/2}" fill="#6e7681" font-size="11" transform="rotate(-90 13 ${T+(H-T-Bm)/2})" text-anchor="middle">${opts.ylabel}</text>`:'';
  // 存圖資料供滑過查最近點顯示日期/數值
  LINE_DATA[gid]={L,R,W,n,pts,P,spanD,label:(p)=>(opts.tip?opts.tip(p):fa(p.v))};
  return `<div class="chart-scroll" tabindex="0" aria-label="趨勢圖，可左右捲動"><svg id="lc-${gid}" width="100%" viewBox="0 0 ${W} ${H}">
    <defs><linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.30"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    ${grid}${zline}
    <path d="${area}" fill="url(#${gid})" stroke="none"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2" stroke-linejoin="round"/>
    <circle cx="${ex.toFixed(1)}" cy="${ey.toFixed(1)}" r="3.5" fill="${col}"/>
    <circle id="lm-${gid}" r="4" fill="${col}" stroke="#0d1117" stroke-width="1.5" style="display:none" pointer-events="none"/>
    ${ticks}${yl}
    <rect x="${L}" y="${T}" width="${(W-L-R).toFixed(1)}" height="${(H-T-Bm).toFixed(1)}" fill="transparent" onpointerdown="lineTip(event,'${gid}')" onmousemove="lineTip(event,'${gid}')" onmouseout="lineOut('${gid}')"/></svg></div>`;
}
// 線圖滑過：依滑鼠 x 找最近資料點，顯示日期＋數值並標出該點
function dateLab(t,spanD){ if(t==null) return ''; const d=new Date(Number(t)*1000), p2=x=>('0'+x).slice(-2);
  return spanD<2 ? (d.getMonth()+1)+'/'+d.getDate()+' '+p2(d.getHours())+':'+p2(d.getMinutes())
       : spanD<=160 ? (d.getMonth()+1)+'/'+d.getDate()
       : d.getFullYear()+'/'+(d.getMonth()+1)+'/'+d.getDate(); }
function lineTip(e,id){ const d=LINE_DATA[id]; if(!d) return;
  const svg=document.getElementById('lc-'+id); if(!svg) return;
  const r=svg.getBoundingClientRect(); if(!r.width) return;
  const vx=(e.clientX-r.left)/r.width*d.W;
  let i=Math.round((vx-d.L)/(d.W-d.L-d.R)*(d.n-1)); i=Math.max(0,Math.min(d.n-1,i));
  const p=d.pts[i], m=document.getElementById('lm-'+id);
  if(m){ m.setAttribute('cx',d.P[i][0].toFixed(1)); m.setAttribute('cy',d.P[i][1].toFixed(1)); m.style.display='block'; }
  ctip(e, dateLab(p.t,d.spanD)+'　'+d.label(p)); }
function lineOut(id){ ctipHide(); const m=document.getElementById('lm-'+id); if(m)m.style.display='none'; }
// Each population is analyzed independently; no combined trade verdict.
let SB_VERDICT=null, OC_VERDICT=null, LTH_INFO=null, LTH_ERR=null;
function signedBTC(v){return Number.isFinite(v)?(v>0?'+':'')+Math.round(v).toLocaleString()+' BTC':'缺少對照日';}
function supplyBehavior(r, subject){
  const a=r?.changes_btc?.['7'], b=r?.changes_btc?.['30'];
  if(!Number.isFinite(a)||!Number.isFinite(b))return subject+'：7／30 天對照不足，暫不判定趨勢。';
  if(a>0&&b<0)return subject+'：近 30 天減少，但近 7 天轉為增加。';
  if(a<0&&b>0)return subject+'：近 30 天增加，但近 7 天轉為減少。';
  return subject+'：近 7 天'+(a>0?'增加':a<0?'減少':'持平')+'，近 30 天'+(b>0?'增加':b<0?'減少':'持平')+'。';
}
function smartBehavior(){
  const all=orderedPoints(SB_ALL||[],'v'), last=all.at(-1);
  if(!last)return 'BTC 合約部位資料不足。';
  const target=last.t-86400;
  const prev=all.filter(p=>p.t<=target&&target-p.t<=3600).at(-1);
  const current=(Date.now()/1000-last.t>3600?'資料延遲，以下為上次紀錄。':'')+'目前樣本名目部位'+(last.v>0?'淨多':last.v<0?'淨空':'多空相等')+'。';
  if(!prev)return current+'缺少 24 小時對照，暫不判斷部位變化。';
  if(![last.long,last.short,prev.long,prev.short].every(Number.isFinite))return current+'缺少多空分項，暫不判斷部位變化。';
  const describe=(name,n)=>name+(n>0?'增加':n<0?'減少':'持平')+' $'+(Math.abs(n)/1e6).toFixed(2)+'M';
  return current+'約 24 小時內，'+describe('多單名目金額',last.long-prev.long)+'；'+describe('空單名目金額',last.short-prev.short)+'。樣本 '+(prev.count??'—')+' → '+(last.count??'—')+' 帳號。';
}
function renderBigMoney(){
  const el=document.getElementById('bigmoney'); if(!el) return;
  const freshness=r=>r?.as_of?'截至 '+r.as_of+((r.meta?.stale||Date.now()-Date.parse(r.as_of)>3*86400000)?'｜資料延遲':''):'';
  const whale=OC_INFO?supplyBehavior(OC_INFO,'大額地址合計餘額'):'資料載入中…';
  el.innerHTML=`<section class="reading-guide"><p class="eyebrow">BTC 群體行為</p><h2>三類群體，各自看動作。</h2><p>先讀摘要，再展開圖表。三類可能重疊，不能加總成買賣結論。</p><nav aria-label="首頁分析區塊"><a href="#group-whales">巨鯨</a><a href="#group-smart">聰明錢</a><a href="#group-lth">長期持有者</a><a href="#market-support">市場背景 ↓</a></nav></section>`;
  document.getElementById('brief-whales').innerHTML=`<div class="brief-grid"><div><h3>現貨地址</h3><p class="brief-main">${htmlText(OC_ERR||whale)}</p><p class="meta">${htmlText(freshness(OC_INFO))}｜餘額分組可能含交易所與託管，減少不等於賣出。</p></div><div><h3>合約大額帳號</h3>${accountBrief('whale')}<p class="meta">合約方向與現貨地址分開看，不代表同一批持有人。</p></div></div><p class="reading-hint">怎麼搭配看：先確認變的是地址餘額還是合約部位；兩邊方向不同時，保留差異，不推測原因。</p>`;
  document.getElementById('brief-smart').innerHTML=`<h3>已驗證組 · BTC 合約</h3>${accountBrief('smart_verified')}<p class="meta">Hyperliquid 合約追蹤樣本；歷史獲利補入組另外列示，不能當成已驗證組。</p><p class="reading-hint">怎麼搭配看：先看同帳號多倉與空倉的數量變化，再展開下方群體趨勢。群體名目金額也會受價格與追蹤名單影響。</p>`;
  document.getElementById('brief-lth').innerHTML=`<p class="brief-main">${htmlText(LTH_ERR||(LTH_INFO?supplyBehavior(LTH_INFO,'LTH 供給'):'資料載入中…'))}</p><p class="meta">${htmlText(freshness(LTH_INFO))}｜按幣齡分類，供給減少不直接代表賣出。</p><p class="reading-hint">怎麼搭配看：近 7 天看近期變化，近 30 天看較長期間。增加可能是幣齡成熟，減少可能是舊幣移動；請分別查看巨鯨與聰明錢。</p>`;

}
function accountBrief(group){
  if(ACCOUNT_DATA?.persist_failed)return '<p class="brief-main">本輪保存失敗，暫不提供異動摘要。</p>';
  const r=ACCOUNT_DATA?.groups?.[group]?.previous;
  if(!r)return '<p class="brief-main">同帳號資料尚待累積或取得。</p>';
  const stamp=r.as_of?new Date(r.as_of*1000).toLocaleString():'—';
  const age=r.as_of&&Date.now()/1000-r.as_of>3600?'｜資料延遲':'';
  if(!r.baseline_at||!r.matched)return `<p class="brief-main">歷史不足或沒有共同可比帳號，暫不判斷增減。</p><p class="meta">截至 ${htmlText(stamp)}${age}</p>`;
  const change=(label,n)=>label+(Number.isFinite(n)?(n>0?'增加 ':n<0?'減少 ':'持平 ')+btcQuantity(Math.abs(n))+' BTC':'資料不足');
  return `<p class="brief-main">${change('多倉',r.long_change_btc)}；${change('空倉',r.short_change_btc)}。</p><p class="meta">相較上一筆（${htmlText(new Date(r.baseline_at*1000).toLocaleString())}），同組可比 ${r.matched} 個帳號。<br>截至 ${htmlText(stamp)}${age}；未取得 ${r.failed??'—'} 個帳號。新納入與移出不計為加減倉。</p>`;
}
function openAccountGroup(group){
  ACCOUNT_GROUP=group;renderAccountActivity();
  const panel=document.getElementById('account-inspector');panel.open=true;
  panel.scrollIntoView({behavior:'smooth',block:'start'});
}
let ACCOUNT_DATA=null, ACCOUNT_GROUP='smart_verified', ACCOUNT_WINDOW='previous', ACCOUNT_ROWS=[], ACCOUNT_HISTORY_TOKEN=0;
const ACTION_NAMES={unchanged:'持平',open_long:'新開多倉',open_short:'新開空倉',close_long:'多倉歸零',close_short:'空倉歸零',flip_long:'空轉多',flip_short:'多轉空',add_long:'增加多倉',add_short:'增加空倉',reduce_long:'減少多倉',reduce_short:'減少空倉'};
function btcQuantity(v){return Number.isFinite(v)?v.toLocaleString(undefined,{maximumFractionDigits:5}):'—';}
async function loadAccountActivity(){
  try{const next=await apiJSON('/account_activity');if(JSON.stringify(next)!==JSON.stringify(ACCOUNT_DATA)){ACCOUNT_DATA=next;renderAccountActivity();renderBigMoney();}}
  catch(e){ACCOUNT_DATA=null;renderBigMoney();document.getElementById('account-activity').innerHTML='<h2>同帳號 BTC 合約異動</h2><p>暫時無法取得，請稍後重新整理。</p>';}
}
function renderAccountActivity(){
  const r=ACCOUNT_DATA?.groups?.[ACCOUNT_GROUP]?.[ACCOUNT_WINDOW];
  ACCOUNT_HISTORY_TOKEN++;
  const changedRows=r?.rows||[], currentRows=r?.current_rows||[];
  ACCOUNT_ROWS=[...changedRows,...currentRows];
  const groups={smart_verified:'聰明錢：已驗證組',smart_pnl_only:'歷史獲利補入組',whale:'合約大額帳號'};
  const windows={previous:'上一筆快照', '24h':'約 24 小時','7d':'約 7 天'};
  const controls=`<div class="activity-controls"><label>觀察群體 <select aria-label="觀察群體" onchange="ACCOUNT_GROUP=this.value;renderAccountActivity()">${Object.entries(groups).map(([k,v])=>`<option value="${k}" ${k===ACCOUNT_GROUP?'selected':''}>${v}</option>`).join('')}</select></label><label>比較期間 <select aria-label="比較期間" onchange="ACCOUNT_WINDOW=this.value;renderAccountActivity()">${Object.entries(windows).map(([k,v])=>`<option value="${k}" ${k===ACCOUNT_WINDOW?'selected':''}>${v}</option>`).join('')}</select></label></div>`;
  const time=t=>t?new Date(t*1000).toLocaleString():'—';
  const meta=r?`<p class="meta">資料截至 ${time(r.as_of)}${Date.now()/1000-r.as_of>3600?'｜資料延遲':''}；本次取得 ${r.received}/${r.selected} 個帳號，${r.failed} 個未取得。<br>目前取得樣本：多倉 ${btcQuantity(r.current_long_btc)} BTC／空倉 ${btcQuantity(r.current_short_btc)} BTC。</p>`:'';
  let body='<p>開始累積逐帳號持倉。此期間尚無可比較快照；舊群體合計不能回推個別帳號動作。</p>';
  if(ACCOUNT_DATA?.persist_failed)body='<p>本輪逐帳號資料保存失敗，暫不提供異動排行。</p>';
  else if(r?.baseline_at && !r.matched)body='<p>兩個時間點沒有同組且成功取得的共同帳號，無法判定持倉變化。</p>';
  else if(r?.baseline_at){
    const counts=r.counts||{};
    body=`<p class="meta">對照 ${time(r.baseline_at)} → ${time(r.as_of)}（實際相隔 ${((r.as_of-r.baseline_at)/3600).toFixed(2)} 小時）。<br>同組且兩次成功取得 ${r.matched} 個；新納入 ${r.entered} 個、移出分類 ${r.exited} 個、任一端未取得 ${r.unobserved} 個。移出不代表平倉；不同期間的可比帳號集合可能不同。</p>
      <div class="activity-kpis"><div><strong>${btcQuantity(r.long_change_btc)} BTC</strong>可比帳號多倉變化</div><div><strong>${btcQuantity(r.short_change_btc)} BTC</strong>可比帳號空倉變化</div><div><strong>${r.changed}／${r.matched}</strong>持倉數量改變的帳號</div></div>
      <p class="meta">${Object.entries(counts).filter(([k,v])=>v).map(([k,v])=>ACTION_NAMES[k]+' '+v+' 人').join(' · ')||'無共同可比帳號'}</p>
      <div class="activity-table"><table><thead><tr><th>帳號（展開紀錄）</th><th>動作</th><th>原部位 BTC</th><th>目前 BTC</th><th>淨部位差 BTC</th></tr></thead><tbody>${changedRows.map((x,i)=>`<tr><td><button onclick="showAccountHistory(${i})">${htmlText(x.address.slice(0,8)+'…'+x.address.slice(-6))}</button></td><td>${ACTION_NAMES[x.action]||'未知'}</td><td>${btcQuantity(x.before_btc)}</td><td>${btcQuantity(x.after_btc)}</td><td>${btcQuantity(x.delta_btc)}</td></tr>`).join('')}</tbody></table></div>
      ${!changedRows.length?'<p>目前沒有可列出的持倉異動。</p>':''}`;
  }
  const current=`<details><summary>目前 BTC 持倉排行（最多 20 個）</summary><div class="activity-table"><table><thead><tr><th>帳號</th><th>BTC 部位</th><th>取得時間</th></tr></thead><tbody>${currentRows.map((x,i)=>`<tr><td><button onclick="showAccountHistory(${changedRows.length+i})">${htmlText(x.address.slice(0,8)+'…'+x.address.slice(-6))}</button></td><td>${btcQuantity(x.after_btc)}</td><td>${time(x.observed_at)}</td></tr>`).join('')}</tbody></table></div>${!currentRows.length?'<p>目前取得的帳號沒有可列出的 BTC 部位。</p>':''}</details>`;
  document.getElementById('account-activity').innerHTML=`<h2>同帳號 BTC 合約異動</h2>${controls}${meta}${body}${current}<p class="meta">按 BTC 數量差的絕對值排序，最多 20 筆；正部位為多倉、負部位為空倉。比較兩端快照，無法還原期間每筆交易，也不代表存提款或現貨金流。群體可能重疊，不能直接加總。</p><div id="account-detail"></div>`;
}
async function showAccountHistory(index){
  const row=ACCOUNT_ROWS[index], group=ACCOUNT_GROUP;if(!row)return;
  const token=++ACCOUNT_HISTORY_TOKEN;
  const el=document.getElementById('account-detail');el.textContent='帳號紀錄載入中…';
  try{
    const r=await apiJSON('/account_history?address='+encodeURIComponent(row.address)+'&cohort='+group);
    if(token!==ACCOUNT_HISTORY_TOKEN||group!==ACCOUNT_GROUP||document.getElementById('account-detail')!==el)return;
    el.innerHTML=`<h3>${htmlText(row.address)}</h3><p class="meta">最近最多 120 次採集；未納入名單或取得失敗保留缺值。正值為多倉，負值為空倉。</p><div class="activity-table"><table><thead><tr><th>採集時間</th><th>BTC 部位</th><th>狀態</th></tr></thead><tbody>${(r.history||[]).slice().reverse().map(x=>`<tr><td>${new Date(x.ts*1000).toLocaleString()}</td><td>${btcQuantity(x.btc)}</td><td>${x.status==='observed'?'已取得':x.status==='failed'?'取得失敗':'當時未納入此組'}</td></tr>`).join('')}</tbody></table></div>`;
  }catch(e){el.textContent='帳號紀錄暫時無法取得。';}
}
async function loadLTH(){
  try{LTH_INFO=await apiJSON('/lth_history');LTH_ERR=null;renderLTH();}
  catch(e){LTH_ERR='日資料暫時無法更新';renderLTH();}
  renderBigMoney();
}
let LTH_RANGE='30d';
function setLTHRange(range){if(!['7d','30d'].includes(range))return;LTH_RANGE=range;renderLTH();}
function renderLTH(){
  const r=LTH_INFO, el=document.getElementById('lth');
  const days=LTH_RANGE==='7d'?7:30;
  const toggle=`<div class="row" style="justify-content:flex-end"><span class="rtoggle"><button class="${LTH_RANGE==='7d'?'on':''}" aria-pressed="${LTH_RANGE==='7d'}" onclick="setLTHRange('7d')">近7天</button><button class="${LTH_RANGE==='30d'?'on':''}" aria-pressed="${LTH_RANGE==='30d'}" onclick="setLTHRange('30d')">近30天</button></span></div>`;
  if(!r){el.innerHTML='<div class="box empty">'+(LTH_ERR||'資料載入中…')+'</div>';return;}
  const all=orderedPoints((r.history||[]).map(x=>({t:Date.parse(x.date)/1000,v:x.btc})),'v');
  const bars=[];
  for(let i=1;i<all.length;i++)if(all[i].t>all.at(-1).t-days*86400&&all[i].t-all[i-1].t===86400)bars.push({t:all[i].t,v:all[i].v-all[i-1].v});
  const meta=r.meta||{};
  const fetched=typeof meta.updated_at==='number'?new Date(meta.updated_at*1000).toLocaleString():'未提供';
  const sourceAge=Number.isInteger(meta.source_age_days)&&meta.source_age_days>=0?`來源日期距 UTC 今天 ${meta.source_age_days} 天；`:'';
  const refreshState=meta.refresh_failed?'更新失敗，保留上次日資料，最多每小時重試一次。':meta.refreshing?'背景更新中，保留上次日資料。':meta.stale?'快取待更新。':'';
  el.innerHTML=`<div class="box">${toggle}<p><b>${supplyBehavior(r,'LTH 供給')}</b></p>
    <p>目前 ${signedBTC(r.balance_btc).replace(/^\+/,'')}｜近 1 天 ${signedBTC(r.changes_btc?.['1'])}｜近 7 天 ${signedBTC(r.changes_btc?.['7'])}｜近 30 天 ${signedBTC(r.changes_btc?.['30'])}</p>
    <p class="meta">截至 ${r.as_of}。${LTH_ERR||((r.meta?.stale||Date.now()-Date.parse(r.as_of)>3*86400000)?'資料延遲，保留上次資料。':'')} ${r.note}</p>
    <p class="meta">${sourceAge}取得時間：${fetched}。${refreshState}${meta.persist_failed?'快取保存失敗。':''}${meta.refresh_interval_seconds?'日資料最多重用 6 小時，UTC 換日重查；取得時間不代表來源日期更新。':''}</p>
    <p class="meta">近 ${days} 天每日供給差額；缺日不畫成單日變化。下降只能說明 LTH 分類供給減少，要判斷賣出仍需舊幣支出與流向證據。</p>
    ${barChart(bars,{tip:p=>'供給差額 '+signedBTC(p.v)})}<p class="meta">來源：<a href="https://bitcoin-data.com/v1/long-term-hodler-supply-btc" target="_blank" rel="noopener">bitcoin-data LTH 日供給</a></p></div>`;
  setSum('sum-lth','近'+days+'天 '+signedBTC(r.changes_btc?.[String(days)]));
}
// 🪙 鏈上巨鯨 BTC 現貨持倉量：每日買/賣量柱狀（綠囤幣/紅出貨）＋近30天/近7天切換
let OC_ALL=[], OC_RANGE='30d', OC_BANDS='大型持有者', OC_ERR=null, OC_INFO=null;
function setOCRange(rg){ OC_RANGE=rg; renderOnchain(); }
async function loadOnchainWhale(){
  try{
    const r=await apiJSON('/onchain_whale');
    OC_INFO=r;
    OC_ALL=(r.history||[]).map(x=>({t:Date.parse(x.date)/1000, btc:x.btc, whale:x.whale, humpback:x.humpback}));
    OC_BANDS=r.bands||'大型持有者'; OC_ERR=r.meta?.stale?'來源更新延遲，顯示上次資料':null;
    renderOnchain();renderBigMoney();
  }catch(e){OC_ERR='更新失敗，稍後重試';renderOnchain();renderBigMoney();}
}
function renderOnchain(){
  const all=orderedPoints(OC_ALL||[],'btc');
  const toggle=`<span class="rtoggle"><button class="${OC_RANGE==='7d'?'on':''}" onclick="setOCRange('7d')">近7天</button><button class="${OC_RANGE==='30d'?'on':''}" onclick="setOCRange('30d')">近30天</button></span>`;
  if(all.length<2){
    document.getElementById('onchainwhale').innerHTML='<div class="box"><div class="meta">'+(OC_ERR?('bitcoin-data 暫時取不到（'+OC_ERR+'），下輪重試。'):'資料載入中…')+'</div></div>';
    setSum('sum-onchain','—');return;
  }
  const days=OC_RANGE==='7d'?7:30;
  const signed=v=>v==null?'缺少對照日':(v>0?'+':'')+Math.round(v).toLocaleString()+' BTC';
  const rows=OC_INFO?.cohorts||[];
  const displayRows=rows.length?[...rows,{label:'兩組合計',balance_btc:all[all.length-1].btc,changes_btc:OC_INFO.changes_btc,total:true}]:[];
  const quantity=v=>Number.isFinite(v)?Math.round(v).toLocaleString():'資料不足';
  const delta=v=>`<span class="balance-change ${Number.isFinite(v)?(v>0?'increase':v<0?'decrease':''):'missing'}">${signed(v)}</span>`;
  const table=displayRows.length?`<div class="balance-desktop"><table class="balance-table"><caption>地址分組比較 <span>單位：BTC</span></caption><thead><tr><th scope="col">地址分組</th><th scope="col">目前餘額</th><th scope="col">近 1 天變化</th><th scope="col">近 7 天變化</th><th scope="col">近 30 天變化</th></tr></thead><tbody>${displayRows.map(c=>`<tr class="${c.total?'balance-total':''}"><th scope="row">${htmlText(c.label)}</th><td class="balance-value">${quantity(c.balance_btc)}</td>${[1,7,30].map(n=>`<td>${delta(c.changes_btc?.[String(n)])}</td>`).join('')}</tr>`).join('')}</tbody></table></div><div class="balance-mobile">${displayRows.map(c=>`<article class="balance-card ${c.total?'balance-total':''}"><h4>${htmlText(c.label)}</h4><p class="balance-current"><span>目前餘額</span><strong>${quantity(c.balance_btc)} <small>BTC</small></strong></p><dl>${[1,7,30].map(n=>`<div><dt>近 ${n} 天</dt><dd>${delta(c.changes_btc?.[String(n)])}</dd></div>`).join('')}</dl></article>`).join('')}</div>`:'';
  const charts=(rows.length?rows:[{id:'btc',label:OC_BANDS}]).map(c=>{
    const bars=[];let gaps=0;
    for(let i=1;i<all.length;i++){
      if(all[i].t<=all[all.length-1].t-days*86400)continue;
      if(all[i].t-all[i-1].t!==86400){gaps++;continue;}
      const v=all[i][c.id]-all[i-1][c.id];if(Number.isFinite(v))bars.push({t:all[i].t,v});
    }
    return `<section class="balance-chart"><h4>${htmlText(c.label)}</h4><p class="meta">每日餘額變化 · 單位 BTC${gaps?'｜缺日 '+gaps+' 段，不畫成單日變化':''}</p><div>${barChart(bars,{up:'#3fb950',down:'#f85149',tip:p=>(p.v>=0?'餘額增加 ':'餘額減少 ')+signed(p.v)})}</div></section>`;
  }).join('');
  document.getElementById('onchainwhale').innerHTML=`<div class="box balance-panel">
    <div class="balance-overview"><span class="balance-kicker">餘額動向</span><p>${supplyBehavior(OC_INFO,"大額地址合計餘額")}</p><span class="meta">資料截至 ${new Date(all[all.length-1].t*1000).toISOString().slice(0,10)}${OC_ERR?' · '+htmlText(OC_ERR):''}</span></div>
    ${table}
    <div class="balance-trend-heading"><div><h3>每日變化</h3><p class="meta">綠＝餘額增加，紅＝餘額減少</p></div>${toggle}</div>
    ${charts}
    <details class="balance-notes"><summary>資料來源與解讀限制</summary><p>${htmlText(OC_INFO?.note||'地址餘額變化不等於成交買賣。')} 轉帳、交易所託管與跨分組均可能影響數值。巨鯨按地址餘額分類；長期持有者按持有時間分類，請分別查看各自分析。</p><p>來源：<a href="https://bitcoin-data.com/v1/coins-addr-10K-1K-BTC" target="_blank" rel="noopener">1,000–10,000 BTC 地址</a> ／ <a href="https://bitcoin-data.com/v1/coins-addr-10K-BTC" target="_blank" rel="noopener">超過10,000 BTC 地址</a></p></details></div>`;
  setSum('sum-onchain','BTC 地址分組｜近7天合計 '+signed(OC_INFO?.changes_btc?.['7']));

}
// 柱狀圖：從零軸長出垂直柱，綠(正)/紅(負)，附 Y 格線與時間刻度
function barChart(pts, opts){
  opts=opts||{};
  if(!pts||!pts.length) return '<span class="meta">此區間資料累積中…</span>';
  const W=1000,H=200,L=52,R=16,T=14,Bm=30,n=pts.length,vs=pts.map(p=>p.v);
  let mn=Math.min(0,...vs),mx=Math.max(0,...vs);
  const step=niceStep((mx-mn)||Math.abs(mx)||1,5);
  let lo=Math.floor(mn/step)*step, hi=Math.ceil(mx/step)*step; if(lo===hi)hi=lo+step;
  const xs=i=>L+(i+0.5)/n*(W-L-R), ys=v=>T+(1-(v-lo)/(hi-lo))*(H-T-Bm);
  const bw=Math.max(1.5,(W-L-R)/n*0.66), z=ys(0);
  const fa=v=>{const a=Math.abs(v);return a>=1e9?(v/1e9).toFixed(1)+'B':a>=1e6?(v/1e6).toFixed(1)+'M':a>=1e3?(v/1e3).toFixed(0)+'K':''+Math.round(v);};
  let grid='';
  for(let g=lo; g<=hi+1e-9; g+=step){ const y=ys(g);
    grid+=`<line x1="${L}" y1="${y.toFixed(1)}" x2="${W-R}" y2="${y.toFixed(1)}" stroke="#21262d"/>`
        +`<text x="${L-6}" y="${(y+4).toFixed(1)}" fill="#6e7681" font-size="11" text-anchor="end">${fa(g)}</text>`; }
  const pad2=x=>('0'+x).slice(-2), spanD=(Number(pts[n-1].t)-Number(pts[0].t))/86400;
  const dlab=t=>{const d=new Date(Number(t)*1000); return spanD<2?(d.getMonth()+1)+'/'+d.getDate()+' '+pad2(d.getHours())+':'+pad2(d.getMinutes()):(d.getMonth()+1)+'/'+d.getDate();};
  const colW=(W-L-R)/n;
  const bars=pts.map((p,i)=>{ const y=ys(p.v), x=xs(i)-bw/2, top=Math.min(y,z), hh=Math.max(0.6,Math.abs(y-z));
    const lab=dlab(p.t)+'　'+(opts.tip?opts.tip(p):(p.v>=0?'+':'')+fa(p.v));
    const bar=`<rect x="${x.toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${hh.toFixed(1)}" rx="1" fill="${p.v>=0?(opts.up||'#3fb950'):(opts.down||'#f85149')}" pointer-events="none"/>`;
    const hit=`<rect x="${(xs(i)-colW/2).toFixed(1)}" y="${T}" width="${colW.toFixed(1)}" height="${(H-T-Bm).toFixed(1)}" fill="transparent" onpointerdown="ctip(event,'${lab}')" onmousemove="ctip(event,'${lab}')" onmouseout="ctipHide()"/>`;
    return bar+hit; }).join('');
  let ticks;
  if(n<=10){   // 柱不多→每根標日期
    ticks=pts.map((p,i)=>`<text x="${xs(i).toFixed(1)}" y="${H-8}" fill="#8b949e" font-size="11" text-anchor="middle">${dlab(p.t)}</text>`).join('');
  }else{       // 柱多→稀疏刻度，細節靠滑過顯示
    const nT=Math.min(6,n), idxs=[...new Set(Array.from({length:nT},(_,k)=>Math.round(k*(n-1)/(nT-1))))];
    ticks=idxs.map(i=>{const tx=Math.max(L+8,Math.min(W-R-8,xs(i)));return `<text x="${tx.toFixed(1)}" y="${H-8}" fill="#8b949e" font-size="12" text-anchor="middle">${dlab(pts[i].t)}</text>`;}).join('');
  }
  return `<div class="chart-scroll" tabindex="0" aria-label="每日變化圖，可左右捲動"><svg width="100%" viewBox="0 0 ${W} ${H}">${grid}
    <line x1="${L}" y1="${z.toFixed(1)}" x2="${W-R}" y2="${z.toFixed(1)}" stroke="#484f58"/>${bars}${ticks}</svg></div>`;
}
// 圖表浮動提示（滑過柱顯示日期＋數值）
function ctip(e,txt){ const t=document.getElementById('ctip'); if(!t)return;
  t.textContent=txt; t.style.display='block';
  t.style.left=Math.max(10,Math.min(window.innerWidth-t.offsetWidth-10, e.clientX+12))+'px';
  t.style.top=Math.max(8,Math.min(window.innerHeight-t.offsetHeight-8,e.clientY-t.offsetHeight-12))+'px'; }
document.addEventListener('scroll',()=>ctipHide(),true);
function ctipHide(){ const t=document.getElementById('ctip'); if(t)t.style.display='none'; }
// 依區間分桶：24h→每小時一柱、30天→每天一柱（取桶內最後一筆淨持倉）
function bucketNet(all, rangeKey){
  const now=Date.now()/1000;
  const cutoff = rangeKey==='30d' ? now-30*86400 : now-24*3600;
  const bsec   = rangeKey==='30d' ? 86400 : 3600;
  const pts=orderedPoints(all,'v').filter(p=>p.t>=cutoff && p.t<=now);
  const m=new Map();
  for(const p of pts) m.set(Math.floor(p.t/bsec), p);   // 升冪→最後一筆勝出
  return [...m.entries()].sort((a,b)=>a[0]-b[0]).map(([k,p])=>({t:k*bsec, v:p.v}));
}
// 把「持倉水位」序列轉成「每桶買賣動作」：v=本桶淨持倉相對上一桶的變化（正=在買/加碼、負=在賣/減碼）
function bucketFlow(all, rangeKey){
  const lv=bucketNet(all, rangeKey), out=[];
  const step=rangeKey==='30d'?86400:3600;
  for(let i=1;i<lv.length;i++) if(lv[i].t-lv[i-1].t===step) out.push({t:lv[i].t, v:lv[i].v-lv[i-1].v});
  return out;
}
// 從一串買賣動作 flow 判斷方向：連續同向輪數 streak、是否加速 accel
function flowDir(flow){
  const fv=flow.map(p=>p.v), recent=fv.slice(-6), lastSign=Math.sign(recent[recent.length-1]||0);
  let streak=0; for(let i=recent.length-1;i>=0;i--){ if(Math.sign(recent[i])===lastSign&&lastSign!==0) streak++; else break; }
  const seg=recent.slice(-streak).map(Math.abs);
  const accel = seg.length>=2 && seg[seg.length-1]>seg[0] && seg.every((x,i)=>i===0||x>=seg[i-1]*0.8);
  return {lastSign, streak, accel};
}
// 🧠 聰明錢 BTC 吸籌偵測：連續加碼 + 加碼量遞增 = 加速吸籌（柱狀＋24H/30天可選）
let REPLAY_DATA=null, REPLAY_FRAMES=[], REPLAY_INDEX=0, REPLAY_RANGE='24h', REPLAY_GROUP='smart_verified', REPLAY_TIMER=null, REPLAY_SPEED=1000;
function replayFrames(data,range){
  const cutoff=(data?.as_of||0)-(range==='7d'?7*86400:86400);
  return (data?.frames||[]).filter(f=>Number.isFinite(f.ts)&&f.ts>=cutoff&&f.ts<=data.as_of).slice().sort((a,b)=>a.ts-b.ts);
}
function stopReplay(){if(REPLAY_TIMER!==null)clearTimeout(REPLAY_TIMER);REPLAY_TIMER=null;const b=document.getElementById('replay-play');if(b)b.textContent='播放';}
async function loadReplay(){
  stopReplay();const b=document.getElementById('replay-load');b.disabled=true;
  try{const data=await apiJSON('/account_replay');REPLAY_DATA=data;REPLAY_FRAMES=replayFrames(data,REPLAY_RANGE);REPLAY_INDEX=0;
    document.getElementById('replay-content').hidden=!REPLAY_FRAMES.length;
    document.getElementById('replay-status').textContent=data.status==='persist_failed'?'本輪保存失敗，暫不提供回放。':!REPLAY_FRAMES.length?'尚無已完成的持倉快照，等待累積。':'範圍最多近7天、505筆。每一步是一筆實際紀錄，時間間隔不一定相同；不補值、不插入虛構快照。';
    b.textContent='更新快照';renderReplay();
  }catch(e){document.getElementById('replay-status').textContent='讀取失敗'+(REPLAY_FRAMES.length?'，保留上次載入的回放；請留意快照日期。':'，請稍後重試。');}
  finally{b.disabled=false;}
}
function setReplayRange(value){stopReplay();REPLAY_RANGE=value==='7d'?'7d':'24h';REPLAY_FRAMES=replayFrames(REPLAY_DATA,REPLAY_RANGE);REPLAY_INDEX=0;renderReplay();}
function setReplayGroup(value){stopReplay();REPLAY_GROUP=value==='smart_pnl_only'?'smart_pnl_only':'smart_verified';renderReplay();}
function seekReplay(value){stopReplay();REPLAY_INDEX=Math.max(0,Math.min(REPLAY_FRAMES.length-1,Number(value)||0));renderReplay();}
function toggleReplay(){
  if(REPLAY_TIMER!==null){stopReplay();return;}if(REPLAY_FRAMES.length<2)return;
  if(REPLAY_INDEX>=REPLAY_FRAMES.length-1)REPLAY_INDEX=0;
  document.getElementById('replay-play').textContent='暫停';renderReplay();
  const advance=()=>{if(document.hidden){stopReplay();return;}REPLAY_INDEX++;renderReplay();if(REPLAY_INDEX>=REPLAY_FRAMES.length-1){stopReplay();return;}REPLAY_TIMER=setTimeout(advance,REPLAY_SPEED);};
  REPLAY_TIMER=setTimeout(advance,REPLAY_SPEED);
}
function replayGraphic(frames,index,smartGroup){
  const f=frames[index];if(!f)return '';
  const scale=Math.max(1,...frames.flatMap(x=>['whale',smartGroup].flatMap(g=>[x.groups?.[g]?.long_btc,x.groups?.[g]?.short_btc].filter(Number.isFinite))));
  const rows=[['whale','巨鯨 · 合約大額','#67d6e8'],[smartGroup,smartGroup==='smart_verified'?'聰明錢 · 已驗證':'聰明錢 · 獲利補入','#e4bd7b']];
  return `<div class="replay-axis"><span>← 空倉 BTC</span><span>多倉 BTC →</span></div>${rows.map(([g,label,col])=>{
    const r=f.groups?.[g]||{};
    return `<div class="replay-track-row"><h4 style="color:${col}">${label}</h4><div class="replay-tracks" role="img" aria-label="${label}，空倉 ${btcQuantity(r.short_btc)} BTC，多倉 ${btcQuantity(r.long_btc)} BTC"><div class="replay-short">${Number.isFinite(r.short_btc)?`<i style="width:${r.short_btc/scale*100}%;background:${col};opacity:.6"></i>`:'<span>未取得</span>'}</div><div>${Number.isFinite(r.long_btc)?`<i style="width:${r.long_btc/scale*100}%;background:${col}"></i>`:'<span>未取得</span>'}</div></div><div class="replay-values"><span>空 ${btcQuantity(r.short_btc)} BTC</span><span>多 ${btcQuantity(r.long_btc)} BTC</span></div></div>`;
  }).join('')}<p class="meta">中心為 0 · 兩組共同比例尺，每側上限 ${btcQuantity(scale)} BTC</p>`;

}
function renderReplay(){
  const f=REPLAY_FRAMES[REPLAY_INDEX],slider=document.getElementById('replay-slider');
  slider.max=Math.max(0,REPLAY_FRAMES.length-1);slider.value=REPLAY_INDEX;slider.disabled=REPLAY_FRAMES.length<2;document.getElementById('replay-play').disabled=REPLAY_FRAMES.length<2;
  if(!f){document.getElementById('replay-chart').innerHTML='';document.getElementById('replay-details').innerHTML='';document.getElementById('replay-time').textContent='這個期間沒有可播放快照。';return;}
  const gap=f.baseline_at?f.ts-f.baseline_at:null;
  const stamp=new Date(f.ts*1000).toLocaleString();slider.setAttribute?.('aria-valuetext',stamp);
  document.getElementById('replay-time').textContent='批次記錄 '+stamp+' · '+(REPLAY_INDEX+1)+' / '+REPLAY_FRAMES.length+' 筆'+(gap?' · 距上一筆 '+Math.round(gap/60)+' 分鐘'+(gap>2400?'（採集間隔較長）':''):' · 無上一筆對照')+(Date.now()/1000-REPLAY_DATA.as_of>3600?' · 最新快照已超過1小時':'');
  document.getElementById('replay-chart').innerHTML=replayGraphic(REPLAY_FRAMES,REPLAY_INDEX,REPLAY_GROUP);
  const change=(name,v)=>name+(Number.isFinite(v)?(v>0?'增加 ':v<0?'減少 ':'持平 ')+btcQuantity(Math.abs(v))+' BTC':'無可比資料');
  document.getElementById('replay-details').innerHTML=[['whale','巨鯨'],[REPLAY_GROUP,REPLAY_GROUP==='smart_verified'?'聰明錢 · 已驗證組':'聰明錢 · 歷史獲利補入組']].map(([g,name])=>{const r=f.groups?.[g]||{};return `<article><h3>${name}</h3><p>同帳號：${change('多倉',r.long_change_btc)}；${change('空倉',r.short_change_btc)}。</p><p class="meta">相較${f.baseline_at?htmlText(new Date(f.baseline_at*1000).toLocaleString()):'無上一筆'}｜共同可比 ${r.matched??0} 個帳號<br>取得 ${r.received??0} / ${r.selected??0}，失敗 ${r.failed??0}；名單新增 ${r.entered??'—'}、移出 ${r.exited??'—'}。${r.failed?'本筆長條僅包含成功取得的帳號。':''}<br>持倉取得：${r.observed_from?htmlText(new Date(r.observed_from*1000).toLocaleString()):'未取得'}${r.observed_to&&r.observed_to!==r.observed_from?' ～ '+htmlText(new Date(r.observed_to*1000).toLocaleString()):''}</p></article>`;}).join('');
}
document.addEventListener('visibilitychange',()=>{if(document.hidden)stopReplay();});

let SB_ALL=[], SB_RANGE='24h';
function setSBRange(rg){ SB_RANGE=rg; renderSmartBTC(); }
async function loadSmartBTC(){
  try{
    const r=await apiJSON('/whale_history?symbol=BTC&cohort=smart&limit=2500');
    SB_ALL=orderedPoints((r.history||[]).map(x=>({t:Date.parse(x.ts)/1000, v:x.net_usd, long:x.long_usd, short:x.short_usd, count:x.count})),'v');
    renderSmartBTC();
  }catch(e){document.getElementById('smartbtc').innerHTML='<div class="box empty">聰明錢合約分析載入失敗：'+e+'</div>';}
}
function renderSmartBTC(){
  const all=orderedPoints(SB_ALL||[],'v');
  const toggle=`<span class="rtoggle"><button class="${SB_RANGE==='24h'?'on':''}" onclick="setSBRange('24h')">24H</button><button class="${SB_RANGE==='30d'?'on':''}" onclick="setSBRange('30d')">近30天</button></span>`;
  if(all.length<3){
    document.getElementById('smartbtc').innerHTML='<div class="box"><div class="row" style="justify-content:flex-end">'+toggle+'</div><div class="meta">每 20 分鐘記一筆，目前 '+all.length+' 筆，3 筆以上開始偵測。</div></div>';
    setSum('sum-smartbtc',`累積中（${all.length} 筆）`);
    SB_VERDICT={insufficient:true}; renderBigMoney();return;
  }
  const bars=bucketFlow(all, SB_RANGE);            // 每根柱＝那一輪的淨買/淨賣
  const {lastSign, streak, accel}=flowDir(bars);
  const v=all.map(p=>p.v), net=v[v.length-1], col=net>=0?'#3fb950':'#f85149';
  const concl={t:`聰明錢 BTC 淨持倉名目金額：${bars.length?(lastSign>0?'增加':lastSign<0?'減少':'持平'):'區間資料不足'}。包含價格與樣本變化，不能直接視為淨買賣。`,c:'#8b949e'};
  SB_VERDICT={dir: streak>=2?(lastSign>0?'buy':lastSign<0?'sell':'flat'):'flat', accel}; renderBigMoney();
  const note = SB_RANGE==='30d' && (all[all.length-1].t-all[0].t)<30*86400 ? `<div class="meta">（30天資料累積中——逐輪記錄，目前約 ${Math.max(1,Math.round((all[all.length-1].t-all[0].t)/86400))} 天）</div>` : '';
  document.getElementById('smartbtc').innerHTML=`<div class="box">
    <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:6px"><span class="meta">🧠 本次 BTC 持倉樣本 ${all[all.length-1].count??'—'} 個帳號 · 淨持倉名目金額變化</span>${toggle}</div>
    <div class="vline" style="border-left-color:${concl.c}">📍 現在：${concl.t}</div>
    <div class="meta">每根柱＝那一輪聰明錢<b style="color:#3fb950">名目金額增加(綠)</b>／<b style="color:#f85149">名目金額減少(紅)</b> BTC 合約｜此差額包含價格變化及追蹤樣本變化，非成交金額。<br><span style="opacity:.75">（目前累計站在 <b style="color:${col}">${net>=0?'淨多':'淨空'} $${(Math.abs(net)/1e6).toFixed(1)}M</b>，僅供參考立場，非當輪動作）</span></div>
    <p>${smartBehavior()}</p>${note}${barChart(bars,{tip:p=>(p.v>=0?'名目金額增加 +$':'名目金額減少 -$')+(Math.abs(p.v)/1e6).toFixed(1)+'M'})}
  </div>`;
  setSum('sum-smartbtc', `${concl.t.replace(/<[^>]+>/g,'')}`.slice(0,40));
}
// 🐋 巨鯨 BTC 合約淨持倉：柱狀（綠淨多/紅淨空）＋24H/30天切換，柱往零軸＝接近翻轉
let WH_ALL=[], WH_RANGE='24h';
function setWHRange(rg){ WH_RANGE=rg; renderWhaleChart(); }
async function loadWhaleChart(){
  try{
    const r=await apiJSON('/whale_history?symbol=BTC&cohort=whale&limit=2500');
    WH_ALL=(r.history||[]).map(x=>({t:Date.parse(x.ts)/1000, v:x.net_usd, long:x.long_usd, short:x.short_usd, count:x.count}));
    renderWhaleChart();
  }catch(e){document.getElementById('whalechart').innerHTML='<div class="box empty">鯨魚圖載入失敗：'+e+'</div>';}
}
function renderWhaleChart(){
  const all=orderedPoints(WH_ALL||[],'v');
  const toggle=`<span class="rtoggle"><button class="${WH_RANGE==='24h'?'on':''}" onclick="setWHRange('24h')">24H</button><button class="${WH_RANGE==='30d'?'on':''}" onclick="setWHRange('30d')">近30天</button></span>`;
  if(all.length<2){
    document.getElementById('whalechart').innerHTML='<div class="box"><div class="row" style="justify-content:flex-end">'+toggle+'</div><div class="meta">每 20 分鐘記一筆，目前 '+all.length+' 筆，2 筆以上開始畫（看大戶部位何時翻多/翻空＝進場時機）。</div></div>';
    setSum('sum-whale',`累積中（${all.length} 筆）`);return;}
  const last=all[all.length-1], net=last.v, bias=net>=0?'淨多':'淨空', col=net>=0?'#3fb950':'#f85149';
  const bars=bucketFlow(all, WH_RANGE);            // 每根柱＝那一輪的淨買/淨賣
  const {lastSign, streak, accel}=flowDir(bars);
  const firstNet=all[0].v, flip = firstNet<0&&net>=0?'翻多':firstNet>=0&&net<0?'翻空':'';
  const wc={t:`巨鯨 BTC 淨持倉名目金額：${bars.length?(lastSign>0?'增加':lastSign<0?'減少':'持平'):'區間資料不足'}。包含價格與樣本變化，不能直接視為淨買賣。`,c:'#8b949e'};
  const note = WH_RANGE==='30d' && (all[all.length-1].t-all[0].t)<30*86400 ? `<div class="meta">（30天資料累積中——逐輪記錄，目前約 ${Math.max(1,Math.round((all[all.length-1].t-all[0].t)/86400))} 天）</div>` : '';
  document.getElementById('whalechart').innerHTML=`<div class="box">
    <div class="row" style="justify-content:space-between;align-items:center;margin-bottom:6px"><span class="meta">🐋 本次 BTC 持倉樣本 ${last.count??'—'} 個帳號 · 淨持倉名目金額變化</span>${toggle}</div>
    <div class="vline" style="border-left-color:${wc.c}">📍 現在：${wc.t}</div>
    <div class="meta">每根柱＝那一輪巨鯨<b style="color:#3fb950">名目金額增加(綠)</b>／<b style="color:#f85149">名目金額減少(紅)</b> BTC 合約｜此差額包含價格變化及追蹤樣本變化，非成交金額。<br><span style="opacity:.75">（目前累計站在 <b style="color:${col}">${bias} $${(Math.abs(net)/1e6).toFixed(1)}M</b>：多 $${(last.long/1e6).toFixed(1)}M／空 $${(last.short/1e6).toFixed(1)}M，${last.count} 帳號，僅供參考立場）</span></div>
    ${note}${barChart(bars,{tip:p=>(p.v>=0?'名目金額增加 +$':'名目金額減少 -$')+(Math.abs(p.v)/1e6).toFixed(1)+'M'})}
  </div>`;
  setSum('sum-whale', `${wc.t.replace(/<[^>]+>/g,'')}`.slice(0,40));
}

let QUOTE_META=null, VALUATION_META=null, ANALYSIS_META=null;
let REFRESH_TASK=null, TABLE_STATE={decisions:[],hlcoins:[],scores:{}}, TABLE_ERRORS=new Set();
function renderMarketState(){
  const {decisions,hlcoins,scores}=TABLE_STATE;
  // 合併：HL+CoinGecko 已整合為底；輕量全幣評分疊上；watchlist 完整決策最後覆蓋。
  const bySym={};
  hlcoins.forEach(c=>bySym[c.symbol]={symbol:c.symbol, price:c.price,
    funding_ann:c.funding_ann, funding_flag:c.funding_flag,
    open_interest:c.open_interest_usd, oi_source:c.open_interest_source, premium:c.premium,
    market_cap:c.market_cap, cap_match:c.market_cap_match, oi_cap:c.oi_cap, vol_cap:c.vol_cap});
  Object.entries(scores).forEach(([s,v])=>{ if(hlcoins.length && !bySym[s])return; const r=bySym[s]||(bySym[s]={symbol:s});
    const {funding_ann, ...signals}=v;
    Object.assign(r, signals); if(r.funding_ann==null)r.funding_ann=funding_ann;
    r.score_source='市場掃描'; });   // label/score/confidence/divergence/sm_net/whale_net/…
  decisions.forEach(d=>{ if(hlcoins.length && !bySym[d.symbol])return; const r=bySym[d.symbol]||(bySym[d.symbol]={symbol:d.symbol});
    r.score_source='綜合決策'; r.label=d.label; r.score=d.score; r.confidence=d.confidence; if(r.price==null)r.price=d.price; });
  MROWS=Object.values(bySym);
  renderTable();

  if(TABLE_ERRORS.size){
    setSum('sum-table','部分資料更新失敗，顯示已取得的資料（可能含上一輪）；稍後重試');
  }
  renderLastUp();
}
function refresh(){
  pruneLineData();
  if(REFRESH_TASK) return REFRESH_TASK;
  REFRESH_TASK=(async()=>{
    const market=[['/hl_market','hlcoins','coins',Array.isArray],
      ['/scores','scores','scores',x=>!!x&&typeof x==='object'&&!Array.isArray(x)],
      ['/decisions','decisions','decisions',Array.isArray]].map(async([url,key,field,valid])=>{
      try{
        const data=await apiJSON(url);
        if(!valid(data[field])) throw new Error('資料格式不符');
        TABLE_STATE[key]=data[field]; TABLE_ERRORS.delete(key);
        if(key==='hlcoins'){ ANALYSIS_META=data.meta||null; QUOTE_META=data.meta?.quotes||null; VALUATION_META=data.meta?.valuations||null; }
        if(key==='decisions'){
          const times=data[field].map(d=>Date.parse(d.ts)).filter(Number.isFinite);
          LASTUP=times.length?Math.min(...times):0;
        }
      }catch(e){TABLE_ERRORS.add(key);}
      renderMarketState();
    });
    await Promise.allSettled([...market,loadRadar(),loadDefi(),loadPositioning(),
      loadAccountActivity(),loadSmartBTC(),loadWhaleChart(),loadOnchainWhale(),loadLTH(),loadStablecoins(),loadMacro()]);
  })().finally(()=>{REFRESH_TASK=null;});
  return REFRESH_TASK;
}
// 最後更新時間：顯示時刻＋相對「X 秒/分前」，每秒持續跳動，一眼看出資料是活的。
let LASTUP=0;
function renderLastUp(){
  const el=document.getElementById('ts'); if(!el) return;
  const age=ts=>{const sec=Math.max(0,Math.round((Date.now()-ts)/1000));
    return sec<60?sec+' 秒前':sec<3600?Math.floor(sec/60)+' 分前':Math.floor(sec/3600)+' 小時前';};
  const quoteTs=QUOTE_META?.fetched_at*1000;
  const stale=quoteTs && (Date.now()-quoteTs>180000 || QUOTE_META.refresh_failed);
  const quotes=quoteTs?'行情取得：'+new Date(quoteTs).toLocaleTimeString()+'（'+age(quoteTs)+'）'+(stale?' ⚠ 行情延遲':''):'行情取得時間未知';
  const decisions=LASTUP?'分析資料：'+new Date(LASTUP).toLocaleTimeString()+'（'+age(LASTUP)+'）':'分析資料準備中';
  el.textContent=(TABLE_ERRORS.size?'部分資料更新失敗｜':'')+quotes+'｜'+decisions;
  const completed=Date.parse(ANALYSIS_META?.analysis?.completed_at||'');
  const qualification=ANALYSIS_META?.qualification;
  if(qualification?.refreshing) el.textContent+='｜帳號資格背景檢查中（不阻塞持倉）';
  else if(qualification?.failed) el.textContent+='｜帳號資格更新失敗；未過期資格保留原時間';
  else if(qualification?.completed_at) el.textContent+='｜資格檢查完成'+(qualification.unavailable?'（部分帳號無可用資料）':'');
  if(ANALYSIS_META?.last_cycle_failed) el.textContent+=' ⚠ 分析更新失敗，保留上次結果';
  else if(ANALYSIS_META?.refreshing) el.textContent+='（分析更新中，顯示上次結果）';
  else if(ANALYSIS_META?.analysis?.restored) el.textContent+='（已讀回上次分析）';
  if(completed && Date.now()-completed>2400000) el.textContent+=' ⚠ 分析延遲';
  if(ANALYSIS_META?.analysis?.persist_failed) el.textContent+=' ⚠ 分析保存失敗';
  if(VALUATION_META){
    const parts=[['market_caps','市值'],['aggregate_oi','跨所 OI']].map(([key,label])=>{
      const ts=VALUATION_META[key]?.fetched_at*1000;
      return label+(ts?'取得 '+age(ts)+(Date.now()-ts>2400000?' ⚠ 延遲':''):'準備中');
    });
    el.textContent+='｜'+parts.join('／');
  }
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
  loadValidate(); loadNews(); loadSocial(); loadReddit(); loadBacktest();
}
async function askKB(){
  const q=document.getElementById('kbq').value.trim(); if(!q) return;
  const out=document.getElementById('kbout'); out.textContent='思考中…';
  try{ const r=await (await fetch('/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q})})).json();
    out.textContent=r.answer||JSON.stringify(r); }
  catch(e){ out.textContent='問答失敗：'+e; }
}
function fgColor(v){return v<25?'#f85149':v<45?'#d29922':v<55?'#8b949e':v<75?'#3fb950':'#2ea043';}
function sentimentStatus(fg){
  const observed=Number(fg.observed_at), fetched=Number(fg.fetched_at);
  const stale=!observed || Date.now()/1000-observed>172800;
  const status=fg.refresh_failed?'更新失敗，保留上次數值':stale?'資料日期不明或已延遲':'日頻資料';
  return `${status}｜資料日期 ${observed?new Date(observed*1000).toISOString().slice(0,10)+'（UTC）':'未知'}｜取得 ${fetched?new Date(fetched*1000).toLocaleString('zh-TW'):'未知'}`;
}
async function loadSocial(){
  try{
    const r=await apiJSON('/social');
    const fg=r.fear_greed||{};
    let fgHtml='<div class="box empty">恐懼貪婪指數暫無有效資料</div>';
    if(fg.value!=null){
      const col=fgColor(fg.value);
      const spark=lineChart((fg.history||[]).map(h=>({t:+h.t,v:h.v})), {color:'#58a6ff', zeroFloor:true, tip:p=>'恐懼貪婪 '+Math.round(p.v)});
      const pctNote = fg.percentile!=null
        ? `歷史第 <b style="color:${col}">${fg.percentile}</b> 百分位${fg.percentile<=10?'（歷史較少見的低值，不代表底部）':fg.percentile>=90?'（極度貪婪，留意風險）':''}`
        : '';
      const v=fg.value;
      const fc={t:`${String(fg.label||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}（${v}）：BTC 情緒指標，不代表巨鯨現貨持有變化，也不能單獨確認買點或賣點。`,c:col};
      fgHtml=`<div class="box">
        <h2>😱 恐懼貪婪指數 <small>BTC 情緒（<a href="https://alternative.me/crypto/fear-and-greed-index/" target="_blank" rel="noopener">Alternative.me</a>，${fg.days||''} 筆日頻資料）</small></h2>
        <div class="meta">${sentimentStatus(fg)}</div>
        <div class="vline" style="border-left-color:${fc.c}">📍 最近有效觀測：${fc.t}</div>
        <div class="kpis"><div class="kpi"><div class="v" style="color:${col};font-size:34px">${fg.value}</div>
          <div class="k">${String(fg.label||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}</div></div>
          <div class="kpi"><div class="v" style="color:${col}">${fg.percentile??'—'}%</div><div class="k">歷史百分位</div></div>
          <div class="chart-kpi">${spark}</div></div>
        <div class="meta">${pctNote}｜區間 ${fg.hist_min}–${fg.hist_max}。百分位只表示情緒在歷史資料中的位置，不是反轉機率。</div>
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
  document.getElementById('page-strategy').innerHTML=`<div class="wrap">
  <details class="ccard" open>
    <summary><span class="ctitle">🔬 訊號驗證</span><span class="csum">訊號出現後 BTC 實際怎麼走（前瞻報酬·勝率·vs基準）——能不能預判價格的證明</span><span class="chev">▾</span></summary>
    <div id="validate"><div class="box empty">訊號驗證載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">📰 新聞分析</span><span class="csum">6 家媒體利多/利空＋影響幣·整體情緒</span><span class="chev">▾</span></summary>
    <div id="news"><div class="box empty">新聞分析載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">👽 Reddit 散戶情緒</span><span class="csum">各幣討論熱度＋詞庫情緒（各版輪流更新）</span><span class="chev">▾</span></summary>
    <div id="reddit"><div class="box empty">Reddit 討論熱度載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">😱 恐懼貪婪 / 社群</span><span class="csum">全區間恐懼貪婪指數·各幣社群情緒</span><span class="chev">▾</span></summary>
    <div id="social"><div class="box empty">社群情緒載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">📈 策略回測</span><span class="csum">方向命中率＋損益曲線（真實 K 線對齊）</span><span class="chev">▾</span></summary>
    <div id="bt"><div class="box empty">回測載入中…</div></div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">🧠 Obsidian 知識庫</span><span class="csum">下載 vault·把訊號變成個人交易知識圖</span><span class="chev">▾</span></summary>
    <div class="box">
      <p><a class="dl" href="/vault.zip">⬇ 下載 Obsidian Vault (.zip)</a></p>
      <div class="step">1. 解壓 → Obsidian「開啟資料夾作為 Vault」</div>
      <div class="step">2. 看 Graph View：訊號 ↔ 幣 ↔ KOL 連成一張圖</div>
      <div class="step">3. 內含 Coins/(40幣)、Journal/(每日快照)、KOL/、Strategies/(寫假設掛回測)</div>
      <div class="step">4. 在 Strategies 寫你的策略假設，對照 Journal 複盤、找 edge</div>
    </div>
  </details>
  <details class="ccard">
    <summary><span class="ctitle">🔎 知識庫問答（RAG）</span><span class="csum">對累積的決策/關係用自然語言問答</span><span class="chev">▾</span></summary>
    <div class="box">
      <div class="ask"><input id="kbq" placeholder="例：聰明錢和鯨魚現在對 ETH 的態度一致嗎？" onkeydown="if(event.key==='Enter')askKB()">
        <button onclick="askKB()">問</button></div>
      <div id="kbout" class="meta"></div>
    </div>
  </details>
</div>`;
  loadValidate(); loadNews(); loadSocial(); loadReddit(); loadBacktest();
}
async function loadValidate(){
  try{
    const v=await apiJSON('/validate');
    const pw=v.price_window||{};
    let curFG=null;  // 當下恐懼貪婪值，用來判讀「現在落在哪個桶」
    try{ const rd=await apiJSON('/radar'); curFG=rd.market&&rd.market.fear_greed; }catch(e){}
    const col=x=>x==null?'#8b949e':x>0?'#3fb950':'#f85149';
    const wcol=x=>x==null?'#8b949e':x>=55?'#3fb950':x<=45?'#f85149':'#d29922';
    function tbl(study){
      const hz=(study&&study.horizons)||{};
      const keys=Object.keys(hz);
      if(!keys.length) return '<div class="meta">資料不足</div>';
      return keys.map(k=>{
        const blk=hz[k], o=blk.overall||{};
        const rows=(blk.buckets||[]).map(b=>`<tr>
          <td>${b.bucket}</td>
          <td style="text-align:right">${b.n||0}</td>
          <td style="text-align:right;color:${wcol(b.win_rate)}">${b.win_rate==null?'—':b.win_rate+'%'}</td>
          <td style="text-align:right;color:${col(b.mean)}"><b>${b.mean==null?'—':(b.mean>0?'+':'')+b.mean+'%'}</b></td>
          <td style="text-align:right;color:${col(b.edge_mean)}">${b.edge_mean==null?'—':(b.edge_mean>0?'+':'')+b.edge_mean+'%'}</td></tr>`).join('');
        return `<div style="margin-top:8px"><div class="meta">前瞻 <b>${k}</b>　基準(全樣本) n=${o.n||0}・勝率 ${o.win_rate==null?'—':o.win_rate+'%'}・平均 <span style="color:${col(o.mean)}">${o.mean==null?'—':(o.mean>0?'+':'')+o.mean+'%'}</span></div>
        <div class="strategy-table-scroll" tabindex="0" aria-label="完整策略數字，可左右捲動"><table class="vt"><thead><tr><th>區間</th><th>樣本</th><th>勝率</th><th>平均報酬</th><th>vs基準</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
      }).join('');
    }
    // 直觀「上漲機率」直條：直條=該情緒下買進後上漲機率；灰線=隨便買的平均勝率(基準)
    // 超過灰線(綠)=比平常更值得買；低於(紅)=更該避開。edge 只拿來決定好壞色與標籤。
    // 基準勝率極端(單向行情)或樣本太少 → 統計力不足，不可信
    function reliable(blk){
      const o=(blk&&blk.overall)||{}, base=o.win_rate, n=o.n;
      return base!=null && base<=72 && base>=28 && (n==null||n>=30);
    }
    function edgeBars(blk, nowVal){
      const bs=(blk&&blk.buckets)||[], o=(blk&&blk.overall)||{}, base=o.win_rate, ok=reliable(blk);
      if(!bs.some(b=>b.n>0)) return '<div class="meta" style="padding:4px 0">　└ 樣本累積中，暫無資料</div>';
      const head=base!=null?`<div class="wrhead">直條＝買進後「上漲機率」　｜　灰線＝隨便買的平均 <b>${base}%</b>（過灰線＝比平常更值得買）</div>`:'';
      return head+'<div class="ebars">'+bs.map(b=>{
        const now = nowVal!=null && b.range && nowVal>=b.range[0] && nowVal<b.range[1];
        const lab = `${b.bucket}${now?' <span class="nowtag">📍現在</span>':''}`;
        if(b.win_rate==null) return `<div class="wrow${now?' now':''}"><span class="wlab">${lab}</span><span class="meta" style="flex:1">樣本不足</span><span class="en">${b.n||0}筆</span></div>`;
        const e=b.edge||0, good=e>=3, bad=e<=-3;
        const c = ok ? (good?'#3fb950':bad?'#f85149':'#8b949e') : '#6e7681';   // 不可信→全灰，不誤導
        const tag = ok ? (good?'👍 值得買':bad?'👎 該避開':'— 跟平常差不多') : '';
        return `<div class="wrow${now?' now':''}"><span class="wlab">${lab}</span>
          <div class="wtrack"><i class="wfill" style="width:${b.win_rate}%;background:${c}"></i>${base!=null?`<span class="wbase" style="left:${base}%"></span>`:''}</div>
          <span class="wpct" style="color:${c}">${b.win_rate}%</span>
          <span class="wret" style="color:${(b.mean||0)>=0?'#3fb950':'#f85149'}">${b.mean==null?'':'平均'+(b.mean>0?'+':'')+b.mean+'%'}</span>
          <span class="wtag" style="color:${c}">${tag}</span>
          <span class="en">${b.n}筆</span></div>`;
      }).join('')+'</div>';
    }
    // 兩句白話結論：最值得買 & 最該避開（樣本夠的桶）
    function verdict(study,hk,minN){
      const blk=study&&study.horizons&&study.horizons[hk]; if(!blk) return null;
      const cands=(blk.buckets||[]).filter(b=>b.n>=(minN||20)&&b.edge!=null);
      if(!cands.length) return {t:'樣本還不足、統計力弱（累積中）',c:'#8b949e'};
      let best=cands[0],worst=cands[0];
      for(const b of cands){ if(b.edge>best.edge)best=b; if(b.edge<worst.edge)worst=b; }
      const parts=[];
      if(best.edge>=3) parts.push(`<span style="color:#3fb950">👍 「${best.bucket}」時買最有勝算（${best.win_rate}% 會漲）</span>`);
      if(worst.edge<=-3) parts.push(`<span style="color:#f85149">👎 「${worst.bucket}」時買最危險（只 ${worst.win_rate}% 會漲）</span>`);
      if(!parts.length) parts.push('各情況勝率都跟平常差不多，暫無明顯 edge');
      return {t:parts.join('　｜　'),c:'#c9d1d9'};
    }
    // 「現在 → 行動」：把當下狀態值對到歷史桶，直接講現在該做什麼
    function nowAction(blk, nowVal, stateName){
      if(!blk || nowVal==null) return '';
      const b=(blk.buckets||[]).find(x=>x.range && nowVal>=x.range[0] && nowVal<x.range[1]);
      if(!b || b.win_rate==null) return '';
      const e=b.edge||0, good=e>=3, bad=e<=-3, c=good?'#3fb950':bad?'#f85149':'#d29922';
      const act=good?'歷史上這情況買進勝算高 → 偏向<b>進場(做多)</b>'
               :bad?'歷史上這情況買進最危險 → <b>避開／別追多</b>'
               :'歷史上跟平常差不多 → 沒有明顯優勢，等更極端';
      const base=(blk.overall||{}).win_rate;
      return `<div class="nowbox" style="border-color:${c}">🎯 <b>現在</b>：${stateName} <b>${nowVal}</b> ＝「${b.bucket}」
        ｜歷史上這情況買 BTC，<b style="color:${c}">${b.win_rate}% 會漲</b>、平均 ${b.mean>0?'+':''}${b.mean}%（${good?'勝過':bad?'低於':'約等於'}平常 ${base}%）
        <br><span style="color:${c}">→ ${act}</span></div>`;
    }
    // 估「還要多久才可信」：粗估每天約 72 筆/幣，要 ~400 筆樣本且需涵蓋漲跌
    // 逐幣訊號「此刻各幣落在哪個桶」＋怎麼用（對應 F&G 的 nowAction）
    function nowDist(study, blk){
      const now=(study&&study.now)||[]; if(!now.length||!blk) return '';
      const byB={}; now.forEach(x=>{(byB[x.bucket]=byB[x.bucket]||[]).push(x.coin);});
      let neutralN=0;
      const lines=(blk.buckets||[]).map(b=>{
        const coins=byB[b.bucket]; if(!coins||!coins.length) return null;
        if(b.range && b.range[0]<0 && b.range[1]>0){ neutralN+=coins.length; return null; }  // 跨零軸＝中性，不列
        const e=b.edge||0, good=e>=3, bad=e<=-3, c=good?'#3fb950':bad?'#f85149':'#8b949e';
        const tag=good?'👍 值得買':bad?'👎 該避開':'— 偏一邊但無明顯 edge';
        return `<div style="margin:3px 0"><span style="color:${c};font-weight:700">${tag}</span> <span class="meta">${b.bucket}（歷史 ${b.win_rate}% 會漲）</span>：<b>${coins.join('　')}</b></div>`;
      }).filter(Boolean).join('');
      if(!lines) return `<div class="nowbox" style="border-color:#30363d"><span class="meta">🎯 此刻 ${now.length} 幣全數落在中性區，無明顯偏向</span></div>`;
      return `<div class="nowbox" style="border-color:#58a6ff">🎯 <b>此刻偏一邊的幣</b>（另有 ${neutralN} 幣中性未列）<br><span class="meta">怎麼用：<b style="color:#3fb950">挑落在 👍 桶的幣優先做多</b>、<b style="color:#f85149">避開 👎 桶的幣</b>（歷史%＝該桶買進後上漲機率）</span>${lines}</div>`;
    }
    function sig(study,hk,title,sub,nowVal,stateName){
      if(!study) return '';
      const blk=study&&study.horizons&&study.horizons[hk];
      const n=study.samples!=null?study.samples+' 樣本':(study.coins!=null?study.coins+' 幣':'');
      const head=`<div class="vhead">${title} <span class="vsub">${sub}${n?'｜'+n:''}</span></div>`;
      const hasData=blk&&(blk.buckets||[]).some(b=>b.n>0);
      if(!hasData) return `<div class="vsig">${head}<div class="acc">⏳ 樣本累積中，暫無資料（部署後逐輪累積）</div></div>`;
      if(!reliable(blk)){
        const base=(blk.overall||{}).win_rate;
        return `<div class="vsig">${head}
          <div class="acc">⏳ <b>累積中，尚不可用</b>　基準勝率 <b>${base}%</b> ＝最近幾乎什麼都在漲（單向行情）→ 這時算的勝率<b>不具統計意義</b>，不管 88% 還 100% 都只是反映「近期都漲」。<br>需再累積數週、涵蓋<b>上漲與下跌兩種行情</b>，基準回到 ~50% 才看得出真訊號。
          <details class="moredt"><summary>還是要看目前（未成熟）數字</summary>${edgeBars(blk,nowVal)}${tbl(study)}</details></div></div>`;
      }
      const v=verdict(study,hk);
      return `<div class="vsig">${head}
        ${nowAction(blk, nowVal, stateName)}
        ${nowDist(study, blk)}
        ${v?`<div class="vverdict" style="border-left-color:${v.c}">${v.t}</div>`:''}
        ${edgeBars(blk, nowVal)}
        <details class="moredt"><summary>看完整數字（所有前瞻期·各桶勝率/報酬/中位）</summary>${tbl(study)}</details>
      </div>`;
    }
    document.getElementById('validate').innerHTML=`<div class="box">
      <h2>🔬 訊號驗證 <small>把「某狀態出現後價格實際怎麼走」量化成勝率，看訊號能不能預判價格</small></h2>
      <div class="meta" style="margin-bottom:6px">直條＝該狀態下買進後的「上漲機率」；灰線＝隨便買的平均（基準）。<b>過灰線＝比平常更值得買</b>。只有「基準接近 50%、樣本夠」的訊號才可信。</div>
      <div class="vsec">✅ 已可用（有長歷史，立刻能用）</div>
      ${sig(v.fear_greed,'30d','😱 散戶恐懼貪婪 → BTC','日線近'+(pw.daily_bars||0)+'天',curFG,'恐懼貪婪')}
      <div class="vsec">⏳ 累積中（逐幣訊號，部署後才開始記，需數週＋含漲跌行情）</div>
      ${sig(v.divergence,'24h','⭐ 逐幣背離（大戶 vs 散戶·命題核心）','小時線')}
      ${sig(v.consensus,'24h','🔥 散戶共識過熱（擁擠交易·反指標）','小時線')}
      ${sig(v.pos_smart,'24h','🧠 聰明錢逐幣淨多空','小時線')}
      ${sig(v.pos_whale,'24h','🐋 巨鯨逐幣淨多空','小時線')}
      ${sig(v.mom_smart,'24h','⚡ 聰明錢變化率（翻倉/加碼）','小時線')}
      ${sig(v.mom_whale,'24h','⚡ 巨鯨變化率','小時線')}
    </div>`;
  }catch(e){document.getElementById('validate').innerHTML='<div class="box empty">訊號驗證載入失敗：'+e+'</div>';}
}
function htmlText(value){
  return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function newsLink(value){
  try{
    if(typeof value!=='string'||!/^https?:\/\//i.test(value)) return null;
    const u=new URL(value);
    if(!['http:','https:'].includes(u.protocol)||!u.hostname||u.username||u.password) return null;
    return htmlText(u.href);
  }catch(e){return null;}
}
function ago(ts){ if(!ts) return ''; const m=Math.floor((Date.now()/1000-ts)/60);
  return m<60?m+'分前':m<1440?Math.floor(m/60)+'時前':Math.floor(m/1440)+'天前'; }
function newsFreshness(r){
  const f=r.freshness;
  if(!f) return '新聞取得時間未知；舊快照尚未記錄来源狀態';
  const age=f.fetched_at?Date.now()/1000-f.fetched_at:null;
  const state=f.refresh_failed?'更新失敗，保留上次可用新聞':f.partial?'部分來源未取得可用新聞':'本次來源取得齊全';
  const reasons={rate_limited:'來源限流',access_denied:'來源拒絕存取',http_error:'來源回應錯誤',timeout:'連線逾時',request_failed:'連線失敗',invalid_data:'回應格式不符',empty_feed:'回應無可用標題'};
  const missing=Object.entries(f.sources||{}).filter(([k,v])=>v.status!=='received').map(([k,v])=>k+'（'+(reasons[v.reason]||'原因未記錄')+'）');
  return `${state}｜本次 ${f.received_sources}/${f.configured_sources} 家來源有資料｜取得 ${f.fetched_at?ago(f.fetched_at):'時間未知'}${age!=null&&age>3600?'（已超過 1 小時）':''}｜最新文章 ${f.newest_published_at?ago(f.newest_published_at):'發布時間未知'}${missing.length?'｜未取得：'+missing.join('、'):''}。空回應不代表該媒體沒有發文；取得時間不等於文章發布時間。`;
}
async function loadNews(){
  try{
    const [r,sc]=await Promise.all([
      apiJSON('/news'),
      apiJSON('/scores').then(x=>x.scores||{}).catch(()=>({}))]);
    const s=r.summary||{}, items=r.items||[];
    if(!items.length){document.getElementById('news').innerHTML='<div class="box empty">新聞暫無</div><div class="meta">'+htmlText(newsFreshness(r))+'</div>';return;}
    const biasCol=s.net>2?'#3fb950':s.net<-2?'#f85149':'#8b949e';
    // 最受關注幣：新聞淨情緒 vs 聰明錢淨多空（分歧＝潛在反指標）
    const chips=(s.top_coins||[]).map(c=>{
      const nb=c.net>0?'#3fb950':c.net<0?'#f85149':'#8b949e';
      const smn=sc[c.symbol]&&sc[c.symbol].sm_net;
      let div='';
      if(smn!=null){ const newsBull=c.net>0, smBull=smn>0.1, smBear=smn<-0.1;
        if(newsBull&&smBear) div=' <span style="color:#d29922">⚠新聞多·聰明錢空</span>';
        else if(!newsBull&&c.net<0&&smBull) div=' <span style="color:#d29922">⚠新聞空·聰明錢多</span>'; }
      return `<span class="newschip"><b>${htmlText(c.symbol)}</b> <span style="color:${nb}">${c.net>0?'利多':c.net<0?'利空':'中性'} ${htmlText(c.bull)}/${htmlText(c.bear)}</span><span class="meta"> ·${htmlText(c.mentions)}則</span>${div}</span>`;
    }).join('');
    const rows=items.slice(0,24).map(i=>{
      const b=i.sentiment, bc=b==='bull'?'#3fb950':b==='bear'?'#f85149':'#6e7681',
            bl=b==='bull'?'利多':b==='bear'?'利空':'中性';
      const coins=(i.coins||[]).map(s=>`<span class="newscoin">${htmlText(s)}</span>`).join('');
      const link=newsLink(i.link), title=htmlText(i.title);
      const headline=link?`<a href="${link}" target="_blank" rel="noopener noreferrer">${title}</a>`:`<span>${title}</span>`;
      return `<div class="newsrow">
        <span class="newsbadge" style="background:${bc}22;color:${bc};border-color:${bc}55">${bl}</span>
        ${headline}
        <div class="meta">${coins} <span style="opacity:.7">${htmlText(i.source)} · ${ago(i.ts)}</span></div></div>`;
    }).join('');
    document.getElementById('news').innerHTML=`<div class="box">
      <div class="meta">${htmlText(newsFreshness(r))}</div>
      <h2>📰 新聞分析 <small>${htmlText(s.sources||'')} 家媒體 · ${htmlText(r.total)} 則 · 關鍵字利多/利空＋影響幣（詞庫分類，非事件查證）</small></h2>
      <div class="kpis">
        <div class="kpi"><div class="v" style="color:${biasCol};font-size:30px">${htmlText(s.bias||'—')}</div><div class="k">整體新聞情緒</div></div>
        <div class="kpi"><div class="v" style="color:#3fb950">${htmlText(s.bull||0)}</div><div class="k">利多則數</div></div>
        <div class="kpi"><div class="v" style="color:#f85149">${htmlText(s.bear||0)}</div><div class="k">利空則數</div></div>
        <div class="kpi"><div class="v" style="color:#8b949e">${htmlText(s.neutral||0)}</div><div class="k">中性</div></div>
      </div>
      <div class="meta" style="margin:6px 0 4px">最受關注幣（新聞淨情緒，⚠＝與合約樣本方向不同，不代表頂底）：</div>
      <div class="newschips">${chips||'<span class="meta">本輪新聞未明確點名單一幣</span>'}</div>
      <div class="newslist">${rows}</div>
    </div>`;
  }catch(e){document.getElementById('news').innerHTML='<div class="box empty">新聞載入失敗：'+htmlText(e)+'</div>';}
}
function redditFreshness(r){
  const f=r.freshness;
  if(!f) return '各版取得時間未知；舊快照尚未記錄來源狀態';
  if(f.restored_aggregate) return '本次更新未取得可用貼文，顯示上次彙總；各版取得時間未能核對，不代表目前熱度。';
  const now=Date.now()/1000, limit=f.max_age_seconds||10800;
  const reasons={rate_limited:'來源限流',access_denied:'來源拒絕存取',http_error:'來源回應錯誤',timeout:'連線逾時',request_failed:'連線失敗',invalid_data:'回應格式不符',empty_feed:'回應無可用標題',unavailable:'未取得，原因未記錄'};
  const rows=Object.entries(f.sources||{}).map(([name,v])=>{
    const old=v.fetched_at && now-v.fetched_at>limit;
    const state=v.status==='stale'?'過舊，未納入':old?'已過舊，等待下一輪排除':v.status==='not_collected'?'尚無可用資料':v.status==='failed_retained'?'更新失敗，沿用舊資料':'已有資料';
    return `${name}：${state}${reasons[v.reason]?'／'+reasons[v.reason]:''}${v.fetched_at?'（取得 '+ago(v.fetched_at)+'）':''}`;
  });
  return `${f.persist_failed?'本次快照保存失敗，重啟可能無法恢復；':''}每輪更新一版；本輪 ${f.attempted_sub||'—'} ${f.refresh_failed?'未取得可用貼文':'已取得'}｜本次彙總 ${f.included_subs}/${f.configured_subs} 版。超過 3 小時的版快照於彙總時排除。${rows.join('；')}。空回應不代表該版完全沒有討論；舊快照未記錄原因時保留未知。`;
}
async function loadReddit(){
  try{
    const r=await apiJSON('/reddit');
    const coins=r.coins||{};
    if(!Object.keys(coins).length){
      document.getElementById('reddit').innerHTML=`<div class="box">
        <h2>👽 Reddit 散戶討論熱度</h2>
        <div class="meta">${htmlText(redditFreshness(r))}</div><div class="meta">目前沒有可用的幣種提及統計。</div></div>`;
      return;
    }
    const maxM=Math.max(...Object.values(coins).map(v=>v.mentions||0),1);
    const rows=Object.entries(coins).sort((a,b)=>b[1].mentions-a[1].mentions).slice(0,10)
      .map(([s,v])=>{const sen=v.sentiment,col=sen==null?'#8b949e':sen>=60?'#3fb950':sen>=40?'#d29922':'#f85149';
        const w=Math.round((v.mentions/maxM)*100);
        return `<div class="sig"><div class="sigtitle"><span>${htmlText(s)}</span>
          <span class="meta">提及 <b>${htmlText(v.mentions)}</b> ｜ 情緒 <b style="color:${col}">${htmlText(sen==null?'—':sen+'%')}</b></span></div>
          <div class="bar"><i style="width:${w}%;background:#5a3"></i></div></div>`;}).join('');
    const hot=Object.entries(coins).sort((a,b)=>b[1].mentions-a[1].mentions)[0];
    const rc=hot?{t:`本次樣本提及最多：<b>${htmlText(hot[0])}</b>（${htmlText(hot[1].mentions)} 次提及）。這是熱門貼文樣本，不能據此確認討論暴增、價格頂底或現貨買賣。`,c:'#d29922'}:null;
    const aMin=r.newest_ts?Math.max(0,Math.round((Date.now()/1000-r.newest_ts)/60)):null;
    const aTxt=aMin==null?'':(aMin<60?aMin+' 分前':Math.floor(aMin/60)+' 小時前');
    const rangeTxt=r.span_hours!=null?`📅 資料範圍：近 <b>${htmlText(r.span_hours)} 小時</b>的熱門貼文${aTxt?`（最新 ${aTxt}）`:''}——抓的是 Reddit「目前熱門(hot)」，非固定一週`:'';
    document.getElementById('reddit').innerHTML=`<div class="box">
      <h2>👽 Reddit 散戶討論熱度 <small>RSS 公開來源｜${htmlText(r.subs||1)}/${htmlText(r.subs_total||6)} 版輪轉·熱門 ${htmlText(r.total_posts)} 篇</small></h2>
      <div class="meta">${htmlText(redditFreshness(r))}</div>
      ${rangeTxt?`<div class="meta" style="margin:-2px 0 8px">${rangeTxt}</div>`:''}
      ${rc?`<div class="vline" style="border-left-color:${rc.c}">📍 現在：${rc.t}</div>`:''}
      <div class="meta" style="margin-bottom:8px">提及數＝樣本標題提及次數；情緒＝利多詞命中數佔利多與利空詞總命中數的比例，不是看多用戶比例；沒有情緒詞時保留未知。跨版同標題去重，並非全部 Reddit 討論。</div>
      ${rows}</div>`;
  }catch(e){document.getElementById('reddit').innerHTML='<div class="box empty">Reddit 載入失敗：'+htmlText(e)+'</div>';}
}
refresh(); setInterval(()=>{if(!document.hidden) refresh();},30000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden) refresh();});
setInterval(renderLastUp,1000);   // 「X 秒前」每秒持續跳動
setInterval(refreshStrategy,180000);   // 策略頁每 3 分鐘自動重抓(僅該頁可見時)
// PWA：註冊 service worker（可安裝、離線載入 App 殼）
if('serviceWorker' in navigator){window.addEventListener('load',()=>navigator.serviceWorker.register('/sw.js').catch(()=>{}));}
</script>
</body>
</html>
"""
