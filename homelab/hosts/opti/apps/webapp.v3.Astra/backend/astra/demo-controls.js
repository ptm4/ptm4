// State is owned by one preview instance and is never sent to a real service.
const { fixture,freshDemo } = require('./fixtures');
const presets = require('./channel-directory.json');
function simulatedRoute(method,path) {
 if(method==='PUT'&&/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/config$/.test(path))return true;
 if(method==='POST'&&/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/send$/.test(path))return true;
 if(method==='POST'&&/^\/api\/streams\/(start|stop|keepalive)$/.test(path))return true;
 if(method==='POST'&&/^\/api\/agents\/(rpi|opti|noblenumbat)\/(reboot|apt-upgrade|restart-service|restart-container|update-container|sync|wake)$/.test(path))return true;
 if(method==='POST'&&/^\/api\/(runners|reports)\/[a-z0-9-]+\/(run|enabled)$/.test(path))return true;
 return method==='POST'&&['/api/agents/sync-all','/api/pihole/blocking','/api/pihole/allow'].includes(path);
}
function createDemo() {
 const slots=Array.from({length:4},(_,i)=>({slot:i+1,state:'idle',channel:null,platform:null,profile:'low-latency',quality:'720p60,720p,best',error:null}));
 let blocking=true;let pauseUntil=null;const events=[];const enabled=new Map();const allowedDomains=new Set();const botConfigs=new Map();
 function read(path,params) {
  if(/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/config$/.test(path))return botConfigs.get(path)||fixture(path);
  if(path==='/api/streams/presets')return presets;
  if(path==='/api/streams/status')return {slots,profiles:['low-latency','smooth'],idle_secs:300,simulated:true};
  if(pauseUntil&&Date.now()>=pauseUntil){blocking=true;pauseUntil=null}
  if(path==='/api/pihole/summary')return {...fixture(path),blocking:{enabled:blocking,timer:pauseUntil?Math.ceil((pauseUntil-Date.now())/1000):null}};
  if(path==='/api/pihole/blocking')return {enabled:blocking,timer:null};
  if(path==='/api/pihole/top')return {domains:fixture(path).domains.filter(d=>!allowedDomains.has(d.domain))};
  if(path==='/api/astra/actions')return {events};
  if(/\/apt-status$/.test(path))return {running:false,result:'success',exit_status:'0',log_tail:['[demo] Package inventory checked.','[demo] Simulated upgrade completed; no host was contacted.']};
  const result=freshDemo(fixture(path,params));
  if(path==='/api/runners'||path==='/api/reports'){const key=path.split('/').pop();return {...result,[key]:result[key].map(r=>({...r,enabled:enabled.has(r.agent)?enabled.get(r.agent):r.enabled}))}}
  return result;
 }
 function act(path,body={}) {
  if(/^\/api\/(weather|jellyfin|healthdigest|sports|hltv)\/config$/.test(path))botConfigs.set(path,{...read(path),...body});
  if(path.startsWith('/api/streams/')){
   if(path.endsWith('/keepalive'))return {ok:true,simulated:true};
   const slot=slots.find(s=>s.slot===body.slot);if(!slot)return {error:'Select a slot from 1 to 4',statusCode:400};
   if(path.endsWith('/stop'))Object.assign(slot,{state:'idle',channel:null,url:null,started_at:null});
   else {
    if(body.type!=='channel'&&body.type!=='url')return {error:'Choose a channel or URL',statusCode:400};
    if(body.type==='channel'&&(!['twitch','youtube','kick'].includes(body.platform)||!/^[@a-z0-9_-]{1,100}$/i.test(body.channel||'')))return {error:'Invalid channel',statusCode:400};
    if(body.type==='url'){try{if(!['https:','http:'].includes(new URL(body.url).protocol))throw Error()}catch{return {error:'A valid HTTP(S) URL is required',statusCode:400}}}
    Object.assign(slot,{...body,state:'running',started_at:Date.now()/1000,uptime_s:0,last_segment_age_s:0,simulated:true});
   }
  }
  if(path==='/api/pihole/blocking'){blocking=body.enabled!==false;pauseUntil=!blocking&&Number(body.seconds)>0?Date.now()+Math.min(Number(body.seconds),86400)*1000:null}
  if(path==='/api/pihole/allow')allowedDomains.add(body.domain);
  if(/\/(runners|reports)\/.+\/enabled$/.test(path))enabled.set(path.split('/')[3],!!body.enabled);
  const event={at:new Date().toISOString(),path,simulated:true,status:'completed'};events.unshift(event);events.splice(100);
  return {ok:true,simulated:true,status:'completed',message:'Simulated locally. No system was contacted.',...event};
 }
 return {read,act};
}
module.exports={createDemo,simulatedRoute};
