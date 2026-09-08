// Streams — control proxy to stream-station on noblenumbat, plus the two things v3
// adds on top of it:
//
//   GET  /guide  — "what's worth watching": HLTV's day feed joined with the Valve
//                  ranking (top 20) and the channel directory, so every match carries a
//                  tier, whether a top-20 team plays, and the broadcast channel the
//                  station can start; plus the station's live slots and the presets.
//   POST /watch  — one-tap start: given a channel (or a match's stream URL) pick a free
//                  slot (or reuse one already on that channel) and start it.
//
// stream-station resolves live streams with streamlink and remuxes them to HLS; the
// bearer token lives ONLY here — the browser never sees it. The video itself does not
// come through this route: nginx proxies /hls straight to nn (see nginx-wg.conf).
const { proxyJson } = require('../lib/upstream');
const { cachedInject } = require('../lib/hldb-cache');
const { FALLBACK_PRESETS, channelFromUrl, organizerForEvent, organizerForChannel, norm } = require('../lib/stream-catalog');

const STREAM_URL = process.env.STREAM_URL || 'http://192.168.1.6:8098';
const STREAM_TOKEN = process.env.HL_STREAM_TOKEN || '';
const TOP_N = 20;

// /start is slow on purpose: streamlink has to resolve the channel and negotiate the
// source before the first segment exists, which is a few seconds on a good day.
const ROUTES = [
  { method: 'get',  path: '/status',  up: 'GET',  upPath: '/status' },
  { method: 'get',  path: '/presets', up: 'GET',  upPath: '/presets' },
  { method: 'post', path: '/start',   up: 'POST', upPath: '/start', timeout: 15000 },
  { method: 'post', path: '/stop',    up: 'POST', upPath: '/stop' },
  // Sent by the open page each poll: "these slots are still wanted". Without it the
  // idle reaper would kill whichever slots aren't in the visible tab.
  { method: 'post', path: '/keepalive', up: 'POST', upPath: '/keepalive' },
];

const normTeam = (t) => norm(String(t || '').replace(/^team\s+/i, '')).replace(/ /g, '');

// Tier: S = the match HLTV rates 4-5 stars, or 3 stars with a top-20 team; A = 2-3 stars
// or any top-20 team; B = everything else. "stars" is HLTV's own match rating.
function tierFor(m, topSet) {
  const stars = m.stars ?? 0;
  const t1 = topSet.has(normTeam(m.team1)), t2 = topSet.has(normTeam(m.team2));
  const top = t1 || t2;
  if (stars >= 4 || (stars >= 3 && top) || (t1 && t2)) return 'S';
  if (stars >= 2 || top) return 'A';
  return 'B';
}

