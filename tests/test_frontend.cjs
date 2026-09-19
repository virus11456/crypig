const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const page=fs.readFileSync('crypig/dashboard/page.py','utf8');
const code=page.split('<script>')[1].split('</script>')[0];
const noBoot=code.slice(0,code.lastIndexOf('refresh(); setInterval'));
function fixture(url){
 const name=url.replace('&limit=2500','').slice(1).replaceAll('?','_').replaceAll('&','_').replaceAll('=','-');
 return JSON.parse(fs.readFileSync('tests/fixtures/'+name+'.json','utf8'));
}
function setup(fetch){
 const elements=new Map();
 const document={hidden:false,addEventListener(){},getElementById(id){
  if(!elements.has(id)) elements.set(id,{innerHTML:'',textContent:'',style:{}});
  return elements.get(id);
 }};
 const ctx=vm.createContext({fetch,document,console,URL,AbortController,setTimeout,clearTimeout,window:{},navigator:{}});
 vm.runInContext(noBoot,ctx);
 return {ctx,elements,run:s=>vm.runInContext(s,ctx)};
}
const response=data=>({ok:true,status:200,json:async()=>data});
const tick=()=>new Promise(resolve=>setImmediate(resolve));
test('independent core requests begin immediately; table renders before slow macro/scores',async()=>{
 const calls=[], pending={};
 const h=setup(url=>{calls.push(url);return new Promise(resolve=>{pending[url]=resolve;});});
 const task=h.run('refresh()');
 assert(calls.includes('/hl_market'));assert(calls.includes('/scores'));assert(calls.includes('/decisions'));
 assert(calls.includes('/radar_history'));
 pending['/hl_market'](response(fixture('/hl_market')));await tick();
 assert.match(h.elements.get('table').innerHTML,/BTC/);
 for(const url of calls.filter(x=>x!=='/hl_market')) pending[url](response(fixture(url)));
 await task;
 assert.match(h.elements.get('smartbtc').innerHTML,/21 個帳號/);
 assert.match(h.elements.get('whalechart').innerHTML,/13 個帳號/);
 assert.doesNotMatch(h.elements.get('onchainwhale').innerHTML,/那天長期持有者淨買/);
});
test('a second refresh shares ongoing work',async()=>{
 const pending={},calls=[];const h=setup(url=>{calls.push(url);return new Promise(r=>pending[url]=r);});
 const a=h.run('refresh()'),b=h.run('refresh()');assert.equal(a,b);assert.equal(new Set(calls).size,calls.length);
 for(const url of calls) pending[url](response(fixture(url)));await a;
});
test('failed scores preserve market prices and explicitly mark partial data',async()=>{
 const h=setup(async url=>url==='/scores'?{ok:false,status:503}:response(fixture(url)));
 await h.run('refresh()');assert.match(h.elements.get('table').innerHTML,/BTC/);
 assert.match(h.elements.get('sum-table').innerHTML,/部分資料更新失敗/);
});
test('malformed market response is not accepted as an empty successful result',async()=>{
 const h=setup(async url=>response(url==='/hl_market'?{coins:null}:fixture(url)));
 await h.run('refresh()');assert.match(h.elements.get('sum-table').innerHTML,/部分資料更新失敗/);
});
test('history requests cache within TTL, market prices do not',async()=>{
 const calls=[];const h=setup(async url=>{calls.push(url);return response(fixture(url));});
 await h.run('refresh()');await h.run('refresh()');
 assert.equal(calls.filter(x=>x==='/stablecoins').length,1);
 assert.equal(calls.filter(x=>x==='/onchain_whale').length,1);
 assert.equal(calls.filter(x=>x==='/hl_market').length,2);
 h.run("API_CACHE.get('/stablecoins').expires=0");
 await h.run("apiJSON('/stablecoins')");assert.equal(calls.filter(x=>x==='/stablecoins').length,2);
});
test('request timeout aborts hanging request and clears in-flight record for retry',async()=>{
 let calls=0;const h=setup((url,{signal})=>{
  calls++;if(calls>1)return Promise.resolve(response({history:[]}));
  return new Promise((res,rej)=>signal.addEventListener('abort',()=>rej(new Error('aborted'))));
 });
 await assert.rejects(h.run("apiJSON('/stablecoins',5)"),/aborted/);
 assert.equal(h.run('API_INFLIGHT.size'),0);
 await h.run("apiJSON('/stablecoins',5)");assert.equal(calls,2);
});
test('onchain 30/7-day windows respect calendar boundaries',()=>{
 const h=setup();h.ctx.fixture=fixture('/onchain_whale').history;
 h.run('OC_ALL=fixture.map(x=>({t:Date.parse(x.date)/1000,btc:x.btc})); barChart=pts=>JSON.stringify(pts); renderOnchain()');
 let text=h.elements.get('onchainwhale').innerHTML;
 const getBars=()=>JSON.parse(h.elements.get('onchainwhale').innerHTML.match(/(\[\{"t".*\])/)[1]);
 assert.equal(getBars().length,30);assert.match(text,/2026-09-11/);
 h.run("setOCRange('7d')");assert.equal(getBars().length,7);
 assert.equal(h.run('onchainWindow([{t:0,btc:1},{t:864000,btc:2}],7).length'),1);
});
test('out of order position snapshots use latest per bucket; gaps do not become single-hour flows',()=>{
 const h=setup();
 const result=h.run(`(()=>{const t=Math.floor(Date.now()/3600000)*3600;
 return bucketFlow([{t:t-3600+10,v:20},{t:t-7200+10,v:10},{t:t-3600+20,v:25},{t:t-14400,v:1}],'24h');})()`);
 assert.equal(result.length,1);assert.equal(result[0].v,15);
});
test('non-numeric and duplicated points cannot corrupt charts',()=>{
 const h=setup();
 assert.equal(h.run("orderedPoints([{t:1,v:null},{t:2,v:3},{t:2,v:4},{t:NaN,v:5}],'v').length"),1);
 assert.equal(h.run("orderedPoints([{t:2,v:3},{t:2,v:4}],'v')[0].v"),4);
});
test('stablecoin 30-day change uses calendar time',()=>{
 const h=setup();const r=h.run('scNetFlow([{t:0,v:100},{t:86400*29,v:200},{t:86400*30,v:250}])');
 assert.equal(r.length,1);assert.equal(r[0].v,150);
});
test('30-day position views disclose an incomplete history even with five daily bars',async()=>{
 const h=setup(async url=>response(fixture(url)));await h.run('refresh()');
 h.run("setSBRange('30d'); setWHRange('30d')");
 assert.match(h.elements.get('smartbtc').innerHTML,/30天資料累積中/);
 assert.match(h.elements.get('whalechart').innerHTML,/30天資料累積中/);
});
test('obsolete line chart tooltip data is released without deleting visible charts',()=>{
 const h=setup();h.run("LINE_DATA.old={}; LINE_DATA.visible={}");
 h.ctx.document.getElementById=id=>id==='lc-visible'?{}:null;
 h.run('pruneLineData()');assert.equal(h.run('Object.keys(LINE_DATA).join()'),'visible');
});
test('slow score funding cannot overwrite latest quote funding; old quotes are disclosed',()=>{
 const h=setup();
 h.run("TABLE_STATE={decisions:[],hlcoins:[{symbol:'BTC',price:100,funding_ann:0.12}],scores:{BTC:{funding_ann:0.99,score:5}}}; QUOTE_META={fetched_at:Date.now()/1000-240}; renderMarketState()");
 assert.equal(h.run('MROWS[0].funding_ann'),0.12);
 assert.match(h.elements.get('ts').textContent,/行情延遲/);
 assert.match(h.elements.get('ts').textContent,/分析資料準備中/);
});
test('scores and old decisions cannot reintroduce an absent market into live quotes',()=>{
 const h=setup();
 h.run("TABLE_STATE={hlcoins:[{symbol:'BTC',price:100}],scores:{OLD:{score:1}},decisions:[{symbol:'OLD',price:300}]}; renderMarketState()");
 assert.equal(h.run("MROWS.map(r=>r.symbol).join(',')"),'BTC');
});
test('valuation timestamps distinguish older market caps from fresh quotes',()=>{
 const h=setup();
 h.run("VALUATION_META={market_caps:{fetched_at:Date.now()/1000-2500},aggregate_oi:{fetched_at:null}}; renderLastUp()");
 assert.match(h.elements.get('ts').textContent,/市值取得.*延遲/);
 assert.match(h.elements.get('ts').textContent,/跨所 OI準備中/);
});
test('address cohort panel separates holders and skips multi-day gaps',()=>{
 const h=setup();
 h.run(`OC_ALL=[{t:86400,btc:30,whale:10,humpback:20},{t:259200,btc:28,whale:8,humpback:20},{t:345600,btc:31,whale:9,humpback:22}];
 OC_INFO={note:'來源限制',changes_btc:{'1':3,'7':null,'30':null},cohorts:[{id:'whale',label:'1,000–10,000 BTC 地址',balance_btc:9,changes_btc:{'1':1,'7':null,'30':null}},{id:'humpback',label:'>10,000 BTC 地址',balance_btc:22,changes_btc:{'1':2,'7':null,'30':null}}]};
 barChart=pts=>JSON.stringify(pts);renderOnchain();`);
 const html=h.elements.get('onchainwhale').innerHTML;
 assert.match(html,/長期持有者按持有時間/);assert.match(html,/缺日 1 段/);
 assert.match(html,/缺少對照日/);assert.doesNotMatch(html,/"t":259200/);
 assert.match(html,/"v":1/);assert.match(html,/"v":2/);
});
test('restored analysis keeps its age and discloses refresh failures and persistence failures',()=>{
 const h=setup();
 h.run("LASTUP=Date.now()-7200000; ANALYSIS_META={analysis:{completed_at:new Date(LASTUP).toISOString(),restored:true}}; renderLastUp()");
 assert.match(h.elements.get('ts').textContent,/已讀回上次分析/);
 assert.match(h.elements.get('ts').textContent,/分析延遲/);
 h.run("ANALYSIS_META.last_cycle_failed=true; ANALYSIS_META.analysis.persist_failed=true; renderLastUp()");
 assert.match(h.elements.get('ts').textContent,/分析更新失敗，保留上次結果/);
 assert.match(h.elements.get('ts').textContent,/分析保存失敗/);
});
test('DeFi source dates disclose partial failure and remove unsupported net-flow claims',async()=>{
 const d=fixture('/defi');d.sources={tvl:{fetched_at:Date.now()/1000,observed_at:Date.now()/1000-259200},stablecoin:{fetched_at:123,refresh_failed:true}};
 const h=setup(async()=>response(d)); await h.run('loadDefi()');
 const html=h.elements.get('defi').innerHTML;
 assert.match(html,/資料日期/);assert.match(html,/更新失敗/);assert.match(html,/更新延遲/);
 assert.match(html,/包含資產價格與涵蓋範圍/);assert.doesNotMatch(html,/資金正流入|穩定幣增發中/);
});
test('sentiment shows its observation date and does not promise a bottom',async()=>{
 const h=setup(async()=>response({fear_greed:{value:10,label:'Extreme Fear',observed_at:1789171200,fetched_at:1789222367,refresh_failed:true,history:[],days:1,percentile:1}}));
 await h.run('loadSocial()');
 const html=h.elements.get('social').innerHTML;
 assert.match(html,/更新失敗，保留上次數值/);assert.match(html,/2026-09-12/);
 assert.match(html,/不代表巨鯨現貨持有變化/);assert.doesNotMatch(html,/常是.*反向買點|越低越接近大底/);
});
test('unknown latest radar gap is not rendered as a zero or convergence signal',async()=>{
 const h=setup(async url=>response(url==='/radar'?{market:{verdict:'資料不足',diverging:null},coins:[]}:{history:[{ts:'2026-09-12T00:00:00Z',gap:1},{ts:'2026-09-12T01:00:00Z',gap:null}]}));
 await h.run('loadRadar()');const html=h.elements.get('radar').innerHTML;
 assert.match(html,/最近連續有效 0 筆/);assert.doesNotMatch(html,/最新背離量|背離收斂中/);
});
test('three cohorts describe independent trends, not a consensus trade',async()=>{
 const h=setup(async url=>response(fixture(url)));await h.run('refresh()');
 h.run(`LTH_INFO={as_of:'2026-09-11',changes_btc:{7:-10,30:-20}};
 OC_INFO={as_of:'2026-09-11',changes_btc:{7:10,30:-30},cohorts:[]};renderBigMoney()`);
 const text=['brief-whales','brief-smart','brief-lth'].map(id=>h.elements.get(id).innerHTML).join('');
 assert.match(text,/LTH 供給：近 7 天減少，近 30 天減少/);
 assert.match(text,/大額地址合計餘額：近 30 天減少，但近 7 天轉為增加/);
 assert.match(text,/Hyperliquid 合約/);
 assert.doesNotMatch(text,/大戶共識/);
});
test('smart money analyzes both sides and refuses an incomplete 24h baseline',()=>{
 const h=setup();
 h.run('SB_ALL=[{t:1,v:80,long:100,short:20,count:5},{t:86401,v:60,long:120,short:60,count:6}]');
 assert.match(h.run('smartBehavior()'),/多單名目金額增加.*空單名目金額增加/);
 h.run('SB_ALL[0].t=4000');assert.match(h.run('smartBehavior()'),/缺少 24 小時對照/);
 h.run('SB_ALL[0].t=1;SB_ALL[0].long=null');assert.match(h.run('smartBehavior()'),/缺少多空分項/);
});
test('LTH failure does not block the other behavior analyses',async()=>{
 const h=setup(async url=>url==='/lth_history'?{ok:false,status:503}:response(fixture(url)));
 await h.run('refresh()');assert.match(h.elements.get('lth').innerHTML,/暫時無法更新/);
 assert.match(h.elements.get('smartbtc').innerHTML,/21 個帳號/);
 assert.match(h.elements.get('onchainwhale').innerHTML,/BTC/);
});
test('qualification coverage distinguishes fallback accounts from verified positions',async()=>{
 const h=setup(async url=>response({smart:{total:2,long_pct:1,short_pct:0},whale:{total:0},qualification:{selected:3,qualified:2,pnl_only:1,positions_received:2,positions_qualified:1,positions_pnl_only:1,selected_at:1789227100,oldest_verified_at:1789220000}}));
 await h.run('loadPositioning()');
 const text=h.elements.get('pos').innerHTML;
 assert.match(text,/已驗證 2 個、僅歷史獲利補入 1 個/);
 assert.match(text,/實際取得持倉 2 個（已驗證 1、補入 1）/);
 assert.match(text,/新資格結果下一輪套用/);
});
test('qualification details disclose source limits without declaring empty histories API failures',()=>{
 const h=setup();const text=h.run(`qualificationDetails({completed_at:1789227100,requested:3,qualified:0,reasons:{no_fills:1,no_scored_closes:1,rate_limited:1},criteria:{},partial_failure:true})`);
 assert.match(text,/空成交紀錄 1 個/);assert.match(text,/非零平倉損益 1 個/);assert.match(text,/來源限流 1 個/);
 assert.match(text,/不代表完整交易歷史/);
});

test('qualification subgroup rendering discloses coverage and missing historical comparison',()=>{
 const h=setup();
 assert.match(h.run('qualificationSplit({})'),/等待下一輪/);
 h.ctx.p={smart_verified:{total:2,long:1,short:1,flat:0,long_pct:.5,short_pct:.5,winrate_median:80,winrate_accounts:2,btc:{accounts:1,long_usd:120,short_usd:0}},smart_pnl_only:{total:1,long:0,short:1,flat:0,long_pct:0,short_pct:1,btc:{accounts:1,long_usd:0,short_usd:500}}};
 const text=h.run('qualificationSplit(p)');
 assert.match(text,/多空人數相同/);assert.match(text,/2\/2 帳號/);
 assert.match(text,/僅歷史獲利補入/);assert.match(text,/尚無各組歷史對照/);
 assert.doesNotMatch(text,/勝率 <b>/);
});

test('zero net distinguishes offset holdings and unavailable legacy detail',()=>{
 const h=setup(); h.ctx.g={total:2,long:0,short:0,flat:2,long_pct:null,short_pct:null,no_positions:1,offset_positions:1,flat_unknown:0};
 const text=h.run("posRow('sample','',g,'gray')");assert.match(text,/無持倉 1/);assert.match(text,/有持倉淨額為零 1/);
 delete h.ctx.g.no_positions;assert.match(h.run("posRow('sample','',g,'gray')"),/持倉狀態未細分/);
});
test('radar presents observed disagreement without promising tops or bottoms',async()=>{
 const h=setup(async url=>response(fixture(url)));
 await h.run('loadRadar()');
 const html=h.elements.get('opp').innerHTML;
 assert.match(html,/費率百分比為縮放指標/);
 assert.doesNotMatch(html,/反向＝alpha|現在有沒有進場機會|alpha 候選/);
 assert.match(html,/正費率／樣本空/);
});

test('news freshness distinguishes failed, partial, and legacy snapshots',()=>{
 const h=setup();
 assert.match(h.run('newsFreshness({})'),/時間未知/);
 h.ctx.f={refresh_failed:true,received_sources:0,configured_sources:6,fetched_at:1,sources:{Decrypt:{status:'unavailable'}}};
 const text=h.run('newsFreshness({freshness:f})');
 assert.match(text,/更新失敗/);assert.match(text,/超過 1 小時/);assert.match(text,/Decrypt/);
 h.ctx.f={partial:true,received_sources:5,configured_sources:6,sources:{}};
 assert.match(h.run('newsFreshness({freshness:f})'),/部分來源/);
});
test('reddit discloses legacy, restored and per-board failure states',()=>{
 const h=setup();assert.match(h.run('redditFreshness({})'),/時間未知/);
 assert.match(h.run('redditFreshness({freshness:{restored_aggregate:true}})'),/不代表目前熱度/);
 h.ctx.f={attempted_sub:'Bitcoin',refresh_failed:true,included_subs:1,configured_subs:6,sources:{Bitcoin:{status:'failed_retained',fetched_at:Date.now()/1000},CryptoMarkets:{status:'stale',fetched_at:1}}};
 const t=h.run('redditFreshness({freshness:f})');assert.match(t,/沿用舊資料/);assert.match(t,/過舊，未納入/);
});
test('reddit displays recorded cause without inventing a cause for legacy data',()=>{
 const h=setup();h.ctx.f={sources:{Bitcoin:{status:'failed_retained',reason:'rate_limited'},altcoin:{status:'not_collected'}}};
 const html=h.run('redditFreshness({freshness:f})');assert.match(html,/Bitcoin：更新失敗，沿用舊資料／來源限流/);assert.match(html,/altcoin：尚無可用資料/);assert.doesNotMatch(html,/altcoin：尚無可用資料／來源限流/);
});
test('news shows individual publisher failure reasons and legacy unknowns',()=>{
 const h=setup();h.ctx.f={partial:true,sources:{Decrypt:{status:'unavailable',reason:'rate_limited'},NewsBTC:{status:'unavailable'}}};
 const text=h.run('newsFreshness({freshness:f})');assert.match(text,/Decrypt（來源限流）/);assert.match(text,/NewsBTC（原因未記錄）/);
});

test('news renders external headlines as text and only permits ordinary web links',async()=>{
 const payload='<img src=x onerror="alert(1)">';
 const links=['javascript:alert(1)','data:text/html,boom','//evil.test','https://u:p@example.com','https://example.com/article?q=a&b="x"'];
 const data={items:links.map(link=>({link,title:payload,source:payload,coins:[payload],sentiment:'bull'})),summary:{top_coins:[{symbol:payload,net:1,bull:1,bear:0,mentions:1}]},total:5};
 const h=setup(async url=>response(url==='/news'?data:{scores:{}}));
 await h.run('loadNews()');const html=h.elements.get('news').innerHTML;
 assert.doesNotMatch(html,/<img|href="javascript:|href="data:|href="\/\//);
 assert.equal((html.match(/<a /g)||[]).length,1);
 assert.match(html,/&lt;img/);assert.match(html,/noopener noreferrer/);assert.match(html,/&amp;b=/);
});
test('news and reddit freshness and symbols cannot inject markup',async()=>{
 const payload='<svg onload=alert(1)>';
 const freshness={sources:{[payload]:{status:'unavailable'}},attempted_sub:payload,received_sources:0,configured_sources:1};
 const h=setup(async url=>response(url==='/news'?{items:[],freshness}:{coins:{[payload]:{mentions:2,sentiment:50}},freshness}));
 await h.run('loadNews()');await h.run('loadReddit()');
 for(const id of ['news','reddit']){assert.doesNotMatch(h.elements.get(id).innerHTML,/<svg/);assert.match(h.elements.get(id).innerHTML,/&lt;svg/);}
});
test('account activity clearly waits for real quantity history',async()=>{
 const h=setup(async()=>response({groups:{smart_verified:{previous:{status:'waiting',as_of:Date.now()/1000,selected:30,received:29,failed:1,current_long_btc:2,current_short_btc:3}}}}));
 await h.run('loadAccountActivity()');const html=h.elements.get('account-activity').innerHTML;
 assert.match(html,/尚無可比較快照/);assert.match(html,/29\/30/);assert.doesNotMatch(html,/同組且兩次成功取得/);
});
test('activity separates matched sample changes from roster churn and failures',async()=>{
 const data={groups:{smart_verified:{previous:{as_of:2000,baseline_at:1000,selected:4,received:3,failed:1,matched:2,entered:1,exited:1,unobserved:1,changed:1,long_change_btc:1,short_change_btc:0,counts:{add_long:1,unchanged:1},rows:[{address:'0x'+'a'.repeat(40),action:'add_long',before_btc:1,after_btc:2,delta_btc:1}]}}}};
 const h=setup(async()=>response(data));await h.run('loadAccountActivity()');const html=h.elements.get('account-activity').innerHTML;
 assert.match(html,/移出不代表平倉/);assert.match(html,/增加多倉/);assert.match(html,/任一端未取得 1/);assert.match(html,/showAccountHistory\(0\)/);
 h.run("ACCOUNT_WINDOW='24h';renderAccountActivity()");assert.match(h.elements.get('account-activity').innerHTML,/尚無可比較快照/);
});

test('unchanged account polling preserves opened details',async()=>{
 const h=setup(async()=>response({groups:{}}));await h.run('loadAccountActivity()');
 h.elements.get('account-activity').innerHTML='open account detail';await h.run('loadAccountActivity()');
 assert.equal(h.elements.get('account-activity').innerHTML,'open account detail');
});

test('LTH 7/30 day controls change bars and summary, preserve selection and skip gaps',()=>{
 const h=setup(()=>{throw Error('range change must not fetch')});
 h.run(`LTH_INFO={as_of:'2026-09-11',balance_btc:1000,changes_btc:{7:7,30:30},note:'',history:Array.from({length:31},(_,i)=>({date:new Date(Date.UTC(2026,7,12+i)).toISOString().slice(0,10),btc:100+i}))};
 barChart=(bars)=>'bar-count:'+bars.length;renderLTH()`);
 assert.match(h.elements.get('lth').innerHTML,/bar-count:30/);assert.match(h.elements.get('sum-lth').innerHTML,/近30天/);
 h.run("setLTHRange('7d')");assert.match(h.elements.get('lth').innerHTML,/bar-count:7/);assert.match(h.elements.get('lth').innerHTML,/近 7 天每日供給差額/);assert.match(h.elements.get('sum-lth').innerHTML,/近7天/);
 h.run('renderLTH()');assert.equal(h.run('LTH_RANGE'),'7d');
 h.run('LTH_INFO.history.splice(28,1);renderLTH()');assert.match(h.elements.get('lth').innerHTML,/bar-count:5/);
 h.run("setLTHRange('30d')");assert.match(h.elements.get('lth').innerHTML,/bar-count:28/);
});

test('LTH exposes acquisition time separately from source age and refresh failure',()=>{
 const h=setup();h.run(`LTH_INFO={as_of:'2026-09-11',balance_btc:100,changes_btc:{},history:[],note:'',meta:{updated_at:1789223000,source_age_days:3,refresh_failed:true,stale:true,persist_failed:true,refresh_interval_seconds:21600}};renderLTH()`);
 const html=h.elements.get('lth').innerHTML;
 assert.match(html,/來源日期距 UTC 今天 3 天/);assert.match(html,/取得時間/);
 assert.match(html,/更新失敗/);assert.match(html,/每小時重試一次/);assert.match(html,/快取保存失敗/);
 assert.match(html,/取得時間不代表來源日期更新/);
 h.run('LTH_INFO.meta={};renderLTH()');
 assert.match(h.elements.get('lth').innerHTML,/取得時間：未提供/);
 assert.doesNotMatch(h.elements.get('lth').innerHTML,/UTC 今天 0 天/);
});

test('home preserves all panels under three populations and market context',()=>{
 const html=page.split('<script>')[0];
 for(const id of ['bigmoney','account-activity','lth','smartbtc','whalechart','onchainwhale','macro','defi','stablecoins','opp','radar','pos','table']) {
  assert.equal(html.split('id="'+id+'"').length-1,1,id);
 }
 assert(html.indexOf('id="group-whales"')<html.indexOf('id="group-smart"'));
 assert(html.indexOf('id="group-smart"')<html.indexOf('id="group-lth"'));
 assert(html.indexOf('id="group-lth"')<html.indexOf('id="market-support"'));
 assert(!/<details class="ccard" open>/.test(html));
});
test('population account briefs use same-account BTC changes and keep missing data unknown',()=>{
 const h=setup();h.run(`ACCOUNT_DATA={groups:{whale:{previous:{as_of:2000,baseline_at:1000,matched:3,long_change_btc:0,short_change_btc:-2,failed:1}}}}`);
 assert.match(h.run("accountBrief('whale')"),/多倉持平 0 BTC；空倉減少 2 BTC/);
 assert.match(h.run("accountBrief('smart_verified')"),/尚待累積/);
 h.run('ACCOUNT_DATA.persist_failed=true');assert.match(h.run("accountBrief('whale')"),/保存失敗/);
});
test('population links select the requested cohort without another fetch',()=>{
 const h=setup(()=>{throw Error('unexpected request')});
 h.run("document.getElementById('account-inspector').scrollIntoView=()=>{};openAccountGroup('whale')");
 assert.equal(h.run('ACCOUNT_GROUP'),'whale');assert.equal(h.elements.get('account-inspector').open,true);
});

test('chart tooltip stays inside narrow viewports and charts support pointer taps',()=>{
 const h=setup(async()=>response({}));
 h.run("window.innerWidth=320;window.innerHeight=640");
 const tip=h.run("document.getElementById('ctip')");tip.offsetWidth=300;tip.offsetHeight=90;
 h.run("ctip({clientX:315,clientY:635},'日期與數值')");
 assert.equal(tip.style.left,'10px');assert.equal(tip.style.top,'533px');
 h.run("ctip({clientX:0,clientY:0},'日期與數值')");assert.equal(tip.style.top,'8px');
 assert.match(h.run("lineChart([{t:1,v:1},{t:2,v:2}],{})"),/onpointerdown="lineTip/);
 assert.match(h.run("barChart([{t:1,v:1},{t:2,v:2}],{})"),/onpointerdown="ctip/);
});

test('balance comparison keeps missing values and renders readable desktop and mobile views',()=>{
 const h=setup();h.run(`OC_ALL=[{t:86400,btc:10,whale:10},{t:172800,btc:10,whale:10}];OC_INFO={changes_btc:{1:0,7:null,30:-2},cohorts:[{id:'whale',label:'測試 <地址>',balance_btc:null,changes_btc:{1:0,7:null,30:-2}}]};renderOnchain()`);
 const html=h.elements.get('onchainwhale').innerHTML;
 assert.match(html,/class="balance-table"/);assert.match(html,/class="balance-mobile"/);
 assert.match(html,/測試 &lt;地址&gt;/);assert.match(html,/資料不足/);assert.match(html,/缺少對照日/);assert.match(html,/>0 BTC</);assert.match(html,/-2 BTC/);
 assert.match(html,/資料來源與解讀限制/);
});

test('replay uses recorded timestamps, fixed scale, missing values and independent groups',()=>{
 const h=setup();h.run(`REPLAY_DATA={as_of:10000,frames:[{ts:1000,groups:{whale:{long_btc:10,short_btc:5},smart_verified:{long_btc:1,short_btc:0}}},{ts:9000,baseline_at:1000,groups:{whale:{long_btc:null,short_btc:null},smart_verified:{long_btc:2,short_btc:0}}}]};REPLAY_FRAMES=replayFrames(REPLAY_DATA,'24h');renderReplay()`);
 assert.deepEqual(Array.from(h.run('REPLAY_FRAMES.map(f=>f.ts)')),[1000,9000]);
 assert.match(h.elements.get('replay-chart').innerHTML,/每側上限 10 BTC/);
 h.run('seekReplay(1)');assert.match(h.elements.get('replay-chart').innerHTML,/未取得/);assert.match(h.elements.get('replay-time').textContent,/採集間隔較長/);
 assert.match(h.elements.get('replay-chart').innerHTML,/空 0 BTC/);
 h.run("setReplayGroup('smart_pnl_only')");assert.match(h.elements.get('replay-chart').innerHTML,/獲利補入/);
 assert.equal(h.run("replayFrames({as_of:90000,frames:[{ts:1},{ts:89999},{ts:90001}]},'24h').length"),1);
});

test('header and footer expose sibling SIMPLES tool sites',()=>{
 const html=page.split('<script>')[0];
 const header=html.split('<header>')[1].split('</header>')[0];
 const footer=html.split('<footer>')[1].split('</footer>')[0];
 assert.match(header,/href="https:\/\/warhubs\.com\/"/);
 assert.match(header,/href="https:\/\/stocktools\.cc\/"/);
 assert.match(header,/title="Stocktools"/);
 assert.match(header,/href="https:\/\/toolist\.cc\/"/);
 assert.match(header,/戰情觀測站/);
 assert.match(header,/美股雙重分析/);
 assert.match(header,/分頁工作區/);
 assert.match(footer,/href="https:\/\/warhubs\.com\/"/);
 assert.match(footer,/href="https:\/\/stocktools\.cc\/"/);
 assert.match(footer,/title="Stocktools"/);
 assert.match(footer,/href="https:\/\/toolist\.cc\/"/);
 assert.match(footer,/href="https:\/\/simples\.com\.tw\/"/);
 assert.match(footer,/SIMPLES 工具網/);
 assert.doesNotMatch(header,/moneytools/i);
 assert.doesNotMatch(footer,/moneytools/i);
 assert.doesNotMatch(header,/affiliate|utm_/i);
 assert.doesNotMatch(footer,/affiliate|utm_/i);
});

test('header and footer expose compact Stocktools TW deep links',()=>{
 const html=page.split('<script>')[0];
 const header=html.split('<header>')[1].split('</header>')[0];
 const footer=html.split('<footer>')[1].split('</footer>')[0];
 const fee='https://www.stocktools.cc/tw/us-fee-calculator';
 const etf='https://www.stocktools.cc/tw/us-etf';
 const deposit='https://www.stocktools.cc/tw/us-deposit';
 const openAccount='https://www.stocktools.cc/tw/us-open-account';
 const dividend='https://www.stocktools.cc/tw/us-dividend';
 const firstBuy='https://www.stocktools.cc/tw/us-first-buy';
 const premarket='https://www.stocktools.cc/tw/us-premarket';
 const orderTypes='https://www.stocktools.cc/tw/us-order-types';
 const adr='https://www.stocktools.cc/tw/us-adr';
 const fx='https://www.stocktools.cc/tw/us-fx';
 const fractional='https://www.stocktools.cc/tw/us-fractional';
 const earnings='https://www.stocktools.cc/tw/us-earnings';
 for (const url of [fee,etf,deposit,openAccount,dividend,firstBuy,premarket,orderTypes,adr,fx,fractional,earnings]){
  assert.equal(html.split(url).length-1,2);
  assert.match(header,new RegExp(`href="${url.replaceAll('/','\\/')}"[^>]*target="_blank"[^>]*rel="noopener noreferrer"`));
  assert.match(footer,new RegExp(`href="${url.replaceAll('/','\\/')}"[^>]*target="_blank"[^>]*rel="noopener noreferrer"`));
 }
 assert.match(header,/aria-label="相關工具"/);
 assert.match(footer,/aria-label="相關工具"/);
 assert.match(header,/>相關工具</);
 assert.match(footer,/>相關工具</);
 assert.match(header,/>美股手續費</);
 assert.match(header,/>美股 ETF</);
 assert.match(header,/>美股入金</);
 assert.match(header,/>美股開戶</);
 assert.match(header,/>美股配息</);
 assert.match(header,/>第一次買美股</);
 assert.match(header,/>美股盤前盤後</);
 assert.match(header,/>市價／限價</);
 assert.match(header,/>美股 ADR</);
 assert.match(header,/>美股匯損</);
 assert.match(header,/>美股碎股</);
 assert.match(header,/>美股財報日</);
 assert.match(footer,/>美股手續費</);
 assert.match(footer,/>美股 ETF</);
 assert.match(footer,/>美股入金</);
 assert.match(footer,/>美股開戶</);
 assert.match(footer,/>美股配息</);
 assert.match(footer,/>第一次買美股</);
 assert.match(footer,/>美股盤前盤後</);
 assert.match(footer,/>市價／限價</);
 assert.match(footer,/>美股 ADR</);
 assert.match(footer,/>美股匯損</);
 assert.match(footer,/>美股碎股</);
 assert.match(footer,/>美股財報日</);
 assert.match(header,/href="https:\/\/stocktools\.cc\/"/);
 assert.match(footer,/href="https:\/\/stocktools\.cc\/"/);
 assert.doesNotMatch(html,/firstrade/i);
 assert.doesNotMatch(html,/affiliate|utm_/i);
});

test('header exposes one OKX and one Pionex signup link',()=>{
 const html=page.split('<script>')[0];
 const header=html.split('<header>')[1].split('</header>')[0];
 const footer=html.split('<footer>')[1].split('</footer>')[0];
 const okx='https://okx.com/join/75395880';
 const pionex='https://www.pionex.com/zh-TW/signUp?r=0rcgGsu5GKg';
 assert.equal(html.split(okx).length-1,1);
 assert.equal(html.split(pionex).length-1,1);
 assert.match(header,new RegExp(`href="${okx.replaceAll('/','\\/')}"[^>]*target="_blank"[^>]*rel="noopener noreferrer"`));
 assert.match(header,new RegExp(`href="${pionex.replaceAll('/','\\/').replaceAll('?','\\?')}"[^>]*target="_blank"[^>]*rel="noopener noreferrer"`));
 assert.match(header,/OKX 開戶/);
 assert.match(header,/派網開戶/);
 assert.doesNotMatch(footer,/okx\.com\/join/);
 assert.doesNotMatch(footer,/pionex\.com/);
 assert.doesNotMatch(header,/affiliate|utm_/i);
 assert.doesNotMatch(footer,/affiliate|utm_/i);
});

test('replay playback advances real snapshots and stops at the end or on seeking',()=>{
 const h=setup();let callback;let cancelled=0;h.ctx.setTimeout=fn=>{callback=fn;return 42};h.ctx.clearTimeout=()=>cancelled++;
 h.run('REPLAY_DATA={as_of:2};REPLAY_FRAMES=[{ts:1,groups:{}},{ts:2,groups:{}}];toggleReplay()');
 assert.equal(h.elements.get('replay-play').textContent,'暫停');callback();
 assert.equal(h.run('REPLAY_INDEX'),1);assert.equal(h.run('REPLAY_TIMER'),null);
 h.run('toggleReplay();seekReplay(0)');assert.equal(h.run('REPLAY_TIMER'),null);assert(cancelled>0);
});
