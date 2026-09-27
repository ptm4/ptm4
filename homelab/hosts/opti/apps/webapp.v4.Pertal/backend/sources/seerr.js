// Seerr (media requests) on opti. One snapshot: the latest requests with their titles,
// plus the counts. Seerr's request list carries TMDB ids but no titles, so titles and
// posters are looked up once per id and cached for the life of the process.
'use strict';

const SEERR_URL = process.env.SEERR_URL || 'http://seerr:5055';
const API_KEY = process.env.SEERR_API_KEY || '';

async function seerr(path, { method = 'GET', body, signal, timeoutMs = 8000 } = {}) {
  if (!API_KEY) throw new Error('SEERR_API_KEY is not set — finish Seerr setup and add its API key to .env on opti');
  const sig = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
  const res = await fetch(`${SEERR_URL}/api/v1${path}`, {
    method, signal: sig,
    headers: { 'X-Api-Key': API_KEY, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  if (!res.ok) throw new Error(`Seerr ${path}: HTTP ${res.status}${text ? ` — ${text.slice(0, 120)}` : ''}`);
  return text ? JSON.parse(text) : null;
}

const REQUEST_STATUS = { 1: 'pending', 2: 'approved', 3: 'declined', 4: 'failed', 5: 'completed' };
const MEDIA_STATUS = { 1: 'unknown', 2: 'pending', 3: 'processing', 4: 'partly available', 5: 'available', 6: 'blocklisted', 7: 'deleted' };

function registerSeerrSource(snapshots) {
  const titles = new Map(); // "movie:123" -> { title, year, poster }
  snapshots.register({
    key: 'seerr:requests', group: 'requests', label: 'Seerr requests',
    intervalMs: 60_000, timeoutMs: 20_000, staleAfterMs: 5 * 60_000,
    fetch: async ({ signal }) => {
      const [list, count] = await Promise.all([
        seerr('/request?take=40&skip=0&sort=added&filter=all', { signal }),
        seerr('/request/count', { signal }),
      ]);
      const rows = list?.results ?? [];
      for (const r of rows) {
        const type = r.media?.mediaType ?? r.type;
        const id = r.media?.tmdbId;
        const key = `${type}:${id}`;
        if (!id || titles.has(key)) continue;
        try {
          const d = await seerr(`/${type === 'tv' ? 'tv' : 'movie'}/${id}`, { signal });
          titles.set(key, {
            title: d.title ?? d.name ?? `TMDB ${id}`,
            year: String(d.releaseDate ?? d.firstAirDate ?? '').slice(0, 4) || null,
            poster: d.posterPath ? `https://image.tmdb.org/t/p/w154${d.posterPath}` : null,
          });
        } catch (_) { titles.set(key, { title: `TMDB ${id}`, year: null, poster: null }); }
      }
      return {
        counts: count ?? {},
        requests: rows.map((r) => {
          const type = r.media?.mediaType ?? r.type;
          const meta = titles.get(`${type}:${r.media?.tmdbId}`) ?? {};
          return {
            id: r.id, type, tmdb_id: r.media?.tmdbId ?? null, ...meta,
            status: REQUEST_STATUS[r.status] ?? String(r.status),
            media_status: MEDIA_STATUS[r.media?.status] ?? 'unknown',
            requested_by: r.requestedBy?.displayName ?? r.requestedBy?.username ?? 'someone',
            created_at: r.createdAt, seasons: (r.seasons || []).map((s) => s.seasonNumber),
          };
        }),
      };
    },
  });
}

module.exports = { registerSeerrSource, seerr, SEERR_URL };
