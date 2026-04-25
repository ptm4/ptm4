import { Editor }  from 'https://esm.sh/@tiptap/core@2.11.5';
import StarterKit   from 'https://esm.sh/@tiptap/starter-kit@2.11.5';
import TaskList     from 'https://esm.sh/@tiptap/extension-task-list@2.11.5';
import TaskItem     from 'https://esm.sh/@tiptap/extension-task-item@2.11.5';
import Placeholder  from 'https://esm.sh/@tiptap/extension-placeholder@2.11.5';

// ── Config ────────────────────────────────────────────────────────────────────
// detectServer() tries these candidates in order.
// First is same-origin (browser on RPI via nginx HTTPS).
// Second is direct HTTP to notes-api (works even with self-signed cert issues on mobile).
const SERVER_CANDIDATES = [
  '',                             // same-origin (browser on RPI, proxied through nginx)
  'https://webapp.rpi.lan',       // LAN HTTPS via nginx (if cert is trusted)
  'http://192.168.1.10:3002',     // direct HTTP to notes-api (mobile fallback)
];

let serverBase = null;
let isOnline   = false;

// ── State ─────────────────────────────────────────────────────────────────────
let notebooks      = [];
let pages          = [];
let activeNotebook = null;
let activePage     = null;
let editor         = null;
let saveTimer      = null;
let pageLoading    = false;  // suppress onUpdate during page switch

// ── DOM refs ──────────────────────────────────────────────────────────────────
const notebookList    = document.getElementById('notebook-list');
const pageList        = document.getElementById('page-list');
const btnNewNotebook  = document.getElementById('btn-new-notebook');
const btnNewPage      = document.getElementById('btn-new-page');
const btnSync         = document.getElementById('btn-sync');
const syncStatus      = document.getElementById('sync-status');
const pageTitleInput  = document.getElementById('page-title-input');
const editorContent   = document.getElementById('editor-content');
const placeholder     = document.getElementById('editor-placeholder');
const sidebar         = document.getElementById('sidebar');
const btnSidebarToggle = document.getElementById('btn-sidebar-toggle');

// ── Checksum (SHA-256 via SubtleCrypto — available in all modern browsers) ───
async function computeChecksum(str) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(str));
  return Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, '0')).join('');
}

