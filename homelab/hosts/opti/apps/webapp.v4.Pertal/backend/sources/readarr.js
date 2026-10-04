// Readarr (Bookshelf fork) on noblenumbat — the book side of the Requests page. Seerr only
// does movies and TV, so books are requested by adding an author in Readarr; this snapshot
// lists every monitored book with where it is: wanted, downloading, or in the library.
'use strict';

const READARR_URL = process.env.READARR_URL || 'http://192.168.1.6:8788';
const API_KEY = process.env.READARR_API_KEY || '';

async function readarr(path, { signal, timeoutMs = 10_000 } = {}) {
  if (!API_KEY) throw new Error('READARR_API_KEY is not set — add Readarr\'s API key to .env on opti');
  const sig = signal ? AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]) : AbortSignal.timeout(timeoutMs);
  const res = await fetch(`${READARR_URL}/api/v1${path}`, { headers: { 'X-Api-Key': API_KEY }, signal: sig });
  if (!res.ok) throw new Error(`Readarr ${path}: HTTP ${res.status}`);
  return res.json();
}

// Order within a series ("The Witcher #3") so the list reads like the shelf.
function seriesPosition(title) {
  const m = /#\s*([\d.]+)/.exec(title ?? '');
  return m ? Number(m[1]) : Number.MAX_SAFE_INTEGER;
}

function registerReadarrSource(snapshots) {
  snapshots.register({
    key: 'readarr:books', group: 'requests', label: 'Readarr books',
    intervalMs: 60_000, timeoutMs: 25_000, staleAfterMs: 5 * 60_000,
    fetch: async ({ signal }) => {
      const [books, queue] = await Promise.all([
        readarr('/book', { signal }),
        readarr('/queue?pageSize=100', { signal }),
      ]);
      const queued = new Map((queue?.records ?? []).map((q) => [q.bookId, q]));
      const rows = (books ?? []).filter((b) => b.monitored).map((b) => {
        const files = b.statistics?.bookFileCount ?? 0;
        const q = queued.get(b.id);
        const status = files > 0 ? 'available' : q ? 'downloading' : 'wanted';
        const pct = q && q.size ? Math.round((1 - q.sizeleft / q.size) * 100) : null;
        return {
          id: b.id, title: b.title, author: b.author?.authorName ?? null,
          series: b.seriesTitle || null, position: seriesPosition(b.seriesTitle),
          year: b.releaseDate ? String(b.releaseDate).slice(0, 4) : null,
          status, progress: status === 'downloading' ? pct : null,
        };
      });
      rows.sort((a, b) => (a.author ?? '').localeCompare(b.author ?? '') || a.position - b.position || a.title.localeCompare(b.title));
      const counts = { wanted: 0, downloading: 0, available: 0 };
      for (const r of rows) counts[r.status] += 1;
      return { counts, books: rows };
    },
  });
}

module.exports = { registerReadarrSource, readarr, READARR_URL };
