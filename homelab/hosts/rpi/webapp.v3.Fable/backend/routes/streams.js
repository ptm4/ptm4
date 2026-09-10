// Streams — control proxy to stream-station on noblenumbat, plus the two things v3
// adds on top of it:
//
//   GET  /guide  — "what's worth watching": HLTV's day feed joined with the Valve
//                  Regional Standings and the channel directory, plus the station's
//                  live slots and the presets.
//   POST /watch  — one-tap start: given a channel (or a match's stream URL) pick a free
//                  slot (or reuse one already on that channel) and start it.
//
// EPISTEMICS (decided with Peter 2026-09-10, adopting webapp.v3.Astra's posture).
// The guide reports evidence and refuses to manufacture it:
//   - Rank comes from the VRS feed as a NUMBER per team, never inferred from stars.
//     HLTV's stars are a match rating, not a tournament tier, so no S/A/B tier is
//     derived here; `tier` passes through only if the feed itself says 'S'.
//   - "Premier series" is a claim about the EVENT NAME (see lib/stream-catalog.js),
//     labelled as such, not a tier ruling.
//   - A match gets a watch channel only when HLTV actually supplied a stream URL.
//     An event called "BLAST Premier" is not evidence that twitch/blastpremier is
//     carrying THIS match, so there is no organizer fallback.
//   - A stale feed cannot assert "live": past STALE_AFTER_MS the status of a match
//     the feed called live degrades to 'unknown'.
//   - Directory channels carry no live inference; we report only what OUR station is
//     playing and how many of today's matches list that channel as their broadcast.
//
// stream-station resolves live streams with streamlink and remuxes them to HLS; the
// bearer token lives ONLY here — the browser never sees it. The video itself does not
// come through this route: nginx proxies /hls straight to nn (see nginx-wg.conf).
const { proxyJson } = require('../lib/upstream');
const { cachedInject } = require('../lib/hldb-cache');
const { FALLBACK_PRESETS, channelFromUrl, organizerForChannel, normTeam, isPremier } = require('../lib/stream-catalog');

const STREAM_URL = process.env.STREAM_URL || 'http://192.168.1.6:8098';
const STREAM_TOKEN = process.env.HL_STREAM_TOKEN || '';
const TOP_N = 20;
// The bot caches its day feed for 15 min and falls back to a last-good scrape when
// HLTV is unreachable, so "fetched a while ago" is a normal state, not an error —
// but it does mean we can no longer claim a match is live.
const STALE_AFTER_MS = 30 * 60_000;

