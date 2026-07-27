// Serves the agentic workspace view: the manifest (inventory + portability), per-host tool
// detection (from probe.py status files), and a LIVE wiring computation so the Sync button
// reflects the real current state of the workspace files.
//
// Source of truth is the ptm4 repo on opti, bind-mounted read-only at /workspace (see
// docker-compose.yml). Wiring is file-based, so the backend can (re)compute it directly;
// tooling is host-specific and comes from homelab/agentic/status/<host>.json, which each
// workstation writes by running `python3 homelab/agentic/probe.py`.
const express = require('express');
const fs = require('fs');
const path = require('path');

const router = express.Router();

// Dispatcher on opti (same infra as controls.js) — used to materialize wiring server-side.
const DISPATCHER_URL = process.env.DISPATCHER_URL || '';
const DISPATCH_TOKEN = process.env.HL_DISPATCH_TOKEN || '';
const WIREABLE = new Set(['claude']);   // tools the "Wire it" button can materialize

const WORKSPACE = fs.existsSync('/workspace')
  ? '/workspace'
  : path.join(__dirname, '..', '..', '..', '..');          // dev: repo root from backend/routes
const AGENTIC = path.join(WORKSPACE, 'homelab', 'agentic');
const AGENTIC_REL = 'homelab/agentic';

const readJson = (p) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')); } catch (_) { return null; } };
const exists = (p) => { try { fs.accessSync(p); return true; } catch (_) { return false; } };
const readText = (p) => { try { return fs.readFileSync(p, 'utf8'); } catch (_) { return ''; } };
const check = (id, label, ok, detail) => ({ id, label, status: ok ? 'pass' : 'fail', detail: detail || '' });

function skillNames() {
  try {
    return fs.readdirSync(path.join(AGENTIC, 'skills'), { withFileTypes: true })
      .filter(d => d.isDirectory()).map(d => d.name).sort();
  } catch (_) { return []; }
}

// Live, file-based wiring checks per tool (mirrors probe.py, computed fresh each request).
function liveWiring() {
  const names = skillNames();
  const out = {};

  // Claude Code
  const claudeMd = path.join(WORKSPACE, 'CLAUDE.md');
  const mdRefs = exists(claudeMd) && readText(claudeMd).includes(AGENTIC_REL);
  const skillsDir = path.join(WORKSPACE, '.claude', 'skills');
  const discoverable = names.filter(n => exists(path.join(skillsDir, n, 'SKILL.md')));
  const settings = exists(path.join(WORKSPACE, '.claude', 'settings.local.json'));
  const cChecks = [
    check('claude_md', 'CLAUDE.md directs Claude to homelab/agentic', mdRefs,
      mdRefs ? 'present & references agentic' : (exists(claudeMd) ? 'exists but no agentic reference' : 'no CLAUDE.md')),
    check('claude_skills', '.claude/skills registers all agentic skills', names.length > 0 && discoverable.length === names.length,
      `${discoverable.length}/${names.length} discoverable`),
    check('claude_settings', '.claude settings present', settings, settings ? 'settings.local.json found' : 'none'),
  ];
  out.claude = { name: 'Claude Code', wireable: WIREABLE.has('claude'), wired: cChecks.every(c => c.status === 'pass'), checks: cChecks };

  // Codex (Phase 2 wiring)
  const agentsMd = path.join(WORKSPACE, 'AGENTS.md');
  const codexOk = exists(agentsMd) && readText(agentsMd).includes(AGENTIC_REL);
  out.codex = { name: 'Codex', wireable: WIREABLE.has('codex'), wired: codexOk,
    checks: [check('codex_agents_md', 'AGENTS.md directs Codex to homelab/agentic', codexOk, codexOk ? 'wired' : 'not wired')] };

  // Cursor (Phase 2 wiring)
  const cursorRules = path.join(WORKSPACE, '.cursor', 'rules');
  let cursorOk = false;
  try { cursorOk = fs.readdirSync(cursorRules).some(f => readText(path.join(cursorRules, f)).includes(AGENTIC_REL)); } catch (_) {}
  out.cursor = { name: 'Cursor', wireable: WIREABLE.has('cursor'), wired: cursorOk,
    checks: [check('cursor_rules', '.cursor/rules reference homelab/agentic', cursorOk, cursorOk ? 'wired' : 'not wired')] };

  return out;
}

