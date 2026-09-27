// The Streams guide — ported from v3's routes/streams.js as a pure function over
// snapshots. The epistemics are Peter's decisions (2026-09-10) and are kept exactly:
//   - rank comes from the VRS feed as a NUMBER per team, never inferred from stars;
//   - "premier" is a claim about the EVENT NAME, labelled as such;
//   - a match is watchable only when HLTV attached a stream URL to THAT match
//     (no "the event is BLAST so it must be on twitch/blastpremier" fallback);
//   - a stale feed cannot assert "live": past 30 min, live degrades to 'unknown';
//   - directory channels carry no live inference — only what OUR station is playing.
'use strict';
const { FALLBACK_PRESETS, channelFromUrl, organizerForChannel, normTeam, isPremier } = require('./stream-catalog');

const TOP_N = 20;
const STALE_AFTER_MS = 30 * 60_000;
const ACTIVE = ['starting', 'running'];

function buildGuide({ status, presets: presetsRaw, day, dayMeta, vrs }) {
  const presets = presetsRaw && Array.isArray(presetsRaw.groups) ? presetsRaw : FALLBACK_PRESETS;

  const vrsRaw = Array.isArray(vrs?.teams) ? vrs.teams : [];
  const ranks = new Map();
  vrsRaw.forEach((t, i) => {
    const name = typeof t === 'string' ? t : t?.name;
    const rank = typeof t === 'object' && Number.isFinite(t?.rank) ? t.rank : i + 1;
    if (name) ranks.set(normTeam(name), rank);
  });

  const fetchedMs = Number(day?.fetched_at) * 1000;
  const stale = !!day?.stale || dayMeta?.ok === false
    || !Number.isFinite(fetchedMs) || Date.now() - fetchedMs > STALE_AFTER_MS;

  const slots = status?.slots || [];
  const playing = new Map();
  for (const s of slots) {
    if (ACTIVE.includes(s.state) && s.channel) playing.set(`${s.platform}/${String(s.channel).toLowerCase()}`, s.slot);
  }

  const matches = (Array.isArray(day?.matches) ? day.matches : []).map((m) => {
    const watch = channelFromUrl(m.stream?.url);
    const key = watch?.type === 'channel' ? `${watch.platform}/${watch.channel}` : null;
    const rank1 = ranks.get(normTeam(m.team1)) ?? null;
    const rank2 = ranks.get(normTeam(m.team2)) ?? null;
    return {
      id: m.id, url: m.url, event: m.event, stars: m.stars ?? 0, bo: m.bo,
      team1: m.team1, team2: m.team2, score1: m.score1 ?? null, score2: m.score2 ?? null,
      start_unix: m.start_unix ?? null, maps: m.maps ?? [],
      rank1, rank2,
      top20: (rank1 != null && rank1 <= TOP_N) || (rank2 != null && rank2 <= TOP_N),
      premier: isPremier(m.event),
      status: stale && m.status === 'live' ? 'unknown' : m.status,
      channel: watch?.type === 'channel' ? { platform: watch.platform, channel: watch.channel, label: m.stream?.name || watch.channel } : null,
      watching_slot: key && playing.has(key) ? playing.get(key) : null,
    };
  });
  const statusRank = { live: 0, unknown: 1, upcoming: 2, finished: 3 };
  const priority = (m) => (m.top20 ? 0 : m.premier ? 1 : 2);
  matches.sort((a, b) => (statusRank[a.status] ?? 9) - (statusRank[b.status] ?? 9)
    || priority(a) - priority(b) || (a.start_unix || 0) - (b.start_unix || 0));

  // Station presets first, then the built-in directory for anything they lack.
  const groups = (presets.groups || []).map((g) => ({ ...g, channels: [...(g.channels || [])] }));
  for (const fg of FALLBACK_PRESETS.groups) {
    let g = groups.find((x) => x.name === fg.name);
    if (!g) { g = { ...fg, channels: [] }; groups.push(g); }
    for (const c of fg.channels) {
      const known = groups.some((gg) => gg.channels.some((x) => x.platform === c.platform && String(x.channel).toLowerCase() === c.channel.toLowerCase()));
      if (!known) g.channels.push(c);
    }
  }
  const channels = groups.flatMap((g) => g.channels.map((c) => {
    const key = `${c.platform}/${String(c.channel).toLowerCase()}`;
    const org = organizerForChannel(c.channel);
    return {
      ...c, group: g.name, group_label: g.label, org: c.org || (org ? org.label : null),
      watching_slot: playing.get(key) ?? null,
      listed_matches: matches.filter((m) => m.channel && `${m.channel.platform}/${m.channel.channel}` === key
        && ['live', 'upcoming', 'unknown'].includes(m.status)).length,
    };
  }));

  return {
    station: status ? { ok: true, version: status.version, idle_secs: status.idle_secs, profiles: status.profiles, slots } : { ok: false, slots: [] },
    quality_default: presets.quality_default || FALLBACK_PRESETS.quality_default,
    channels,
    matches,
    vrs: { known: ranks.size > 0, counted: ranks.size, top: vrsRaw.slice(0, TOP_N).map((t) => (typeof t === 'string' ? t : t?.name)).filter(Boolean) },
    hltv: { ok: Array.isArray(day?.matches), stale, fetched_at: day?.fetched_at ?? null, date: day?.date ?? null, error: dayMeta?.ok === false ? dayMeta.error : null },
  };
}

// The Status page's CS2 card: live first, then starred upcoming, then starred results.
function cs2Summary(day) {
  if (!day || !Array.isArray(day.matches)) return null;
  const rank = { live: 0, upcoming: 1, finished: 2 };
  const matches = day.matches
    .filter((m) => m.status === 'live' || (m.stars ?? 0) >= 1)
    .sort((a, b) => (rank[a.status] ?? 3) - (rank[b.status] ?? 3) || (b.stars ?? 0) - (a.stars ?? 0) || (a.start_unix ?? 0) - (b.start_unix ?? 0))
    .slice(0, 8)
    .map((m) => ({
      id: m.id, url: m.url, event: m.event, stars: m.stars ?? 0, status: m.status,
      team1: m.team1, team2: m.team2, score1: m.score1 ?? null, score2: m.score2 ?? null,
      start: m.start_unix ? new Date(m.start_unix * 1000).toISOString() : null,
    }));
  return { date: day.date, stale: !!day.stale, total: day.matches.length, matches };
}

module.exports = { buildGuide, cs2Summary };
