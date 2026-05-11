const express  = require('express');
const cors     = require('cors');
const path     = require('path');
const crypto   = require('crypto');
const Database = require('better-sqlite3');
const fs       = require('fs');

const DATA_DIR = process.env.DATA_DIR || '/data';
const PORT     = process.env.PORT || 3002;

fs.mkdirSync(DATA_DIR, { recursive: true });

const db = new Database(path.join(DATA_DIR, 'notes.db'));
db.pragma('journal_mode = WAL');
db.pragma('foreign_keys = ON');

// ── Schema ────────────────────────────────────────────────────────────────────
db.exec(`
  CREATE TABLE IF NOT EXISTS notebooks (
    id         TEXT PRIMARY KEY,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
  );

  CREATE TABLE IF NOT EXISTS pages (
    id             TEXT PRIMARY KEY,
    notebook_id    TEXT NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    title          TEXT NOT NULL,
    content        TEXT NOT NULL DEFAULT '{}',
    last_modified  TEXT NOT NULL,
    checksum       TEXT NOT NULL,
    is_sync_delta  INTEGER NOT NULL DEFAULT 0
  );

  CREATE INDEX IF NOT EXISTS idx_pages_notebook ON pages(notebook_id);
`);

// Seed a default notebook on first run
if (db.prepare('SELECT COUNT(*) as c FROM notebooks').get().c === 0) {
  const now = new Date().toISOString();
  db.prepare('INSERT INTO notebooks VALUES (?,?,?,?)').run(crypto.randomUUID(), 'My Notebook', now, now);
}

// ── Helpers ───────────────────────────────────────────────────────────────────
// SHA-256 — matches SubtleCrypto used in the browser client
function checksum(content) {
  return crypto.createHash('sha256').update(content).digest('hex');
}

function now() {
  return new Date().toISOString();
}

function isValidJson(str) {
  try { JSON.parse(str); return true; } catch { return false; }
}

// ── App ───────────────────────────────────────────────────────────────────────
const app = express();

// Allow same-origin (browser via nginx) and direct IP access (mobile HTTP fallback)
app.use(cors({
  origin: (origin, cb) => {
    // Allow requests with no origin (mobile apps, curl) and any local network origin
    if (!origin || origin.includes('rpi.lan') || origin.includes('192.168.') || origin.includes('10.') || origin.includes('localhost')) {
      cb(null, true);
    } else {
      cb(null, false);
    }
  },
  credentials: true,
}));
app.use(express.json({ limit: '10mb' }));

// Serve web UI at /notes
app.use('/notes', express.static(path.join(__dirname, '../web')));

// ── Health / ping ─────────────────────────────────────────────────────────────
app.get('/notes/api/ping', (_req, res) => res.json({ ok: true }));

// ── Notebooks ─────────────────────────────────────────────────────────────────
app.get('/notes/api/notebooks', (_req, res) => {
  res.json(db.prepare('SELECT * FROM notebooks ORDER BY title').all());
});

app.post('/notes/api/notebooks', (req, res) => {
  const { title } = req.body;
  if (!title?.trim()) return res.status(400).json({ error: 'title required' });
  const id = crypto.randomUUID();
  const ts = now();
  db.prepare('INSERT INTO notebooks VALUES (?,?,?,?)').run(id, title.trim(), ts, ts);
  res.status(201).json({ id, title: title.trim(), created_at: ts, updated_at: ts });
});

app.put('/notes/api/notebooks/:id', (req, res) => {
  const { title } = req.body;
  if (!title?.trim()) return res.status(400).json({ error: 'title required' });
  const ts   = now();
  const info = db.prepare('UPDATE notebooks SET title=?, updated_at=? WHERE id=?').run(title.trim(), ts, req.params.id);
  if (info.changes === 0) return res.status(404).json({ error: 'not found' });
  res.json({ ok: true });
});

app.delete('/notes/api/notebooks/:id', (req, res) => {
  db.prepare('DELETE FROM notebooks WHERE id=?').run(req.params.id);
  res.json({ ok: true });
});

// ── Pages ─────────────────────────────────────────────────────────────────────
app.get('/notes/api/notebooks/:id/pages', (req, res) => {
  const rows = db.prepare(
    'SELECT id, notebook_id, title, last_modified, checksum, is_sync_delta FROM pages WHERE notebook_id=? ORDER BY last_modified DESC'
  ).all(req.params.id);
  res.json(rows);
});

app.get('/notes/api/pages/:id', (req, res) => {
  const row = db.prepare('SELECT * FROM pages WHERE id=?').get(req.params.id);
  if (!row) return res.status(404).json({ error: 'not found' });
  res.json(row);
});

app.post('/notes/api/pages', (req, res) => {
  const { notebook_id, title, content = '{}' } = req.body;
  if (!notebook_id || !title?.trim()) return res.status(400).json({ error: 'notebook_id and title required' });
  if (!isValidJson(content)) return res.status(400).json({ error: 'content must be valid JSON' });
  if (!db.prepare('SELECT id FROM notebooks WHERE id=?').get(notebook_id)) {
    return res.status(404).json({ error: 'notebook not found' });
  }
  const id = crypto.randomUUID();
  const ts = now();
  const cs = checksum(content);
  db.prepare('INSERT INTO pages VALUES (?,?,?,?,?,?,0)').run(id, notebook_id, title.trim(), content, ts, cs);
  res.status(201).json({ id, notebook_id, title: title.trim(), content, last_modified: ts, checksum: cs, is_sync_delta: 0 });
});

