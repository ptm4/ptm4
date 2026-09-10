// /api/ui/* — the v2 board engine's persistence: boards (layout + widgets),
// global settings, and uploaded wallpapers. State lives under ARCH_DATA_DIR/ui,
// written atomically (lib/store.js).
//
// Unlike the ported routes, these are new with no legacy client, so they carry
// full request schemas AND response schemas — the strictness is safe here.
//
// Concurrency: every board write carries the `rev` the client last read. A stale
// rev returns 409 with the current document, so two open browsers can't silently
// clobber each other's layout.
const fs = require('fs');
const path = require('path');
const store = require('../lib/store');
const { PRESETS, PROTECTED, blankBoard } = require('../lib/board-presets');

const MAX_WALLPAPER_BYTES = 8 * 1024 * 1024;

// Bundled defaults ship with the frontend build; uploads live in the volume.
// A wallpaper ships ON by default: translucent cards over a flat canvas just read
// as flat cards — the glass only becomes glass when there is something behind it.
const DEFAULT_SETTINGS = {
  wallpaper: 'graphite.svg',
  glass: { opacity: 0.62, blur: 18, dim: 0.28 },
  reduce_glass: false,
  default_board: 'home',
};

function loadBoard(slug) {
  let doc = store.readBoard(slug);
  if (!doc && PRESETS[slug]) {
    // First boot, or the file was lost — reseed the protected board from its preset.
    doc = { ...PRESETS[slug], rev: 1, updated_at: new Date().toISOString() };
    try { store.ensureDirs(); store.writeBoard(slug, doc); } catch (_) { /* read-only fs: serve it anyway */ }
  }
  return doc;
}

