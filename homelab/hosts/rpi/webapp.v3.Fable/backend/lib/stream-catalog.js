// The channel directory the Streams guide reasons with. stream-station's presets.json
// stays the source for what the station will start; this file adds what the guide
// needs on top: which organizer a channel belongs to (so an HLTV match can be joined
// to the broadcast that carries it), a category for grouping, and a language hint.
// A channel missing from presets still works — /watch builds the start request from
// platform + channel, presets only decide what gets a chip.
const ORGANIZERS = [
  // key (matches norm() of HLTV stream box names / event names) → twitch channel
  { key: 'blast', label: 'BLAST', channels: ['blastpremier', 'blasttv'] },
  { key: 'esl', label: 'ESL / IEM', channels: ['eslcs', 'eslcsb'] },
  { key: 'iem', label: 'ESL / IEM', channels: ['eslcs', 'eslcsb'] },
  { key: 'intel extreme masters', label: 'ESL / IEM', channels: ['eslcs', 'eslcsb'] },
  { key: 'pgl', label: 'PGL', channels: ['pgl'] },
  { key: 'hltv', label: 'HLTV', channels: ['hltvorg'] },
  { key: 'esea', label: 'ESEA', channels: ['esea'] },
  { key: 'fissure', label: 'FISSURE', channels: ['fissure'] },
];

const FALLBACK_PRESETS = {
  quality_default: 'best,1440p60,1440p,1080p60,1080p,720p60,720p,worst',
  groups: [
    { name: 'organizers', label: 'Tournament broadcasts', channels: [
      { platform: 'twitch', channel: 'eslcs', label: 'ESL CS', org: 'ESL / IEM' },
      { platform: 'twitch', channel: 'eslcsb', label: 'ESL CS B', org: 'ESL / IEM' },
      { platform: 'twitch', channel: 'blastpremier', label: 'BLAST Premier', org: 'BLAST' },
      { platform: 'twitch', channel: 'pgl', label: 'PGL', org: 'PGL' },
      { platform: 'twitch', channel: 'hltvorg', label: 'HLTV.org', org: 'HLTV' },
    ] },
    { name: 'streamers', label: 'CS2 streamers', channels: [
      { platform: 'twitch', channel: 'fl0m', label: 'fl0m' },
      { platform: 'twitch', channel: 'ohnepixel', label: 'ohnePixel' },
      { platform: 'twitch', channel: 'tarik', label: 'tarik' },
    ] },
  ],
};

const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').replace(/\s+/g, ' ').trim();

// "https://twitch.tv/blastpremier" → { platform: 'twitch', channel: 'blastpremier' }
function channelFromUrl(url) {
  if (!url) return null;
  try {
    const u = new URL(url);
    const h = u.hostname.replace(/^www\./, '');
    const seg = u.pathname.split('/').filter(Boolean);
    if (h.endsWith('twitch.tv') && seg.length === 1 && /^[A-Za-z0-9_]{1,32}$/.test(seg[0])) return { platform: 'twitch', channel: seg[0].toLowerCase() };
    if (h.endsWith('kick.com') && seg.length === 1) return { platform: 'kick', channel: seg[0] };
    if (h.endsWith('youtube.com') && seg[0]?.startsWith('@')) return { platform: 'youtube', channel: seg[0].slice(1) };
  } catch (_) { /* not a URL */ }
  return null;
}

// Which organizer an event name belongs to, if any (BLAST Premier Fall Final → blast).
function organizerForEvent(eventName) {
  const n = norm(eventName);
  return ORGANIZERS.find((o) => n.includes(o.key)) || null;
}

function organizerForChannel(channel) {
  const c = String(channel || '').toLowerCase();
  return ORGANIZERS.find((o) => o.channels.includes(c)) || null;
}

module.exports = { ORGANIZERS, FALLBACK_PRESETS, norm, channelFromUrl, organizerForEvent, organizerForChannel };
