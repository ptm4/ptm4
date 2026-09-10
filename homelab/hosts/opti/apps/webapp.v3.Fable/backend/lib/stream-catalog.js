// The channel directory the Streams guide reasons with. stream-station's presets.json
// stays the source for what the station will start; this file adds what the guide
// needs on top: which organizer a channel belongs to (for a label), and how to read a
// broadcast URL HLTV supplied.
//
// What this file deliberately does NOT do (decided 2026-09-10): it never maps an
// event name to a channel. HLTV attaching a stream to a match is evidence; an event
// merely being called "BLAST Premier" is not evidence that twitch/blastpremier is
// carrying THIS match right now. See routes/streams.js.
const ORGANIZERS = [
  // key (matched against our own directory entries) → twitch channels we host
  { key: 'blast', label: 'BLAST', channels: ['blastpremier', 'blasttv'] },
  { key: 'esl', label: 'ESL / IEM', channels: ['eslcs', 'eslcsb'] },
  { key: 'iem', label: 'ESL / IEM', channels: ['eslcs', 'eslcsb'] },
  { key: 'pgl', label: 'PGL', channels: ['pgl'] },
  { key: 'hltv', label: 'HLTV', channels: ['hltvorg'] },
  { key: 'esea', label: 'ESEA', channels: ['esea'] },
  { key: 'fissure', label: 'FISSURE', channels: ['fissure'] },
];

// "Premier series" is a claim about the EVENT NAME, not a tier ruling. Qualifiers and
// feeder tiers of the same series are excluded, because "IEM Fall Open Qualifier" is
// not the thing people mean by an IEM match.
const PREMIER_RE = /\b(major|iem|blast|pgl|fissure|esl pro league)\b/i;
const NOT_PREMIER_RE = /qualifier|challenger|regional|open cup|closed cup|relegation/i;
const isPremier = (event) => PREMIER_RE.test(event || '') && !NOT_PREMIER_RE.test(event || '');

const FALLBACK_PRESETS = {
  quality_default: 'best,1440p60,1440p,1080p60,1080p,720p60,720p,worst',
  groups: [
    { name: 'organizers', label: 'Tournament broadcasts', channels: [
      { platform: 'twitch', channel: 'eslcs', label: 'ESL CS', org: 'ESL / IEM' },
      { platform: 'twitch', channel: 'eslcsb', label: 'ESL CS B', org: 'ESL / IEM' },
      { platform: 'twitch', channel: 'blastpremier', label: 'BLAST Premier', org: 'BLAST' },
      { platform: 'twitch', channel: 'blasttv', label: 'BLAST.tv', org: 'BLAST' },
      { platform: 'twitch', channel: 'pgl', label: 'PGL', org: 'PGL' },
      { platform: 'twitch', channel: 'hltvorg', label: 'HLTV.org', org: 'HLTV' },
      { platform: 'twitch', channel: 'esea', label: 'ESEA', org: 'ESL' },
      { platform: 'twitch', channel: 'fissure', label: 'FISSURE', org: 'FISSURE' },
    ] },
    { name: 'streamers', label: 'CS2 streamers', channels: [
      { platform: 'twitch', channel: 'fl0m', label: 'fl0m' },
      { platform: 'twitch', channel: 'ohnepixel', label: 'ohnePixel' },
      { platform: 'twitch', channel: 'tarik', label: 'tarik' },
      { platform: 'twitch', channel: 's1mple', label: 's1mple' },
      { platform: 'twitch', channel: 'm0nesy', label: 'm0NESY' },
      { platform: 'twitch', channel: 'shroud', label: 'shroud' },
      { platform: 'twitch', channel: 'stewie2k', label: 'Stewie2K' },
      { platform: 'twitch', channel: 'elige', label: 'EliGE' },
      { platform: 'twitch', channel: 'jasonr', label: 'JasonR' },
      { platform: 'twitch', channel: 'gaules', label: 'Gaules (PT-BR)' },
    ] },
    { name: 'youtube', label: 'YouTube live', channels: [
      { platform: 'youtube', channel: 'BLASTPremier', label: 'BLAST Premier (YouTube)', org: 'BLAST' },
      { platform: 'youtube', channel: 'ESLCS', label: 'ESL CS (YouTube)', org: 'ESL / IEM' },
      { platform: 'youtube', channel: 'PGLesports', label: 'PGL (YouTube)', org: 'PGL' },
    ] },
  ],
};

const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();

// Team names normalize for VRS matching: "Team Spirit" ≈ "Spirit".
const normTeam = (t) => String(t || '').replace(/^team\s+/i, '').toLowerCase().replace(/[^a-z0-9]/g, '');

// Turn a broadcast URL HLTV supplied into something stream-station can start.
// Strict on purpose: https only, no embedded credentials, and Twitch's reserved
// paths (/videos/…, /directory/…) are not channels. A YouTube link is passed through
// as a URL — a watch link carries no channel handle, and VLC can open it directly.
function channelFromUrl(raw) {
  if (!raw) return null;
  try {
    const u = new URL(raw);
    if (u.protocol !== 'https:' || u.username || u.password) return null;
    const host = u.hostname.replace(/^www\./, '');
    const seg = u.pathname.split('/').filter(Boolean);
    if (host === 'twitch.tv' && seg.length === 1 && /^[a-z0-9_]{1,32}$/i.test(seg[0])
        && !['videos', 'directory', 'downloads', 'settings', 'p'].includes(seg[0].toLowerCase())) {
      return { type: 'channel', platform: 'twitch', channel: seg[0].toLowerCase() };
    }
    if (host === 'kick.com' && seg.length === 1 && /^[a-z0-9_-]{1,32}$/i.test(seg[0])) {
      return { type: 'channel', platform: 'kick', channel: seg[0] };
    }
    if (host === 'youtube.com' || host === 'youtu.be') return { type: 'url', url: u.href };
  } catch (_) { /* not a URL */ }
  return null;
}

function organizerForChannel(channel) {
  const c = String(channel || '').toLowerCase();
  return ORGANIZERS.find((o) => o.channels.includes(c)) || null;
}

module.exports = { ORGANIZERS, FALLBACK_PRESETS, norm, normTeam, isPremier, channelFromUrl, organizerForChannel };