// ── API helpers ───────────────────────────────────────────────────────────────
async function api(method, path, body) {
  const base = serverBase || '';
  const res  = await fetch(`${base}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error(`${method} ${path} → ${res.status}`);
  return res.json();
}

const GET    = (p)    => api('GET',    p);
const POST   = (p, b) => api('POST',   p, b);
const PUT    = (p, b) => api('PUT',    p, b);
const DELETE = (p)    => api('DELETE', p);

// ── Local storage ─────────────────────────────────────────────────────────────
const LOCAL_KEY = 'notes_local';

function localLoad() {
  try { return JSON.parse(localStorage.getItem(LOCAL_KEY) || '{}'); } catch { return {}; }
}

function localSave(data) {
  try {
    localStorage.setItem(LOCAL_KEY, JSON.stringify(data));
  } catch (e) {
    if (e.name === 'QuotaExceededError') {
      console.warn('localStorage full — oldest sync deltas will be pruned');
      pruneLocalDeltas();
    }
  }
}

function pruneLocalDeltas() {
  const d = localLoad();
  const pages = Object.values(d.pages || {});
  const deltas = pages.filter(p => p.is_sync_delta).sort((a, b) =>
    new Date(a.last_modified) - new Date(b.last_modified));
  for (const delta of deltas.slice(0, 10)) {
    delete d.pages[delta.id];
  }
  try { localStorage.setItem(LOCAL_KEY, JSON.stringify(d)); } catch {}
}

function getLocalNotebooks() {
  return Object.values(localLoad().notebooks || {});
}
function getLocalPages(notebookId) {
  return Object.values(localLoad().pages || {})
    .filter(p => p.notebook_id === notebookId)
    .sort((a, b) => new Date(b.last_modified) - new Date(a.last_modified));
}
function upsertLocalPage(page) {
  const d = localLoad();
  d.pages = d.pages || {};
  const existing = d.pages[page.id];
  // Only overwrite if incoming is newer (or we have nothing)
  if (!existing || new Date(page.last_modified) >= new Date(existing.last_modified)) {
    d.pages[page.id] = page;
    localSave(d);
  }
}
function upsertLocalNotebook(nb) {
  const d = localLoad();
  d.notebooks = d.notebooks || {};
  d.notebooks[nb.id] = nb;
  localSave(d);
}

// ── Network detection ─────────────────────────────────────────────────────────
async function detectServer() {
  for (const base of SERVER_CANDIDATES) {
    try {
      const res = await fetch(`${base}/notes/api/ping`, {
        signal: AbortSignal.timeout(1800),
      });
      if (res.ok) { serverBase = base; return true; }
    } catch {}
  }
  serverBase = null;
  return false;
}

async function updateOnlineStatus() {
  isOnline = await detectServer();
  if (isOnline) {
    syncStatus.textContent = '● online';
    syncStatus.className   = 'online';
    btnSync.disabled = false;
  } else {
    syncStatus.textContent = '● offline';
    syncStatus.className   = '';
    btnSync.disabled = true;
  }
}

// ── Editor ────────────────────────────────────────────────────────────────────
function initEditor() {
  editor = new Editor({
    element: editorContent,
    extensions: [
      StarterKit,
      TaskList.configure({}),
      TaskItem.configure({ nested: true }),
      Placeholder.configure({ placeholder: 'Start writing…' }),
    ],
    content: '',
    editable: false,
    onUpdate: () => {
      if (!pageLoading) scheduleSave();
    },
    onTransaction: () => updateToolbar(),
  });
}

function updateToolbar() {
  if (!editor) return;
  document.querySelectorAll('#editor-toolbar button[data-cmd]').forEach(btn => {
    const cmd = btn.dataset.cmd;
    const active =
      cmd === 'bold'         ? editor.isActive('bold') :
      cmd === 'italic'       ? editor.isActive('italic') :
      cmd === 'strike'       ? editor.isActive('strike') :
      cmd === 'h1'           ? editor.isActive('heading', { level: 1 }) :
      cmd === 'h2'           ? editor.isActive('heading', { level: 2 }) :
      cmd === 'h3'           ? editor.isActive('heading', { level: 3 }) :
      cmd === 'bulletList'   ? editor.isActive('bulletList') :
      cmd === 'orderedList'  ? editor.isActive('orderedList') :
      cmd === 'taskList'     ? editor.isActive('taskList') :
      cmd === 'blockquote'   ? editor.isActive('blockquote') :
      cmd === 'codeBlock'    ? editor.isActive('codeBlock') : false;
    btn.classList.toggle('active', active);
  });
}

document.querySelectorAll('#editor-toolbar button[data-cmd]').forEach(btn => {
  btn.addEventListener('mousedown', (e) => {
    e.preventDefault();
    if (!editor) return;
    const cmd = btn.dataset.cmd;
    switch (cmd) {
      case 'bold':           editor.chain().focus().toggleBold().run();                    break;
      case 'italic':         editor.chain().focus().toggleItalic().run();                  break;
      case 'strike':         editor.chain().focus().toggleStrike().run();                  break;
      case 'h1':             editor.chain().focus().toggleHeading({ level: 1 }).run();     break;
      case 'h2':             editor.chain().focus().toggleHeading({ level: 2 }).run();     break;
      case 'h3':             editor.chain().focus().toggleHeading({ level: 3 }).run();     break;
      case 'bulletList':     editor.chain().focus().toggleBulletList().run();              break;
      case 'orderedList':    editor.chain().focus().toggleOrderedList().run();             break;
      case 'taskList':       editor.chain().focus().toggleTaskList().run();                break;
      case 'blockquote':     editor.chain().focus().toggleBlockquote().run();              break;
      case 'codeBlock':      editor.chain().focus().toggleCodeBlock().run();               break;
      case 'horizontalRule': editor.chain().focus().setHorizontalRule().run();             break;
      case 'undo':           editor.chain().focus().undo().run();                          break;
      case 'redo':           editor.chain().focus().redo().run();                          break;
    }
  });
});

// ── Save ──────────────────────────────────────────────────────────────────────
function scheduleSave() {
  if (pageLoading || !activePage) return;
  clearTimeout(saveTimer);
  // Capture current page reference at schedule time — avoids stale closure bug
  const pageAtSchedule = activePage;
  saveTimer = setTimeout(() => savePage(pageAtSchedule), 1200);
}

async function savePage(page) {
  if (!page) return;
  const content = JSON.stringify(editor.getJSON());
  const title   = pageTitleInput.value.trim() || 'Untitled';
  const cs      = await computeChecksum(content);
  const now     = new Date().toISOString();

  page.content       = content;
  page.title         = title;
  page.last_modified = now;
  page.checksum      = cs;
  upsertLocalPage(page);

  // Update sidebar label
  const li = document.querySelector(`#page-list li[data-id="${page.id}"]`);
  if (li) li.querySelector('span.title').textContent = title;

  if (isOnline) {
    try {
      const resp = await PUT(`/notes/api/pages/${page.id}`, { title, content });
      // Adopt server's checksum and timestamp
      if (resp.checksum) page.checksum = resp.checksum;
      if (resp.last_modified) page.last_modified = resp.last_modified;
      upsertLocalPage(page);
    } catch (err) {
      console.warn('save to server failed, will sync later:', err);
    }
  }
}

// ── Render ────────────────────────────────────────────────────────────────────
function renderNotebooks() {
  notebookList.innerHTML = '';
  notebooks.forEach(nb => {
    const li = document.createElement('li');
    li.dataset.id = nb.id;
    li.innerHTML  = `<span>📓</span><span class="title">${esc(nb.title)}</span>`;
    if (activeNotebook?.id === nb.id) li.classList.add('active');
    li.addEventListener('click', () => selectNotebook(nb));
    notebookList.appendChild(li);
  });
}

function renderPages() {
  pageList.innerHTML = '';
  pages.forEach(pg => {
    const li    = document.createElement('li');
    li.dataset.id = pg.id;
    const badge = pg.is_sync_delta ? '<span class="sync-badge">sync</span>' : '';
    li.innerHTML  = `<span class="title">${esc(pg.title)}</span>${badge}`;
    if (activePage?.id === pg.id) li.classList.add('active');
    li.addEventListener('click', () => selectPage(pg));
    pageList.appendChild(li);
  });
}

function showEditor(show) {
  editorContent.style.display                                         = show ? '' : 'none';
  document.getElementById('page-title-wrap').style.display           = show ? '' : 'none';
  document.getElementById('editor-toolbar').style.display            = show ? '' : 'none';
  placeholder.classList.toggle('hidden', show);
}

// ── Select ────────────────────────────────────────────────────────────────────
async function selectNotebook(nb) {
  // Flush any pending save for current page before switching
  clearTimeout(saveTimer);
  if (activePage) await savePage(activePage);

  activeNotebook = nb;
  activePage     = null;
  document.getElementById('pages-label').textContent = nb.title.toUpperCase();
  btnNewPage.disabled = false;
  renderNotebooks();
  showEditor(false);

  if (isOnline) {
    try {
      const serverPages = await GET(`/notes/api/notebooks/${nb.id}/pages`);
      serverPages.forEach(upsertLocalPage);
    } catch {}
  }
  pages = getLocalPages(nb.id);
  renderPages();
}

async function selectPage(pg) {
  if (activePage?.id === pg.id) return;

  // Flush pending save for previous page
  clearTimeout(saveTimer);
  if (activePage) await savePage(activePage);

  activePage = pg;
  renderPages();
  showEditor(true);

  pageTitleInput.disabled = false;
  pageTitleInput.value    = pg.title;

  // Load full content — check local first, then server
  let content = pg.content;
  if (isOnline && (!content || content === '{}')) {
    try {
      const full = await GET(`/notes/api/pages/${pg.id}`);
      upsertLocalPage(full);
      content = full.content;
    } catch {}
  }

  pageLoading = true;
  try {
    editor.commands.setContent(content ? JSON.parse(content) : '');
  } catch {
    editor.commands.setContent('');
  }
  editor.setEditable(true);
  editor.commands.focus();
  // Defer clearing flag so the setContent update events fully settle
  requestAnimationFrame(() => { pageLoading = false; });
}

// ── Notebook CRUD ─────────────────────────────────────────────────────────────
btnNewNotebook.addEventListener('click', async () => {
  const title = prompt('Notebook name:');
  if (!title?.trim()) return;

  if (isOnline) {
    try {
      const nb = await POST('/notes/api/notebooks', { title });
      upsertLocalNotebook(nb);
      notebooks.push(nb);
      renderNotebooks();
      selectNotebook(nb);
      return;
    } catch {}
  }
  const nb = {
    id: crypto.randomUUID(), title: title.trim(),
    created_at: new Date().toISOString(), updated_at: new Date().toISOString(),
  };
  upsertLocalNotebook(nb);
  notebooks.push(nb);
  renderNotebooks();
  selectNotebook(nb);
});

// ── Page CRUD ─────────────────────────────────────────────────────────────────
btnNewPage.addEventListener('click', async () => {
  if (!activeNotebook) return;
  const title = prompt('Page title:');
  if (!title?.trim()) return;

  const content = JSON.stringify({ type: 'doc', content: [] });
  const now     = new Date().toISOString();

  if (isOnline) {
    try {
      const pg = await POST('/notes/api/pages', { notebook_id: activeNotebook.id, title, content });
      upsertLocalPage(pg);
      pages.unshift(pg);
      renderPages();
      selectPage(pg);
      return;
    } catch {}
  }
  // Offline: create locally — checksum will be computed on first save
  const cs = await computeChecksum(content);
  const pg = {
    id: crypto.randomUUID(), notebook_id: activeNotebook.id,
    title: title.trim(), content, last_modified: now,
    checksum: cs, is_sync_delta: 0,
  };
  upsertLocalPage(pg);
  pages.unshift(pg);
  renderPages();
  selectPage(pg);
});

pageTitleInput.addEventListener('input', () => scheduleSave());

// ── Sync ──────────────────────────────────────────────────────────────────────
btnSync.addEventListener('click', runSync);

async function runSync() {
  if (!isOnline) return;

  // Flush any unsaved changes first
  clearTimeout(saveTimer);
  if (activePage) await savePage(activePage);

  syncStatus.textContent = '● syncing…';
  syncStatus.className   = 'syncing';
  btnSync.disabled       = true;

  try {
    const local        = localLoad();
    const allLocalPages = Object.values(local.pages || {});

    // Phase 1 — tell server what we have
    const { pull, push: pushIds } = await POST('/notes/api/sync/check', {
      pages: allLocalPages.map(p => ({
        id:            p.id,
        last_modified: p.last_modified,
        checksum:      p.checksum || '',
        notebook_id:   p.notebook_id,
      })),
    });

    // Pull server pages — upsertLocalPage already guards against overwriting newer local
    for (const sp of pull) {
      upsertLocalPage(sp);
    }

    // Phase 2 — push our newer pages
    const pagesToPush = allLocalPages.filter(p => pushIds.includes(p.id));
    if (pagesToPush.length > 0) {
      await POST('/notes/api/sync/push', { pages: pagesToPush });
    }

    // Persist last sync time
    const ts = new Date().toLocaleTimeString();
    localStorage.setItem('notes_last_sync', ts);

    // Refresh current notebook view
    if (activeNotebook) await selectNotebook(activeNotebook);

    syncStatus.textContent = `● synced ${ts}`;
    syncStatus.className   = 'online';
  } catch (err) {
    console.error('sync error:', err);
    syncStatus.textContent = '● sync error';
    syncStatus.className   = 'error';
  } finally {
    btnSync.disabled = false;
  }
}

// ── Sidebar toggle ────────────────────────────────────────────────────────────
btnSidebarToggle.addEventListener('click', () => sidebar.classList.toggle('collapsed'));

// Close sidebar on mobile when clicking editor area
editorContent.addEventListener('click', () => {
  if (window.innerWidth <= 600) sidebar.classList.add('collapsed');
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function esc(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  initEditor();
  showEditor(false);

  // Restore last sync label
  const lastSync = localStorage.getItem('notes_last_sync');
  if (lastSync) syncStatus.textContent = `● last sync ${lastSync}`;

  await updateOnlineStatus();

  if (isOnline) {
    try {
      notebooks = await GET('/notes/api/notebooks');
      notebooks.forEach(upsertLocalNotebook);
    } catch {
      notebooks = getLocalNotebooks();
    }
  } else {
    notebooks = getLocalNotebooks();
  }

  renderNotebooks();
  if (notebooks.length > 0) selectNotebook(notebooks[0]);

  // Recheck connectivity every 30s; auto-sync on reconnect
  let checkCount = 0;
  setInterval(async () => {
    checkCount++;
    const wasOnline = isOnline;
    await updateOnlineStatus();
    // Auto-sync on reconnect, or every 5th check (~2.5 min) if already online
    if ((!wasOnline && isOnline) || (isOnline && checkCount % 5 === 0)) {
      runSync();
    }
  }, 30_000);
}

init();
