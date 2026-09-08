// Atomic JSON store for the v2 UI state (boards, settings, acks) under
// ARCH_DATA_DIR/ui — the container's one writable mount. Same tmp+rename
// discipline the vitals snapshots and architecture fragments use: a crashed or
// racing write can never leave a half-written board behind.
const fs = require('fs');
const path = require('path');
const { ARCH_DATA_DIR } = require('./paths');

const UI_DIR = path.join(ARCH_DATA_DIR, 'ui');
const BOARDS_DIR = path.join(UI_DIR, 'boards');
const WALLPAPER_DIR = path.join(UI_DIR, 'wallpapers');

function ensureDirs() {
  fs.mkdirSync(BOARDS_DIR, { recursive: true });
  fs.mkdirSync(WALLPAPER_DIR, { recursive: true });
}

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, 'utf8')); } catch (_) { return null; }
}

function writeJsonAtomic(file, data) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, file);
}

// Slugs are filenames — never trust one that isn't this shape.
const SLUG_RE = /^[a-z0-9][a-z0-9-]{0,63}$/;
const isSlug = (s) => typeof s === 'string' && SLUG_RE.test(s);

const boardPath = (slug) => path.join(BOARDS_DIR, `${slug}.json`);

function listBoardSlugs() {
  try {
    return fs.readdirSync(BOARDS_DIR)
      .filter((f) => f.endsWith('.json'))
      .map((f) => f.replace(/\.json$/, ''))
      .filter(isSlug)
      .sort();
  } catch (_) {
    return [];
  }
}

const readBoard = (slug) => readJson(boardPath(slug));
const writeBoard = (slug, doc) => writeJsonAtomic(boardPath(slug), doc);

function deleteBoard(slug) {
  try { fs.unlinkSync(boardPath(slug)); return true; } catch (_) { return false; }
}

const SETTINGS_PATH = path.join(UI_DIR, 'settings.json');
const readSettings = () => readJson(SETTINGS_PATH);
const writeSettings = (doc) => writeJsonAtomic(SETTINGS_PATH, doc);

module.exports = {
  UI_DIR, BOARDS_DIR, WALLPAPER_DIR, SETTINGS_PATH,
  ensureDirs, readJson, writeJsonAtomic, isSlug,
  listBoardSlugs, readBoard, writeBoard, deleteBoard,
  readSettings, writeSettings,
};