module.exports = async function streamsRoutes(app) {
  const authHeader = STREAM_TOKEN ? { Authorization: `Bearer ${STREAM_TOKEN}` } : undefined;

  for (const r of ROUTES) {
    app[r.method](r.path, async (req, reply) => {
      // Without a token every POST would come back 401 from nn, which reads in the UI
      // as "the stream station rejected me" rather than "this dashboard is misconfigured".
      if (r.method === 'post' && !STREAM_TOKEN) {
        return reply.code(500).send({ error: 'HL_STREAM_TOKEN is not set on the webapp — cannot control stream-station' });
      }
      try {
        const out = await proxyJson(STREAM_URL, r.up, r.upPath,
          r.method === 'get' ? undefined : req.body, r.timeout || 8000, authHeader);
        reply.code(out.status).send(out.data);
      } catch (e) {
        reply.code(502).send({ error: `stream station unreachable: ${e.message}` });
      }
    });
  }

  async function station(pathname, timeout = 8000) {
    try {
      const out = await proxyJson(STREAM_URL, 'GET', pathname, undefined, timeout);
      return out.status === 200 ? out.data : null;
    } catch (_) { return null; }
  }

  // ── GET /api/streams/guide ──────────────────────────────────────────────────
  app.get('/guide', async () => {
    const [status, presetsRaw, day, vrs] = await Promise.all([
      station('/status'),
      station('/presets'),
      cachedInject(app, '/api/hltv/day', 60_000),
      cachedInject(app, '/api/hltv/vrs', 10 * 60_000),
    ]);
    const presets = presetsRaw && Array.isArray(presetsRaw.groups) ? presetsRaw : FALLBACK_PRESETS;
    const vrsTeams = vrs.status === 200 && Array.isArray(vrs.data?.teams) ? vrs.data.teams.slice(0, TOP_N) : [];
    const topSet = new Set(vrsTeams.map(normTeam));
    const slots = status?.slots || [];
    const live = new Map();   // "platform/channel" → slot
    for (const s of slots) if (['starting', 'running'].includes(s.state) && s.channel) live.set(`${s.platform}/${String(s.channel).toLowerCase()}`, s.slot);

    const matches = (day.status === 200 && Array.isArray(day.data?.matches) ? day.data.matches : []).map((m) => {
      const fromUrl = channelFromUrl(m.stream?.url);
      const org = organizerForEvent(m.event);
      // Prefer the exact channel HLTV links; fall back to the organizer's main channel.
      const channel = fromUrl || (org ? { platform: 'twitch', channel: org.channels[0] } : null);
      const key = channel ? `${channel.platform}/${channel.channel}` : null;
      return {
        ...m,
        tier: tierFor(m, topSet),
        top20: [normTeam(m.team1), normTeam(m.team2)].filter((t) => topSet.has(t)),
        organizer: org ? org.label : (m.stream?.name || null),
        channel: channel ? { ...channel, label: m.stream?.name || (org ? org.label : channel.channel) } : null,
        watching_slot: key && live.has(key) ? live.get(key) : null,
      };
    });

    const tierRank = { S: 0, A: 1, B: 2 };
    const statusRank = { live: 0, upcoming: 1, finished: 2 };
    matches.sort((a, b) => statusRank[a.status] - statusRank[b.status] || tierRank[a.tier] - tierRank[b.tier] || (a.start_unix || 0) - (b.start_unix || 0));

    // Events rolled up: one card per tournament with its best tier and what's on.
    const events = {};
    for (const m of matches) {
      const e = events[m.event] || (events[m.event] = { event: m.event, tier: 'B', live: 0, upcoming: 0, finished: 0, organizer: m.organizer, channel: m.channel, top20: new Set() });
      if (tierRank[m.tier] < tierRank[e.tier]) e.tier = m.tier;
      e[m.status] = (e[m.status] || 0) + 1;
      for (const t of m.top20) e.top20.add(t);
      if (!e.channel && m.channel) e.channel = m.channel;
    }
    const eventList = Object.values(events).map((e) => ({ ...e, top20: [...e.top20] }))
      .sort((a, b) => (b.live - a.live) || tierRank[a.tier] - tierRank[b.tier] || (b.upcoming - a.upcoming));

    // The station's presets first, then the built-in directory for anything it lacks —
    // so the guide is rich even while presets.json on nn is still the old four channels.
    const groups = [...(presets.groups || [])];
    for (const fg of FALLBACK_PRESETS.groups) {
      const g = groups.find((x) => x.name === fg.name) || (groups.push({ ...fg, channels: [] }), groups[groups.length - 1]);
      for (const c of fg.channels) {
        if (!groups.some((gg) => (gg.channels || []).some((x) => x.platform === c.platform && String(x.channel).toLowerCase() === c.channel.toLowerCase()))) {
          g.channels = [...(g.channels || []), c];
        }
      }
    }
    const channels = [];
    for (const g of groups) {
      for (const c of g.channels || []) {
        const key = `${c.platform}/${String(c.channel).toLowerCase()}`;
        const org = organizerForChannel(c.channel);
        channels.push({
          ...c, group: g.name, group_label: g.label,
          org: c.org || (org ? org.label : null),
          watching_slot: live.get(key) ?? null,
          // "on air" = some match today links this channel (live) — the closest thing to
          // a Twitch live check without Twitch API credentials.
          on_air: matches.some((m) => m.status === 'live' && m.channel && `${m.channel.platform}/${m.channel.channel}` === key),
          scheduled: matches.filter((m) => m.status === 'upcoming' && m.channel && `${m.channel.platform}/${m.channel.channel}` === key).length,
        });
      }
    }

    return {
      station: status ? { ok: true, version: status.version, idle_secs: status.idle_secs, profiles: status.profiles, slots } : { ok: false, slots: [] },
      quality_default: presets.quality_default || FALLBACK_PRESETS.quality_default,
      channels,
      matches,
      events: eventList,
      vrs: { as_of: vrs.data?.as_of || null, top: vrsTeams },
      hltv: { ok: day.status === 200, stale: !!day.data?.stale, fetched_at: day.data?.fetched_at || null, date: day.data?.date || null, error: day.status === 200 ? null : (day.data?.error || `HTTP ${day.status}`) },
      generated_at: new Date().toISOString(),
    };
  });

  // ── POST /api/streams/watch ─────────────────────────────────────────────────
  // { platform?, channel? | url?, slot?, quality?, profile? } → starts (or reuses) a slot.
  app.post('/watch', {
    schema: { body: { type: 'object', properties: {
      platform: { type: 'string' }, channel: { type: 'string' }, url: { type: 'string' },
      slot: { type: 'integer', minimum: 1, maximum: 4 }, quality: { type: 'string' }, profile: { type: 'string' },
    } } },
  }, async (req, reply) => {
    if (!STREAM_TOKEN) return reply.code(500).send({ error: 'HL_STREAM_TOKEN is not set on the webapp — cannot control stream-station' });
    let { platform, channel, url, slot, quality, profile } = req.body || {};
    if (url && !channel) {
      const c = channelFromUrl(url);
      if (c) { platform = c.platform; channel = c.channel; url = undefined; }
    }
    if (!channel && !url) return reply.code(400).send({ error: 'channel (with platform) or url is required' });
    platform = platform || 'twitch';

    const status = await station('/status');
    if (!status) return reply.code(502).send({ error: 'stream station unreachable' });
    const slots = status.slots || [];
    const already = channel && slots.find((s) => ['starting', 'running'].includes(s.state) && s.platform === platform && String(s.channel).toLowerCase() === String(channel).toLowerCase());
    if (already) return { ok: true, slot: already.slot, state: already.state, reused: true };

    if (!slot) {
      const free = slots.find((s) => !['starting', 'running'].includes(s.state));
      if (!free) return reply.code(409).send({ error: 'all 4 slots are busy — stop one first', slots: slots.map((s) => ({ slot: s.slot, state: s.state, channel: s.channel })) });
      slot = free.slot;
    }
    const body = channel
      ? { slot, type: 'channel', platform, channel, ...(quality ? { quality } : {}), ...(profile ? { profile } : {}) }
      : { slot, type: 'url', url, ...(profile ? { profile } : {}) };
    try {
      const out = await proxyJson(STREAM_URL, 'POST', '/start', body, 15000, authHeader);
      if (out.status !== 200) return reply.code(out.status).send(out.data);
      if (app.events) app.events.emit('streams', { slot, state: 'starting', platform, channel: channel || url });
      return { ...out.data, reused: false, platform, channel: channel || null, url: url || null };
    } catch (e) {
      return reply.code(502).send({ error: `stream station unreachable: ${e.message}` });
    }
  });
};
