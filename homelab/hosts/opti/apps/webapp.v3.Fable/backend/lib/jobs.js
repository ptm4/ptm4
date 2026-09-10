// Jobs — stepped execution and a permanent audit trail for every action the webapp
// can take against the homelab.
//
// WHY THIS EXISTS. Before this, pressing "Reboot opti" fired one POST and produced one
// toast. If the toast said "failed", you learned nothing about *where* it failed: was
// the agent unreachable, did it refuse, did it accept and the box never came back? And
// once the toast faded there was no record that you had pressed the button at all.
// Peter's words: the actions are "such low feedback". This module is the answer.
//
// The model is deliberately small:
//
//   A JOB is one thing a person asked for ("reboot opti"). It has an id, a kind, a
//   target, a status, and an ordered list of STEPS. A step is one externally
//   observable thing the job does — check the agent answers, send the request, wait
//   for the host to go away, wait for it to come back. Steps are DECLARED UP FRONT,
//   before any of them runs, so the UI can show you the whole plan the moment you
//   confirm, with everything still pending. You see what is about to happen, then
//   watch it happen. That is where the peace of mind comes from — not from more
//   detail after the fact, but from knowing the shape of it before it starts.
//
// Every transition emits on the event bus, so an open browser sees steps tick over
// live rather than polling. Every finished job is appended to a monthly JSONL file
// that nothing ever rewrites, so "what did I run last Tuesday, and what did it say?"
// has an answer months later.
//
// WHAT THIS IS NOT. It is not a queue, a scheduler, or a retry engine. Jobs run
// immediately, in-process, one HTTP request each. If the backend restarts mid-job the
// job is lost from memory and its audit line says `interrupted` — which is honest, and
// far better than a fake "completed" or a job that resumes something the operator has
// stopped watching.
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { ARCH_DATA_DIR } = require('./paths');

const AUDIT_DIR = path.join(ARCH_DATA_DIR, 'audit');

// Jobs kept addressable in memory after finishing, so the drawer can still be opened
// on the thing you just ran. The durable copy is the JSONL; this is only the tail.
const MAX_RESIDENT = 200;

/** @typedef {'pending'|'running'|'ok'|'failed'|'skipped'} StepStatus */

const nowIso = () => new Date().toISOString();

