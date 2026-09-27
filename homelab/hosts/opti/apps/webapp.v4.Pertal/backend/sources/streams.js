// Streams + CS2 data: stream-station on noblenumbat (slots, presets) and hltv-api on opti
// (today's matches, Valve Regional Standings). All polled; the guide and the Status
// page's CS2 card are computed from these snapshots at read time.
'use strict';

const STREAM_URL = process.env.STREAM_URL || 'http://192.168.1.6:8098';
const HLTV_API = process.env.HLTV_API_URL || 'http://hltv-api:8080';
const TZ = 'America/New_York';

async function getJson(url, signal) {
  const res = await fetch(url, { signal });
  if (res.status === 503) {
    const body = await res.json().catch(() => ({}));
    if (body.warming) throw new Error('hltv-api is warming up (first scrape of the day)');
  }
  if (!res.ok) throw new Error(`${new URL(url).host}${new URL(url).pathname}: HTTP ${res.status}`);
  return res.json();
}

function registerStreamSources(snapshots) {
  // Slot state changes by the second while something is starting — poll it fast.
  snapshots.register({
    key: 'streams:status', group: 'streams', label: 'stream-station slots',
    intervalMs: 5000, timeoutMs: 4000, staleAfterMs: 30_000,
    fetch: ({ signal }) => getJson(`${STREAM_URL}/status`, signal),
  });
  snapshots.register({
    key: 'streams:presets', group: 'streams', label: 'stream-station presets',
    intervalMs: 10 * 60_000, timeoutMs: 6000, staleAfterMs: 60 * 60_000,
    fetch: ({ signal }) => getJson(`${STREAM_URL}/presets`, signal),
  });
  // max_age=900 is hltv-api's non-blocking path: a cache hit or a stale-marked
  // last-good answer, with the scrape refreshed behind the response.
  snapshots.register({
    key: 'hltv:day', group: 'hltv', label: 'HLTV day feed',
    intervalMs: 5 * 60_000, timeoutMs: 15_000, staleAfterMs: 30 * 60_000,
    fetch: ({ signal }) => getJson(`${HLTV_API}/day?max_age=900&tz=${encodeURIComponent(TZ)}`, signal),
  });
  snapshots.register({
    key: 'hltv:vrs', group: 'hltv', label: 'Valve Regional Standings',
    intervalMs: 60 * 60_000, timeoutMs: 30_000, staleAfterMs: 24 * 3600_000,
    fetch: ({ signal }) => getJson(`${HLTV_API}/vrs`, signal),
  });
}

module.exports = { registerStreamSources, STREAM_URL };