// Magic-byte sniff — never trust the declared content-type or filename extension.
function sniffImage(buf) {
  if (buf.length > 12 && buf.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return 'png';
  if (buf.length > 3 && buf[0] === 0xff && buf[1] === 0xd8 && buf[2] === 0xff) return 'jpg';
  if (buf.length > 12 && buf.subarray(0, 4).toString('ascii') === 'RIFF' && buf.subarray(8, 12).toString('ascii') === 'WEBP') return 'webp';
  return null;
}

const boardSummarySchema = {
  type: 'object',
  properties: {
    slug: { type: 'string' },
    name: { type: 'string' },
    protected: { type: 'boolean' },
    widgets: { type: 'integer' },
    updated_at: { type: ['string', 'null'] },
  },
};

module.exports = async function uiRoutes(app) {
  // ── boards ────────────────────────────────────────────────────────────────
  app.get('/boards', {
    schema: { response: { 200: { type: 'object', properties: { boards: { type: 'array', items: boardSummarySchema } } } } },
  }, async () => {
    const slugs = new Set([...PROTECTED, ...store.listBoardSlugs()]);
    const boards = [...slugs].map((slug) => {
      const doc = loadBoard(slug) || {};
      return {
        slug,
        name: doc.name || slug,
        protected: PROTECTED.includes(slug),
        widgets: (doc.widgets || []).length,
        updated_at: doc.updated_at || null,
      };
    });
    // Protected boards first (home, dashboard), then user boards alphabetically.
    boards.sort((a, b) => Number(b.protected) - Number(a.protected) || a.slug.localeCompare(b.slug));
    return { boards };
  });

  app.post('/boards', {
    schema: {
      body: {
        type: 'object',
        required: ['name'],
        properties: { name: { type: 'string', minLength: 1, maxLength: 40 } },
      },
    },
  }, async (req, reply) => {
    const name = req.body.name.trim();
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40);
    if (!store.isSlug(slug)) {
      return reply.code(400).send({ error: 'name must contain at least one letter or digit' });
    }
    if (store.readBoard(slug) || PRESETS[slug]) {
      return reply.code(409).send({ error: `a board named '${slug}' already exists` });
    }
    const doc = { ...blankBoard(slug, name), rev: 1, updated_at: new Date().toISOString() };
    store.ensureDirs();
    store.writeBoard(slug, doc);
    return doc;
  });

  app.get('/boards/:slug', async (req, reply) => {
    if (!store.isSlug(req.params.slug)) return reply.code(400).send({ error: 'bad board slug' });
    const doc = loadBoard(req.params.slug);
    if (!doc) return reply.code(404).send({ error: `no board '${req.params.slug}'` });
    return doc;
  });

  app.put('/boards/:slug', {
    schema: {
      body: {
        type: 'object',
        required: ['rev', 'widgets', 'layouts'],
        properties: {
          rev: { type: 'integer', minimum: 0 },
          name: { type: 'string', minLength: 1, maxLength: 40 },
          wallpaper: { type: ['string', 'null'], maxLength: 200 },
          glass: {
            type: ['object', 'null'],
            properties: {
              opacity: { type: 'number', minimum: 0, maximum: 1 },
              blur: { type: 'number', minimum: 0, maximum: 40 },
              dim: { type: 'number', minimum: 0, maximum: 1 },
            },
          },
          widgets: {
            type: 'array',
            maxItems: 120,
            items: {
              type: 'object',
              required: ['id', 'type'],
              properties: {
                id: { type: 'string', minLength: 1, maxLength: 64 },
                type: { type: 'string', minLength: 1, maxLength: 40 },
                options: { type: 'object', additionalProperties: true },
              },
            },
          },
          layouts: {
            type: 'object',
            additionalProperties: {
              type: 'array',
              maxItems: 120,
              items: {
                type: 'object',
                required: ['i', 'x', 'y', 'w', 'h'],
                properties: {
                  i: { type: 'string' },
                  x: { type: 'integer', minimum: 0 },
                  y: { type: 'integer', minimum: 0 },
                  w: { type: 'integer', minimum: 1 },
                  h: { type: 'integer', minimum: 1 },
                },
              },
            },
          },
        },
      },
    },
  }, async (req, reply) => {
    const slug = req.params.slug;
    if (!store.isSlug(slug)) return reply.code(400).send({ error: 'bad board slug' });

    const current = loadBoard(slug);
    if (!current) return reply.code(404).send({ error: `no board '${slug}'` });

    if (req.body.rev !== (current.rev ?? 1)) {
      return reply.code(409).send({
        error: 'this board changed in another tab or browser',
        current,
      });
    }

    const doc = {
      ...current,
      name: req.body.name ?? current.name,
      wallpaper: req.body.wallpaper !== undefined ? req.body.wallpaper : current.wallpaper,
      glass: req.body.glass !== undefined ? req.body.glass : current.glass,
      widgets: req.body.widgets,
      layouts: req.body.layouts,
      protected: PROTECTED.includes(slug),
      rev: (current.rev ?? 1) + 1,
      updated_at: new Date().toISOString(),
    };
    store.ensureDirs();
    store.writeBoard(slug, doc);
    return doc;
  });

  app.delete('/boards/:slug', async (req, reply) => {
    const slug = req.params.slug;
    if (!store.isSlug(slug)) return reply.code(400).send({ error: 'bad board slug' });
    if (PROTECTED.includes(slug)) {
      return reply.code(400).send({ error: `'${slug}' is a built-in board and cannot be deleted` });
    }
    if (!store.readBoard(slug)) return reply.code(404).send({ error: `no board '${slug}'` });
    store.deleteBoard(slug);
    return { ok: true, slug };
  });

  // ── settings ──────────────────────────────────────────────────────────────
  app.get('/settings', async () => ({ ...DEFAULT_SETTINGS, ...(store.readSettings() || {}) }));

  app.put('/settings', {
    schema: {
      body: {
        type: 'object',
        properties: {
          wallpaper: { type: ['string', 'null'], maxLength: 200 },
          glass: {
            type: 'object',
            properties: {
              opacity: { type: 'number', minimum: 0, maximum: 1 },
              blur: { type: 'number', minimum: 0, maximum: 40 },
              dim: { type: 'number', minimum: 0, maximum: 1 },
            },
          },
          reduce_glass: { type: 'boolean' },
          default_board: { type: 'string', maxLength: 64 },
        },
      },
    },
  }, async (req) => {
    const merged = { ...DEFAULT_SETTINGS, ...(store.readSettings() || {}), ...req.body };
    store.ensureDirs();
    store.writeSettings(merged);
    return merged;
  });

  // ── wallpapers ────────────────────────────────────────────────────────────
  // `defaults` are bundled with the frontend build (served from /wallpapers/);
  // `user` are uploads in the volume (served from /media/wallpapers/).
  app.get('/wallpapers', async () => {
    let user = [];
    try {
      user = fs.readdirSync(store.WALLPAPER_DIR).filter((f) => /\.(png|jpg|webp)$/.test(f)).sort();
    } catch (_) { /* nothing uploaded yet */ }
    return { user, dir: store.WALLPAPER_DIR };
  });

  app.post('/wallpapers', async (req, reply) => {
    if (!req.isMultipart()) return reply.code(400).send({ error: 'expected a multipart upload' });
    const file = await req.file({ limits: { fileSize: MAX_WALLPAPER_BYTES, files: 1 } });
    if (!file) return reply.code(400).send({ error: 'no file in the upload' });

    const buf = await file.toBuffer().catch(() => null);
    if (!buf) return reply.code(413).send({ error: 'file too large (8MB max)' });

    const kind = sniffImage(buf);
    if (!kind) return reply.code(400).send({ error: 'not a PNG, JPEG or WebP image' });

    // The stored name is derived, never the client's — no path ever comes from input.
    const base = (file.filename || 'wallpaper').replace(/\.[^.]*$/, '')
      .toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'wallpaper';
    const name = `${base}-${Date.now().toString(36)}.${kind}`;

    store.ensureDirs();
    const dest = path.join(store.WALLPAPER_DIR, name);
    const tmp = `${dest}.tmp`;
    fs.writeFileSync(tmp, buf);
    fs.renameSync(tmp, dest);
    return { ok: true, file: name, url: `/media/wallpapers/${name}` };
  });

  app.delete('/wallpapers/:file', async (req, reply) => {
    const file = req.params.file;
    if (!/^[a-z0-9][a-z0-9.-]{0,63}\.(png|jpg|webp)$/.test(file)) {
      return reply.code(400).send({ error: 'bad wallpaper name' });
    }
    try {
      fs.unlinkSync(path.join(store.WALLPAPER_DIR, file));
      return { ok: true, file };
    } catch (_) {
      return reply.code(404).send({ error: 'no such wallpaper' });
    }
  });
};
