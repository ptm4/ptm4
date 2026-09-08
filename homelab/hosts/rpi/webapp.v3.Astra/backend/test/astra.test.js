const {test,before,after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const build = require('../preview-app');
const {safePath,createReader} = require('../astra/upstream');
const {fixture} = require('../astra/fixtures');
const ROOT=path.resolve(__dirname,'../..');
const runtime=path.join(ROOT,'.runtime','tests-'+Date.now());
let app;let calls=[];let failing=false;
before(async()=>{app=await build({runtime,read:async route=>{calls.push(route);if(failing)throw new Error('VPN disconnected');return fixture(route.split('?')[0])}});await app.ready()});
after(async()=>{await app.close()});
test('demo snapshot and integration reads never call upstream',async()=>{
 for(const route of ['/api/astra/snapshot','/api/vitals','/api/weather/preview','/api/streams/status','/api/hltv/day','/api/pricewatch']){const r=await app.inject(route);assert.equal(r.statusCode,200,route)}
 assert.equal(calls.length,0);assert.equal((await app.inject('/api/astra/capabilities')).json().liveWrites,false);
});
test('demo simulation is explicit and never dispatches',async()=>{
 const r=await app.inject({method:'POST',url:'/api/astra/simulate',payload:{host:'rpi',action:'restart'}});assert.equal(r.statusCode,200);assert.equal(r.json().simulated,true);assert.equal(calls.length,0);
});
test('operational writes and side-effectful GET routes are rejected',async()=>{
 for(const route of ['/api/architecture/ingest','/api/hldb/query','/api/llama/ask','/api/samba/config']){assert.equal((await app.inject({method:'POST',url:route,payload:{}})).statusCode,403,route)}
 for(const route of ['/api/healthdigest/preview','/api/jellyfin/check','/api/weather/witty','/api/agents/rpi/reboot'])assert.equal((await app.inject(route)).statusCode,404,route);
 assert.equal(calls.length,0);
});
test('local preferences persist and detect conflicting updates',async()=>{
 const prefs=(await app.inject('/api/astra/preferences')).json();const saved=await app.inject({method:'PUT',url:'/api/astra/preferences',payload:{...prefs,theme:'light',savedViews:[{name:'Rpi',path:'/operations?host=rpi'}]}});
 assert.equal(saved.statusCode,200);assert.equal(saved.json().rev,1);assert.equal(JSON.parse(fs.readFileSync(path.join(runtime,'astra-preferences.json'))).theme,'light');
 assert.equal((await app.inject({method:'PUT',url:'/api/astra/preferences',payload:prefs})).statusCode,409);
});
test('invalid launchers and foreign browser writes are rejected',async()=>{
 const prefs=(await app.inject('/api/astra/preferences')).json();assert.equal((await app.inject({method:'PUT',url:'/api/astra/preferences',payload:{...prefs,launchers:[{id:'x',name:'X',group:'x',url:'javascript:alert(1)'}]}})).statusCode,400);
 assert.equal((await app.inject({method:'PUT',url:'/api/astra/preferences',headers:{origin:'http://untrusted.example'},payload:prefs})).statusCode,403);
});
test('board create, update, conflict and delete stay inside Astra runtime',async()=>{
 const created=await app.inject({method:'POST',url:'/api/ui/boards',payload:{name:'Astra test'}});assert.equal(created.statusCode,200);const board=created.json();
 const payload={...board,widgets:[{id:'clock-1',type:'clock'}],layouts:{lg:[{i:'clock-1',x:0,y:0,w:4,h:3}],sm:[{i:'clock-1',x:0,y:0,w:2,h:4}]}};
 const saved=await app.inject({method:'PUT',url:`/api/ui/boards/${board.slug}`,payload});assert.equal(saved.statusCode,200);assert.equal(saved.json().layouts.sm[0].h,4);
 assert.equal((await app.inject({method:'PUT',url:`/api/ui/boards/${board.slug}`,payload})).statusCode,409);
 assert.ok(fs.existsSync(path.join(runtime,'ui','boards',board.slug+'.json')));
 assert.equal((await app.inject({method:'DELETE',url:`/api/ui/boards/${board.slug}`})).statusCode,200);
});
test('live mode reads reviewed routes, refuses simulation and keeps local writes local',async()=>{
 assert.equal((await app.inject({method:'POST',url:'/api/astra/mode',payload:{mode:'live-readonly'}})).statusCode,200);
 assert.equal((await app.inject('/api/astra/snapshot')).json().mode,'live-readonly');assert.ok(calls.length>0);
 const count=calls.length;const p=(await app.inject('/api/astra/preferences')).json();assert.equal((await app.inject({method:'PUT',url:'/api/astra/preferences',payload:{...p,acknowledgements:['local-only']}})).statusCode,200);assert.equal(calls.length,count);
 assert.equal((await app.inject({method:'POST',url:'/api/astra/simulate',payload:{host:'rpi',action:'restart'}})).statusCode,403);
 for(const route of ['/api/agents/rpi/reboot','/api/pihole/blocking','/api/architecture/ingest','/api/hldb/query','/api/runners/homelab-doctor/run','/api/llama/ask','/api/streams/start','/api/streams/stop','/api/streams/keepalive'])assert.equal((await app.inject({method:'POST',url:route,payload:{slot:1}})).statusCode,403,route);
 assert.equal(calls.length,count);
});
test('VPN failure is visible and never becomes demo data',async()=>{
 failing=true;const s=(await app.inject('/api/astra/snapshot')).json();assert.equal(s.mode,'live-readonly');assert.equal(s.errors.length,6);assert.ok(s.hosts.every(h=>h.status==='unavailable'||h.status==='stale'));assert.ok(s.services.every(s=>s.status==='stale'));
 const r=await app.inject('/api/vitals');assert.equal(r.statusCode,503);assert.match(r.json().error,/VPN disconnected/);failing=false;
});
test('allowlist drops unreviewed query parameters and rejects path tricks',()=>{
 assert.equal(safePath('/api/hldb/search?q=backup&url=http://evil.test'),'/api/hldb/search?q=backup');
 for(const p of ['/api/agents/rpi/reboot','/api/healthdigest/preview','/api/%2e%2e/llama/ask','/api/ui/boards'])assert.equal(safePath(p),null);
});
test('runtime outside Astra is rejected',async()=>{await assert.rejects(build({runtime:path.resolve(ROOT,'../webapp.v3.Fable/.runtime')}),/child directory/)});
test('reader enforces deadline, rejects HTML and does not follow redirects',async()=>{
 let behavior='slow';let requests=0;
 const server=http.createServer((req,res)=>{requests++;if(behavior==='slow')return;if(behavior==='redirect'){res.writeHead(302,{Location:'http://example.invalid/'});res.end();return}res.end('<html>holding page</html>')});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const read=createReader({base:`http://127.0.0.1:${server.address().port}`,timeout:80});
 try{await assert.rejects(read('/api/vitals'),/timed out/);behavior='html';await assert.rejects(read('/api/vitals'),/non-JSON/);behavior='redirect';await assert.rejects(read('/api/vitals'),/302/);assert.equal(requests,3)}finally{server.closeAllConnections();await new Promise(r=>server.close(r))}
});
test('reader deduplicates simultaneous requests and caches monitoring data',async()=>{
 let requests=0;const server=http.createServer((req,res)=>{requests++;res.setHeader('content-type','application/json');res.end('{"hosts":{}}')});await new Promise(r=>server.listen(0,'127.0.0.1',r));
 try{const read=createReader({base:`http://127.0.0.1:${server.address().port}`});await Promise.all([read('/api/vitals'),read('/api/vitals')]);await read('/api/vitals');assert.equal(requests,1)}finally{server.closeAllConnections();await new Promise(r=>server.close(r))}
});
test('stream simulation changes only local slot state, rejects malformed input and never fetches media',async()=>{
 await app.inject({method:'POST',url:'/api/astra/mode',payload:{mode:'demo'}});const count=calls.length;
 const presets=(await app.inject('/api/streams/presets')).json();assert.equal(presets.groups.flatMap(g=>g.channels).length,21);
 assert.equal((await app.inject({method:'POST',url:'/api/streams/start',payload:{slot:9,type:'channel',platform:'twitch',channel:'eslcs'}})).statusCode,400);
 const started=await app.inject({method:'POST',url:'/api/streams/start',payload:{slot:2,type:'channel',platform:'twitch',channel:'blastpremier',quality:'480p,worst'}});assert.equal(started.json().simulated,true);
 assert.equal((await app.inject('/api/streams/status')).json().slots[1].channel,'blastpremier');
 assert.equal((await app.inject('/hls/slot2/index.m3u8')).statusCode,403);
 await app.inject({method:'POST',url:'/api/streams/stop',payload:{slot:2}});assert.equal((await app.inject('/api/streams/status')).json().slots[1].state,'idle');
 assert.equal(calls.length,count);
});
test('expanded demo pages and guide have usable read models without an upstream request',async()=>{
 const count=calls.length;
 for(const route of ['/api/astra/streams/guide','/api/updates','/api/reports','/api/reports/journal-hunt-latest','/api/runners/hardware-latest','/api/runners/network-latest','/api/runners/homelab-doctor-latest/log','/api/trends','/api/hldb/dataplane','/api/hldb/schema','/api/samba/status','/api/samba/config','/api/llama/status','/api/llama/models','/api/weather/config'])assert.equal((await app.inject(route)).statusCode,200,route);
 const guide=(await app.inject('/api/astra/streams/guide')).json();assert.equal(guide.matches[0].watch.channel,'blastpremier');assert.equal(guide.matches[0].top20,true);assert.equal(guide.matches[0].tier,null);assert.equal(calls.length,count);
});
test('guide treats rank20 as eligible, rank21 as excluded; unknown and stale are explicit',()=>{
 const {buildGuide,channelFromUrl}=require('../astra/guide');const now=Date.now();const ranking={as_of:'sample',teams:Array.from({length:21},(_,i)=>'Team '+(i+1))};const day={fetched_at:now/1000,matches:[{team1:'Team 20',team2:'Unranked',event:'Regional qualifier',status:'live',stars:5},{team1:'Team 21',team2:'Other',event:'Qualifier',status:'upcoming'}]};
 const guide=buildGuide(day,ranking,now);assert.equal(guide.matches[0].top20,true);assert.equal(guide.matches[1].top20,false);assert.equal(guide.matches[0].tier,null);assert.equal(guide.matches[0].premier,false);
 assert.equal(buildGuide(day,null,now).ranking_known,false);assert.equal(buildGuide(day,null,now).matches[0].top20,false);assert.equal(buildGuide(day,ranking,now+3600000).matches[0].status,'unknown');
 for(const url of ['javascript:alert(1)','https://twitch.tv.evil.example/eslcs','https://user:pass@twitch.tv/eslcs','https://twitch.tv/directory','http://127.0.0.1/admin'])assert.equal(channelFromUrl(url),null);
 assert.equal(channelFromUrl('https://www.twitch.tv/eslcs').channel,'eslcs');
});
