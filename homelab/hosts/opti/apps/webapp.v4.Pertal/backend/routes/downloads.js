// /api/downloads — the qBittorrent queue, and the changes you can make to it. Each change
// is a job (steps, tray, audit trail), same as every other button in Pertal. Deleting is
// risky: 428 without confirm. PERTAL_ACTIONS=dry makes the writes no-ops (dev).
//
// Torrents added here go in category "pertal", saved to /data/downloads/pertal on
// noblenumbat; media-import.sh moves each one to opti (ptm/Downloads) once complete.
'use strict';
const { qbt } = require('../sources/downloads');

const DRY = process.env.PERTAL_ACTIONS === 'dry';
const CATEGORY = 'pertal';
const SAVE_PATH = '/data/downloads/pertal';
const HASH_RE = /^[a-f0-9]{40}$/i;
const MAX_FILES = 20;

function runJob(app, spec, body) {
  const job = app.jobs.create(spec);
  (async () => {
    try { await body(job); job.finish('ok'); } catch (err) { job.finish('failed', err); }
  })();
  return job.snapshot();
}

module.exports = async function downloadRoutes(app) {
  await app.register(require('@fastify/multipart'), { limits: { fileSize: 5 * 1024 * 1024, files: MAX_FILES } });

  app.get('/', async () => {
    const q = app.snapshots.get('qbt:queue');
    const v = app.snapshots.get('vpn:gluetun');
    return {
      queue: q?.data ?? null, queue_meta: q?.meta ?? null,
      vpn: v?.data ?? null, vpn_meta: v?.meta ?? null,
      category: CATEGORY, dry: DRY,
    };
  });

  // Add torrents: multipart (.torrent files and/or a `urls` field) or JSON { urls }.
  app.post('/add', async (req, reply) => {
    const files = [];
    let urls = '';
    if (req.isMultipart()) {
      for await (const part of req.parts()) {
        if (part.type === 'file') {
          if (!/\.torrent$/i.test(part.filename)) return reply.code(400).send({ error: `${part.filename} is not a .torrent file` });
          files.push({ name: part.filename, buf: await part.toBuffer() });
        } else if (part.fieldname === 'urls') {
          urls = String(part.value || '');
        }
      }
    } else {
      urls = String(req.body?.urls || '');
    }
    const links = urls.split(/\s+/).map((s) => s.trim()).filter(Boolean);
    if (links.some((l) => !/^(magnet:\?|https?:\/\/)/i.test(l))) return reply.code(400).send({ error: 'links must be magnet: or http(s) URLs' });
    if (!files.length && !links.length) return reply.code(400).send({ error: 'add a .torrent file or a magnet link' });

    const what = [...files.map((f) => f.name), ...links.map((l) => (l.startsWith('magnet:') ? (decodeURIComponent(/dn=([^&]+)/.exec(l)?.[1] ?? 'magnet link')) : l))];
    const job = runJob(app, {
      kind: 'download.add', title: `Add ${what.length === 1 ? what[0] : `${what.length} torrents`}`,
      host: 'noblenumbat', target: 'qbittorrent', resource: 'noblenumbat:qbittorrent',
      steps: [
        { key: 'category', label: `Make sure the "${CATEGORY}" category exists` },
        { key: 'send', label: `Hand ${what.length} torrent(s) to qBittorrent`, detail: what.join(', ').slice(0, 300) },
        { key: 'verify', label: 'See them appear in the queue' },
      ],
    }, async (job) => {
      await job.step('category', async (note) => {
        if (DRY) return note('dry run: skipped');
        const cats = await qbt('/torrents/categories');
        if (cats[CATEGORY]) return note(`exists → ${cats[CATEGORY].savePath || SAVE_PATH}`);
        await qbt('/torrents/createCategory', { method: 'POST', body: new URLSearchParams({ category: CATEGORY, savePath: SAVE_PATH }) });
        note(`created → ${SAVE_PATH}`);
      });
      const before = new Set((app.snapshots.data('qbt:queue')?.torrents ?? []).map((t) => t.hash));
      await job.step('send', async (note) => {
        if (DRY) return note(`dry run: would add ${what.join(', ')}`);
        const form = new FormData();
        for (const f of files) form.append('torrents', new Blob([f.buf], { type: 'application/x-bittorrent' }), f.name);
        if (links.length) form.append('urls', links.join('\n'));
        form.append('category', CATEGORY);
        const out = await qbt('/torrents/add', { method: 'POST', body: form, timeoutMs: 20_000 });
        if (typeof out === 'string' && out.trim() !== 'Ok.') throw new Error(`qBittorrent said: ${out.trim() || 'nothing'} (duplicate or invalid torrent?)`);
        note('qBittorrent accepted');
      });
      await job.step('verify', async (note) => {
        if (DRY) return note('dry run: skipped');
        for (let i = 0; i < 8; i++) {
          const snap = await app.snapshots.refresh('qbt:queue');
          const added = (snap?.data?.torrents ?? []).filter((t) => !before.has(t.hash));
          if (added.length) return note(added.map((t) => `${t.name} (${t.state})`).join('\n'));
          await new Promise((r) => setTimeout(r, 1500));
        }
        throw new Error('not in the queue after 12s — a magnet may still be fetching metadata; check qBittorrent');
      });
    });
    return reply.code(202).send({ job });
  });

  // Pause / resume / delete one torrent.
  app.post('/:hash/:op', async (req, reply) => {
    const { hash, op } = req.params;
    if (!HASH_RE.test(hash)) return reply.code(400).send({ error: 'bad torrent hash' });
    if (!['pause', 'resume', 'delete'].includes(op)) return reply.code(404).send({ error: `unknown operation '${op}'` });
    const t = (app.snapshots.data('qbt:queue')?.torrents ?? []).find((x) => x.hash === hash);
    if (!t) return reply.code(404).send({ error: 'no such torrent in the queue' });
    const deleteFiles = req.body?.deleteFiles === true;
    if (op === 'delete' && req.body?.confirm !== true) return reply.code(428).send({ error: `deleting ${t.name} needs confirmation` });

    const label = op === 'delete' ? (deleteFiles ? 'Delete (with files)' : 'Remove') : op === 'pause' ? 'Pause' : 'Resume';
    const job = runJob(app, {
      kind: `download.${op}`, title: `${label} ${t.name}`, host: 'noblenumbat', target: t.name,
      resource: 'noblenumbat:qbittorrent', danger: op === 'delete',
      steps: [{ key: 'send', label: `${label} in qBittorrent` }, { key: 'verify', label: 'Re-read the queue' }],
    }, async (job) => {
      await job.step('send', async (note) => {
        if (DRY) return note(`dry run: would ${op} ${t.name}`);
        const body = new URLSearchParams({ hashes: hash, ...(op === 'delete' ? { deleteFiles: String(deleteFiles) } : {}) });
        await qbt(`/torrents/${op}`, { method: 'POST', body });
        note('qBittorrent accepted');
      });
      await job.step('verify', async (note) => {
        const snap = await app.snapshots.refresh('qbt:queue');
        const now = (snap?.data?.torrents ?? []).find((x) => x.hash === hash);
        note(now ? `state: ${now.state}` : 'no longer in the queue');
      });
    });
    return reply.code(202).send({ job });
  });
};