const ROUTES = [
  { method: 'get',  path: '/status',  up: 'GET',  upPath: '/status' },
  { method: 'get',  path: '/presets', up: 'GET',  upPath: '/presets' },
  { method: 'post', path: '/start',   up: 'POST', upPath: '/start', timeout: 15000 },
  { method: 'post', path: '/stop',    up: 'POST', upPath: '/stop' },
  // Sent by the open page each poll: "these slots are still wanted". Without it the
  // idle reaper would kill whichever slots aren't in the visible tab.
  { method: 'post', path: '/keepalive', up: 'POST', upPath: '/keepalive' },
];

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

    // The bot serves VRS as an ordered list (bare names, or {name,rank}); position IS
    // the rank. Keep the whole list — a team at #26 is worth showing as #26 rather
    // than flattening it to "unranked".
    const vrsRaw = vrs.status === 200 && Array.isArray(vrs.data?.teams) ? vrs.data.teams : [];
    const ranks = new Map();
    vrsRaw.forEach((t, i) => {
      const name = typeof t === 'string' ? t : t?.name;
      const rank = typeof t === 'object' && Number.isFinite(t?.rank) ? t.rank : i + 1;
      if (name) ranks.set(normTeam(name), rank);
    });
    const rankingKnown = ranks.size > 0;

    // A feed we fetched long ago cannot be quoted for what is happening NOW.
    const fetchedMs = Number(day.data?.fetched_at) * 1000;
    const stale = !!day.data?.stale || !Number.isFinite(fetchedMs) || Date.now() - fetchedMs > STALE_AFTER_MS;

    const slots = status?.slots || [];
    const playing = new Map();   // "platform/channel" → slot we are playing it in
    for (const s of slots) {
      if (['starting', 'running'].includes(s.state) && s.channel) playing.set(`${s.platform}/${String(s.channel).toLowerCase()}`, s.slot);
    }

    const matches = (day.status === 200 && Array.isArray(day.data?.matches) ? day.data.matches : []).map((m) => {
      // Only a stream HLTV actually attached to THIS match becomes a watch target.
      const watch = channelFromUrl(m.stream?.url);
      const key = watch?.type === 'channel' ? `${watch.platform}/${watch.channel}` : null;
      const rank1 = ranks.get(normTeam(m.team1)) ?? null;
      const rank2 = ranks.get(normTeam(m.team2)) ?? null;
      return {
        ...m,
        rank1,
        rank2,
        top20: (rank1 != null && rank1 <= TOP_N) || (rank2 != null && rank2 <= TOP_N),
        premier: isPremier(m.event),
        tier: m.tier === 'S' ? 'S' : null,          // never derived from stars
        // A stale feed's "live" is a memory, not an observation.
        status: stale && m.status === 'live' ? 'unknown' : m.status,
        watch,
        channel: watch?.type === 'channel'
          ? { platform: watch.platform, channel: watch.channel, label: m.stream?.name || watch.channel }
          : null,
        stream_source: m.stream ? (m.stream.name || 'HLTV match stream') : null,
        watching_slot: key && playing.has(key) ? playing.get(key) : null,
      };
    });

    const statusRank = { live: 0, unknown: 1, upcoming: 2, finished: 3 };
    // Priority within a status: top-20 first, then premier events, then start time.
    const priority = (m) => (m.top20 ? 0 : m.premier || m.tier === 'S' ? 1 : 2);
    matches.sort((a, b) => (statusRank[a.status] ?? 9) - (statusRank[b.status] ?? 9)
      || priority(a) - priority(b)
      || (a.start_unix || 0) - (b.start_unix || 0));

    // Events rolled up: one card per tournament, describing only what the feed said.
    const events = {};
    for (const m of matches) {
      const e = events[m.event] || (events[m.event] = {
        event: m.event, premier: m.premier, live: 0, unknown: 0, upcoming: 0, finished: 0,
        top20: 0, channel: m.channel, stream_source: m.stream_source,
      });
      e[m.status] = (e[m.status] || 0) + 1;
      if (m.top20) e.top20 += 1;
      if (!e.channel && m.channel) { e.channel = m.channel; e.stream_source = m.stream_source; }
    }
    const eventList = Object.values(events)
      .sort((a, b) => (b.live - a.live) || (b.top20 - a.top20) || (Number(b.premier) - Number(a.premier)) || (b.upcoming - a.upcoming));

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
          ...c,
          group: g.name,
          group_label: g.label,
          org: c.org || (org ? org.label : null),
          // What OUR station is doing with this channel — an observation, not a guess.
          watching_slot: playing.get(key) ?? null,
          // How many of today's matches name this channel as their broadcast. This is
          // read off the feed's own stream links; it is NOT a claim the channel is live.
          listed_matches: matches.filter((m) => m.channel && `${m.channel.platform}/${m.channel.channel}` === key
            && (m.status === 'live' || m.status === 'upcoming' || m.status === 'unknown')).length,
        });
      }
    }

    return {
      station: status
        ? { ok: true, version: status.version, idle_secs: status.idle_secs, profiles: status.profiles, slots }
        : { ok: false, slots: [] },
      quality_default: presets.quality_default || FALLBACK_PRESETS.quality_default,
      channels,
      matches,
      events: eventList,
      vrs: {
        as_of: vrs.data?.as_of || null,
        known: rankingKnown,
        system: 'Valve Regional Standings, via HLTV',
        counted: ranks.size,
        top: vrsRaw.slice(0, TOP_N).map((t) => (typeof t === 'string' ? t : t?.name)).filter(Boolean),
        error: vrs.status === 200 ? null : (vrs.data?.error || `HTTP ${vrs.status}`),
      },
      hltv: {
        ok: day.status === 200,
        stale,
        fetched_at: day.data?.fetched_at || null,
        date: day.data?.date || null,
        error: day.status === 200 ? null : (day.data?.error || `HTTP ${day.status}`),
      },
      coverage: "HLTV's cached day feed. It deep-scrapes a bounded number of match pages per run, so map scores and broadcast links exist only for those; matches without a listed stream cannot be started from here.",
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
