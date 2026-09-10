// Astra's only preview entrypoint. Does NOT register legacy operational routes,
// static legacy scripts, ingestion handlers, or background collectors.
const fs = require('node:fs');
const path = require('node:path');
const fastify = require('fastify');
const { snapshot, freshDemo } = require('./astra/fixtures');
const { allowed, createReader } = require('./astra/upstream');
const { liveSnapshot } = require('./astra/snapshot');
const {createDemo,simulatedRoute} = require('./astra/demo-controls');
const {buildGuide} = require('./astra/guide');
const ROOT = path.resolve(__dirname, '..');

async function buildPreview(opts = {}) {
  const runtime = path.resolve(opts.runtime || path.join(ROOT, '.runtime'));
  const relative = path.relative(ROOT, runtime);
  if (relative.startsWith('..') || path.isAbsolute(relative) || !relative) throw new Error('Astra runtime must be a child directory of webapp.v3.Astra');
  // Original UI routes resolve these at import. Only a dedicated local directory.
  process.env.ARCH_DATA_DIR = runtime;
  process.env.AGENT_LOGS_DIR = path.join(runtime, 'agent-logs');
  process.env.REPORTS_DIR = path.join(runtime, 'reports');
  process.env.VITALS_DISABLED = '1';
  let mode = opts.mode || process.env.ASTRA_MODE || 'demo';
  if (!['demo','live-readonly'].includes(mode)) throw new Error('Invalid ASTRA_MODE');
  const read = opts.read || createReader();
  const demo = createDemo();
  let previousLive = null;
  const app = fastify({ logger: opts.logger ?? false, bodyLimit: 5 * 1024 * 1024 });
  const settingsFile = path.join(runtime, 'astra-preferences.json');
  const defaults = { rev: 0, theme: 'dark', density: 'comfortable', reducedMotion: false, favorites: ['jellyfin','vaultwarden','pi-hole','kavita'], launchers: [], acknowledgements: [], savedViews: [] };
  const preferences = () => { try { return { ...defaults, ...JSON.parse(fs.readFileSync(settingsFile, 'utf8')) }; } catch { return { ...defaults }; } };
  app.addHook('onRequest', async (req, reply) => {
    // Browser writes must come from this app, not another page on the LAN.
    const origin = req.headers.origin;
    const permitted = new Set([`http://localhost:${process.env.ASTRA_FRONTEND_PORT || 5174}`, `http://127.0.0.1:${process.env.ASTRA_FRONTEND_PORT || 5174}`, `http://localhost:${process.env.ASTRA_PORT || 3003}`, `http://127.0.0.1:${process.env.ASTRA_PORT || 3003}`]);
    if (origin && !permitted.has(origin)) return reply.code(403).send({ error: 'Origin is not an Astra preview origin' });
    const pathname = req.url.split('?')[0];
    if (!['GET','HEAD'].includes(req.method) && !pathname.startsWith('/api/ui/') && !['/api/astra/mode','/api/astra/preferences','/api/astra/simulate'].includes(pathname) && !(mode==='demo'&&simulatedRoute(req.method,pathname))) return reply.code(403).send({ error: 'Live operational writes are disabled in this preview. Use demo mode to simulate supported controls.' });
    reply.header('Cache-Control', 'no-store');
  });
  app.get('/api/health', async () => ({ status: 'ok', app: 'astra', mode }));
  app.get('/api/astra/capabilities', async () => ({ mode, liveWrites: false, localPreferences: true, simulatedActions: mode === 'demo', legacyUrl: 'https://webapp.rpi.lan:8443/' }));
  app.post('/api/astra/mode', { schema: { body: { type:'object', required:['mode'], additionalProperties:false, properties:{mode:{enum:['demo','live-readonly']}} } } }, async req => { mode = req.body.mode; return { mode }; });
  app.get('/api/astra/snapshot', async () => { if(mode==='demo') return freshDemo(snapshot); previousLive=await liveSnapshot(read,previousLive); return previousLive; });
  app.get('/api/astra/preferences', async () => preferences());
  app.get('/api/astra/actions', async () => mode==='demo'?demo.read('/api/astra/actions'):{events:[]});
  app.get('/api/astra/streams/guide', async (_req,reply) => {
    const source=mode==='demo'?async p=>demo.read(p):read;
    const [day,ranking]=await Promise.allSettled([source('/api/hltv/day'),source('/api/hltv/vrs')]);
    if(day.status==='rejected')return reply.code(503).send({error:'HLTV feed unavailable: '+day.reason.message});
    return {...buildGuide(day.value,ranking.status==='fulfilled'?ranking.value:null),ranking_error:ranking.status==='rejected'?ranking.reason.message:null,mode};
  });
  app.put('/api/astra/preferences', { schema: { body: { type:'object', additionalProperties:false, required:['rev','theme','density','reducedMotion','favorites','launchers','acknowledgements','savedViews'], properties:{
    rev:{type:'integer',minimum:0}, theme:{enum:['dark','light']}, density:{enum:['comfortable','compact']}, reducedMotion:{type:'boolean'},
    favorites:{type:'array',maxItems:100,items:{type:'string',maxLength:120}}, acknowledgements:{type:'array',maxItems:500,items:{type:'string',maxLength:120}},
    launchers:{type:'array',maxItems:100,items:{type:'object',required:['id','name','url','group'],additionalProperties:false,properties:{id:{type:'string',maxLength:80},name:{type:'string',minLength:1,maxLength:80},url:{type:'string',maxLength:1000,pattern:'^https?://'},group:{type:'string',maxLength:60}}}},
    savedViews:{type:'array',maxItems:40,items:{type:'object',required:['name','path'],additionalProperties:false,properties:{name:{type:'string',minLength:1,maxLength:60},path:{type:'string',maxLength:500,pattern:'^/(?!/)'}}}}
  } } } }, async (req, reply) => {
    const current = preferences();
    if (req.body.rev !== current.rev) return reply.code(409).send({ error:'Settings changed in another tab; reload and retry', current });
    const value = { ...req.body, rev: current.rev+1 };
    fs.mkdirSync(runtime,{recursive:true});
    const temp = settingsFile + '.' + process.pid + '.tmp';
    fs.writeFileSync(temp, JSON.stringify(value,null,2)); fs.renameSync(temp,settingsFile);
    return value;
  });
  app.post('/api/astra/simulate', { schema: { body: { type:'object', required:['host','action'], additionalProperties:false, properties:{host:{enum:['rpi','opti','noblenumbat','android']},action:{enum:['restart','update','doctor']}} } } }, async (req, reply) => mode !== 'demo' ? reply.code(403).send({error:'Simulation is available only in demo mode. Live controls are disabled.'}) : { simulated:true, status:'completed', host:req.body.host, action:req.body.action, at:new Date().toISOString(), message:'Simulation completed. No host or service was contacted.' });
  await app.register(require('@fastify/multipart'));
  await app.register(require('./routes/ui'), { prefix:'/api/ui' });
  app.get('/api/*', async (req,reply) => {
    const url = new URL(req.url,'http://astra.local');
    if (!allowed(url.pathname)) return reply.code(404).send({error:'This integration is not exposed in Astra preview'});
    if (mode === 'demo') { const data = demo.read(url.pathname,url.searchParams); return data === undefined ? reply.code(503).send({error:'No demo fixture for this integration',mode}) : data; }
    try { return await read(req.url); } catch(e) { return reply.code(503).send({error:e.message,mode}); }
  });
  app.route({method:['POST','PUT','DELETE'],url:'/api/*',handler:async(req,reply)=>{
    const pathname=req.url.split('?')[0];
    if(mode!=='demo'||!simulatedRoute(req.method,pathname))return reply.code(403).send({error:'Operational requests are blocked'});
    const result=demo.act(pathname,req.body);return reply.code(result.statusCode||200).send(result);
  }});
  // HLS is read-only. Only existing station slots and simple media filenames;
  // fixed upstream origin, no redirects, cookies, credentials or arbitrary URLs.
  app.get('/hls/*',async(req,reply)=>{
    if(mode==='demo')return reply.code(403).send({error:'Demo playback is simulated; no media is fetched'});
    if(!/^\/hls\/slot[1-4]\/[a-zA-Z0-9_-]+\.(m3u8|ts|m4s|mp4)$/.test(req.url))return reply.code(400).send({error:'Invalid HLS path'});
    const origin=new URL(process.env.ASTRA_UPSTREAM||'https://192.168.1.10:8443');
    return new Promise(resolve=>{
      const transport=require(origin.protocol==='https:'?'node:https':'node:http');
      const upstream=transport.get(new URL(req.url,origin),{rejectUnauthorized:process.env.ASTRA_ALLOW_SELF_SIGNED!=='1'},res=>{
        if(res.statusCode!==200){res.resume();resolve(reply.code(res.statusCode>=300&&res.statusCode<400?502:res.statusCode||502).send({error:'Media unavailable'}));return;}
        reply.type(req.url.endsWith('.m3u8')?'application/vnd.apple.mpegurl':req.url.endsWith('.ts')?'video/mp2t':'video/mp4');resolve(reply.send(res));
      });
      upstream.setTimeout(12000,()=>upstream.destroy(new Error('Media request timed out')));
      upstream.on('error',e=>{if(!reply.sent)resolve(reply.code(502).send({error:e.message}))});
    });
  });
  // Static app only. Legacy tool URLs are explicit external links in the UI.
  const dist = path.join(ROOT,'frontend','dist');
  if (fs.existsSync(path.join(dist,'index.html'))) await app.register(require('@fastify/static'), {root:dist,prefix:'/'});
  const wallpaperDir = path.join(runtime,'ui','wallpapers');
  fs.mkdirSync(wallpaperDir,{recursive:true});
  await app.register(require('@fastify/static'), {root:wallpaperDir,prefix:'/media/wallpapers/',decorateReply:false});
  app.get('/astra-preview.html', async (_req,reply) => reply.type('text/html').send(fs.readFileSync(path.join(ROOT,'design','astra-preview.html'),'utf8')));
  app.setNotFoundHandler((req,reply) => {
    if (req.method === 'GET' && !req.url.startsWith('/api/') && (req.headers.accept||'').includes('text/html') && fs.existsSync(path.join(dist,'index.html'))) return reply.type('text/html').send(fs.readFileSync(path.join(dist,'index.html'),'utf8'));
    return reply.code(404).send({error:'Not found'});
  });
  return app;
}
module.exports = buildPreview;
