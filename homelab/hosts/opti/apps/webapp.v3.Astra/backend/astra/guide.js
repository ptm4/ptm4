// Rank evidence comes from the existing HLTV/VRS feed, never inferred from stars.
const normalize = name => String(name || '').toLowerCase().replace(/[^a-z0-9]/g, '');
function channelFromUrl(raw) {
  try {
    const u = new URL(raw);
    if (u.protocol !== 'https:' || u.username || u.password) return null;
    const host = u.hostname.replace(/^www\./,'');
    if (host === 'twitch.tv' && /^\/[a-z0-9_]+\/?$/i.test(u.pathname) && !['videos','directory','downloads'].includes(u.pathname.split('/')[1])) return {platform:'twitch',channel:u.pathname.split('/')[1],type:'channel'};
    if (['youtube.com','youtu.be'].includes(host)) return {type:'url',url:u.href};
    if (host === 'kick.com' && /^\/[a-z0-9_-]+\/?$/i.test(u.pathname)) return {platform:'kick',channel:u.pathname.split('/')[1],type:'channel'};
  } catch {}
  return null;
}
function buildGuide(day, ranking, now = Date.now()) {
  const teams = Array.isArray(ranking?.teams) ? ranking.teams : [];
  const ranks = new Map(teams.map((team,i)=>[normalize(typeof team==='string'?team:team.name), i+1]));
  const fetched = Number(day?.fetched_at)*1000;
  const stale = !!day?.stale || !Number.isFinite(fetched) || now-fetched>30*60000;
  return {date:day?.date||null,fetched_at:day?.fetched_at||null,stale,ranking_as_of:ranking?.as_of||null,ranking_known:teams.length>0,ranking_system:'Valve Regional Standings via HLTV',coverage:'Available cached HLTV feed; upstream filtering may omit matches.',matches:(day?.matches||[]).map(m=>{
    const rank1=ranks.get(normalize(m.team1))||null,rank2=ranks.get(normalize(m.team2))||null;
    const premier=/\b(major|IEM|BLAST|PGL|FISSURE)\b/i.test(m.event||'')&&!/qualifier|challenger|regional|open cup/i.test(m.event||'');
    return {...m,rank1,rank2,top20:!!((rank1&&rank1<=20)||(rank2&&rank2<=20)),tier:m.tier==='S'?'S':null,premier,status:stale&&m.status==='live'?'unknown':m.status,watch:channelFromUrl(m.stream?.url),stream_source:m.stream?'HLTV match stream':null};
  })};
}
module.exports={buildGuide,channelFromUrl};
