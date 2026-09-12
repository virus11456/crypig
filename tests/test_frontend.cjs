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
 const ctx=vm.createContext({fetch,document,console,AbortController,setTimeout,clearTimeout,window:{},navigator:{}});
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