app.put('/notes/api/pages/:id', (req, res) => {
  const { title, content } = req.body;
  const existing = db.prepare('SELECT * FROM pages WHERE id=?').get(req.params.id);
  if (!existing) return res.status(404).json({ error: 'not found' });
  if (content !== undefined && !isValidJson(content)) return res.status(400).json({ error: 'content must be valid JSON' });

  const newTitle   = title   !== undefined ? title.trim()  : existing.title;
  const newContent = content !== undefined ? content       : existing.content;
  const ts = now();
  const cs = checksum(newContent);
  db.prepare('UPDATE pages SET title=?, content=?, last_modified=?, checksum=? WHERE id=?')
    .run(newTitle, newContent, ts, cs, req.params.id);
  res.json({ ok: true, last_modified: ts, checksum: cs });
});

app.delete('/notes/api/pages/:id', (req, res) => {
  db.prepare('DELETE FROM pages WHERE id=?').run(req.params.id);
  res.json({ ok: true });
});

// ── Sync: Phase 1 — diff check ────────────────────────────────────────────────
app.post('/notes/api/sync/check', (req, res) => {
  const clientPages = req.body?.pages;
  if (!Array.isArray(clientPages)) return res.status(400).json({ error: 'pages must be an array' });

  const pull   = [];
  const push   = [];
  const seenIds = new Set();

  for (const cp of clientPages) {
    if (!cp.id) continue;
    seenIds.add(cp.id);
    const sp = db.prepare('SELECT * FROM pages WHERE id=?').get(cp.id);

    if (!sp) {
      push.push(cp.id);
    } else if (new Date(sp.last_modified) > new Date(cp.last_modified)) {
      pull.push(sp);
    } else if (sp.checksum !== (cp.checksum || '')) {
      // Client has different content (and is not older) — ask client to push
      push.push(cp.id);
    }
    // Equal timestamp + checksum = no-op
  }

  // Pages on server the client has never seen — send them
  const serverPages = db.prepare('SELECT * FROM pages').all();
  for (const sp of serverPages) {
    if (!seenIds.has(sp.id)) pull.push(sp);
  }

  res.json({ pull, push });
});

// ── Sync: Phase 2 — client pushes its newer pages ────────────────────────────
app.post('/notes/api/sync/push', (req, res) => {
  const pages = req.body?.pages;
  if (!Array.isArray(pages)) return res.status(400).json({ error: 'pages must be an array' });

  const upsert = db.prepare(`
    INSERT INTO pages (id, notebook_id, title, content, last_modified, checksum, is_sync_delta)
    VALUES (@id, @notebook_id, @title, @content, @last_modified, @checksum, 0)
    ON CONFLICT(id) DO UPDATE SET
      title         = CASE WHEN excluded.last_modified > pages.last_modified THEN excluded.title         ELSE pages.title         END,
      content       = CASE WHEN excluded.last_modified > pages.last_modified THEN excluded.content       ELSE pages.content       END,
      last_modified = CASE WHEN excluded.last_modified > pages.last_modified THEN excluded.last_modified ELSE pages.last_modified END,
      checksum      = CASE WHEN excluded.last_modified > pages.last_modified THEN excluded.checksum      ELSE pages.checksum      END
  `);

  const insertDelta = db.prepare(`
    INSERT INTO pages (id, notebook_id, title, content, last_modified, checksum, is_sync_delta)
    VALUES (?,?,?,?,?,?,1)
  `);

  const ensureNotebook = db.prepare(`
    INSERT OR IGNORE INTO notebooks (id, title, created_at, updated_at) VALUES (?,?,?,?)
  `);

  const results = [];

  // Wrap all upserts in a single transaction — all succeed or all roll back
  const runTransaction = db.transaction((pages) => {
    for (const page of pages) {
      if (!page.id || !page.notebook_id) continue;

      const content = page.content || '{}';
      if (!isValidJson(content)) continue;

      const ts = now();
      ensureNotebook.run(page.notebook_id, 'Synced Notebook', ts, ts);

      const existing = db.prepare('SELECT * FROM pages WHERE id=?').get(page.id);
      const cs = checksum(content);

      upsert.run({
        id:            page.id,
        notebook_id:   page.notebook_id,
        title:         (page.title || 'Untitled').trim(),
        content,
        last_modified: page.last_modified || ts,
        checksum:      cs,
      });

      let deltaId = null;
      // If server already had this page at an equal-or-newer timestamp with different content,
      // the upsert kept the server version — save the client's content as a delta page instead
      if (existing && new Date(existing.last_modified) >= new Date(page.last_modified) && existing.checksum !== cs) {
        deltaId = crypto.randomUUID();
        const deltaTs = now();
        insertDelta.run(deltaId, existing.notebook_id, `Synced Changes ${new Date().toLocaleString()}`, content, deltaTs, checksum(content));
      }

      results.push({ id: page.id, delta_created: deltaId });
    }
  });

  try {
    runTransaction(pages);
    res.json({ ok: true, results });
  } catch (err) {
    console.error('sync/push transaction failed:', err);
    res.status(500).json({ error: 'sync failed', detail: err.message });
  }
});

// ── Start ─────────────────────────────────────────────────────────────────────
app.listen(PORT, '0.0.0.0', () => console.log(`notes-api listening on :${PORT}`));