function statusFiles() {
  const dir = path.join(AGENTIC, 'status');
  let files = [];
  try { files = fs.readdirSync(dir).filter(f => f.endsWith('.json')); } catch (_) {}
  return files.map(f => {
    const d = readJson(path.join(dir, f));
    if (d) { try { d._mtime = fs.statSync(path.join(dir, f)).mtime.toISOString(); } catch (_) {} }
    return d;
  }).filter(Boolean);
}

// GET /api/agentic — manifest + per-host tooling status + live wiring. Sync button re-GETs.
router.get('/', (req, res) => {
  const manifest = readJson(path.join(AGENTIC, 'workspace.json'));
  if (!manifest) {
    return res.status(503).json({
      ok: false, source: path.join(AGENTIC, 'workspace.json'),
      error: 'workspace.json not readable',
      hint: 'Run: python3 homelab/agentic/gen-workspace.py on opti; ensure the /workspace mount is present.',
    });
  }
  res.json({
    ok: true,
    source: WORKSPACE,
    computed_at: new Date().toISOString(),
    manifest,
    hosts: statusFiles(),
    wiring: liveWiring(),
  });
});

// POST /api/agentic/wire/:tool — materialize that tool's wiring via the opti dispatcher,
// which runs `probe.py --wire <tool>` on the workspace. Tool is whitelisted here and again
// in the dispatcher; no arbitrary input reaches a shell.
router.post('/wire/:tool', async (req, res) => {
  const tool = String(req.params.tool || '');
  if (!WIREABLE.has(tool)) return res.status(400).json({ ok: false, error: `not wireable: ${tool}` });
  if (!DISPATCHER_URL) return res.status(503).json({ ok: false, error: 'dispatcher not configured (DISPATCHER_URL)' });
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (DISPATCH_TOKEN) headers['Authorization'] = `Bearer ${DISPATCH_TOKEN}`;
    const r = await fetch(`${DISPATCHER_URL}/agentic/wire/${encodeURIComponent(tool)}`, {
      method: 'POST', headers, signal: AbortSignal.timeout(30000),
    });
    const data = await r.json().catch(() => ({}));
    res.status(r.status).json(data);
  } catch (e) {
    res.status(502).json({ ok: false, error: String(e.message || e) });
  }
});

// POST /api/agentic/proposal/:action/:id — promote or dismiss a skill/rule proposal via the
// opti dispatcher (runs propose.py). id is validated to the strict proposal slug here too.
router.post('/proposal/:action/:id', async (req, res) => {
  const { action, id } = req.params;
  if (!['promote', 'dismiss'].includes(action)) return res.status(400).json({ ok: false, error: 'bad action' });
  if (!/^(skill|rule)-[a-z0-9][a-z0-9-]*$/.test(id)) return res.status(400).json({ ok: false, error: 'bad proposal id' });
  if (!DISPATCHER_URL) return res.status(503).json({ ok: false, error: 'dispatcher not configured (DISPATCHER_URL)' });
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (DISPATCH_TOKEN) headers['Authorization'] = `Bearer ${DISPATCH_TOKEN}`;
    const r = await fetch(`${DISPATCHER_URL}/agentic/${action}/${encodeURIComponent(id)}`, {
      method: 'POST', headers, signal: AbortSignal.timeout(30000),
    });
    const data = await r.json().catch(() => ({}));
    res.status(r.status).json(data);
  } catch (e) {
    res.status(502).json({ ok: false, error: String(e.message || e) });
  }
});

module.exports = router;