function auditPath(d = new Date()) {
  const month = `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
  return path.join(AUDIT_DIR, `${month}.jsonl`);
}

// Append-only, one JSON object per line, fsync left to the OS. A dropped audit line
// must never take a real action down with it, so every failure here is swallowed after
// being logged — the action the operator asked for is more important than the record
// of it, and a record that can abort the thing it records is worse than no record.
function appendAudit(app, entry) {
  try {
    fs.mkdirSync(AUDIT_DIR, { recursive: true });
    fs.appendFileSync(auditPath(), `${JSON.stringify(entry)}\n`, 'utf8');
  } catch (err) {
    app?.log?.warn?.({ err }, 'audit append failed');
  }
}

class Job {
  constructor(app, { kind, title, host, target, actor, danger, steps }) {
    this.app = app;
    this.id = crypto.randomBytes(8).toString('hex');
    this.kind = kind;
    this.title = title;
    this.host = host ?? null;
    this.target = target ?? null;
    this.actor = actor ?? 'webapp';
    this.danger = !!danger;
    this.status = 'running';
    this.started_at = nowIso();
    this.finished_at = null;
    this.error = null;
    // The plan, declared before anything runs. `key` is stable; `label` is prose.
    this.steps = (steps || []).map((s) => ({
      key: s.key,
      label: s.label,
      detail: s.detail ?? null,
      status: /** @type {StepStatus} */ ('pending'),
      started_at: null,
      finished_at: null,
      ms: null,
      output: null,
    }));
  }

  snapshot() {
    return {
      id: this.id, kind: this.kind, title: this.title, host: this.host,
      target: this.target, actor: this.actor, danger: this.danger,
      status: this.status, started_at: this.started_at, finished_at: this.finished_at,
      error: this.error,
      steps: this.steps.map((s) => ({ ...s })),
    };
  }

  emit() {
    try { this.app.events?.emit?.('job', this.snapshot()); } catch (_) { /* bus optional */ }
  }

  find(key) {
    const s = this.steps.find((x) => x.key === key);
    if (!s) throw new Error(`job ${this.kind}: no step declared with key '${key}'`);
    return s;
  }

  /**
   * Run one declared step. The callback gets a `note()` it can call to attach a line
   * of human-readable output — what the agent actually said, which is the detail that
   * was missing before.
   *
   * A throw marks the step failed and propagates, so a job reads as a plain async
   * function: `await job.step('a', ...); await job.step('b', ...)` stops at the first
   * failure, and every step after it stays `pending` rather than being silently
   * dropped. "We never got there" is information too.
   */
  async step(key, fn) {
    const s = this.find(key);
    s.status = 'running';
    s.started_at = nowIso();
    this.emit();
    const t0 = Date.now();
    const note = (line) => {
      s.output = s.output ? `${s.output}\n${line}` : String(line);
      this.emit();
    };
    try {
      const out = await fn(note);
      s.status = 'ok';
      s.finished_at = nowIso();
      s.ms = Date.now() - t0;
      this.emit();
      return out;
    } catch (err) {
      s.status = 'failed';
      s.finished_at = nowIso();
      s.ms = Date.now() - t0;
      note(err.message || String(err));
      this.emit();
      throw err;
    }
  }

  /** Mark a declared step deliberately not taken, with the reason. */
  skip(key, why) {
    const s = this.find(key);
    s.status = 'skipped';
    s.detail = why || s.detail;
    s.finished_at = nowIso();
    this.emit();
  }

  finish(status, error) {
    if (this.finished_at) return this.snapshot();
    this.status = status;
    this.error = error ? (error.message || String(error)) : null;
    this.finished_at = nowIso();
    this.emit();
    appendAudit(this.app, {
      ...this.snapshot(),
      // Denormalised for grep-ability: the whole point of a plain-text audit log is
      // that it stays useful without this application.
      summary: `${this.kind} ${this.target || this.host || ''} → ${status}`.trim(),
    });
    return this.snapshot();
  }
}

function createJobs(app) {
  /** @type {Job[]} */
  const resident = [];

  function create(spec) {
    const job = new Job(app, spec);
    resident.unshift(job);
    if (resident.length > MAX_RESIDENT) resident.length = MAX_RESIDENT;
    job.emit();
    return job;
  }

  /**
   * Run a whole job: declare the plan, execute the body, always finish exactly once.
   * The body's return value becomes the HTTP response payload alongside the job, so a
   * route stays a route — the caller still gets its normal JSON, and now also a job id
   * it can follow.
   */
  async function run(spec, body) {
    const job = create(spec);
    try {
      const result = await body(job);
      job.finish('ok');
      return { job: job.snapshot(), result };
    } catch (err) {
      job.finish('failed', err);
      const wrapped = new Error(err.message || String(err));
      wrapped.statusCode = err.statusCode || 502;
      wrapped.job = job.snapshot();
      throw wrapped;
    }
  }

  const list = ({ limit = 50 } = {}) => resident.slice(0, limit).map((j) => j.snapshot());
  const get = (id) => resident.find((j) => j.id === id)?.snapshot() ?? null;

  /**
   * Read the durable trail back, newest first. Reads whole months rather than seeking,
   * which is fine at this scale (a busy month is a few hundred lines) and keeps the
   * format something you can also just `cat`.
   */
  function audit({ days = 30, limit = 200, kind = null, host = null } = {}) {
    const cutoff = Date.now() - days * 86_400_000;
    const months = new Set();
    for (let d = new Date(); d.getTime() > cutoff - 86_400_000; d.setUTCMonth(d.getUTCMonth() - 1)) {
      months.add(auditPath(d));
      if (months.size > 14) break;
    }
    const out = [];
    for (const file of months) {
      let text;
      try { text = fs.readFileSync(file, 'utf8'); } catch (_) { continue; }
      for (const line of text.split('\n')) {
        if (!line.trim()) continue;
        let row;
        try { row = JSON.parse(line); } catch (_) { continue; }
        if (Date.parse(row.started_at) < cutoff) continue;
        if (kind && row.kind !== kind) continue;
        if (host && row.host !== host) continue;
        out.push(row);
      }
    }
    out.sort((a, b) => Date.parse(b.started_at) - Date.parse(a.started_at));
    return out.slice(0, limit);
  }

  return { create, run, list, get, audit, AUDIT_DIR };
}

module.exports = { createJobs, Job };
