// Acknowledged issues — "I know about this, stop showing it to me."
//
// Some findings are true and permanent: opti's boot disk has 272 reallocated sectors and
// will keep creeping up; Peter knows, and a red opti on every page trains him to ignore
// red. An ack takes an issue out of "Needs attention", out of the counts and out of the
// resource's status, and lists it under "Acknowledged" instead.
//
// What an ack matches is the issue's *subject*, not its exact text: numbers and dates
// are wildcards and the text is cut at the first "(", ";" or ",". So
//   "sdb SMART reallocated sectors: 272 (up from 264 since 2026-09-10; grew …)"
// stays acknowledged at 280, but "sdb SMART pending sectors: 1" is a new subject and
// shows. An ack also stops matching when the issue gets MORE severe than it was when
// acknowledged (warn → crit), and a grouped issue ("16 findings") comes back when a
// detail appears that wasn't in the group at ack time. Acks never expire on their own.
//
// Stored as one small JSON file on the shared arch_data volume, so they survive
// restarts, deploys and the cutover.
'use strict';
const fs = require('fs');
const path = require('path');
const { ARCH_DATA_DIR } = require('./paths');

const FILE = path.join(ARCH_DATA_DIR, 'pertal', 'acks.json');
const RANK = { ok: 0, offline: 0, unknown: 1, warn: 2, crit: 3 };

const wild = (s) => String(s ?? '')
  .replace(/\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?/g, '#')
  .replace(/\d+(?:\.\d+)*/g, '#')
  .replace(/\s+/g, ' ').trim().toLowerCase();

/** The part of an issue text that names *what* is wrong, not how much. */
const subject = (text) => wild(text).split(/[(;,]/)[0].trim();

/** Stable identity of an issue across value changes. `scope` is the resource, or the
 *  reporting tool for findings that name no resource. */
function issueKey(issue) {
  const scope = issue.resource_id ?? `${issue.resource}@${issue.host ?? ''}`;
  return `${scope}|${issue.source}|${subject(issue.text)}`;
}

function createAcks({ persist = true, log = console } = {}) {
  /** @type {Map<string, any>} */
  const acks = new Map();
  if (persist) {
    try {
      for (const a of JSON.parse(fs.readFileSync(FILE, 'utf8')).acks ?? []) acks.set(a.key, a);
    } catch (err) {
      if (err.code !== 'ENOENT') log.warn?.({ err }, 'acks: could not read, starting empty');
    }
  }

  function save() {
    if (!persist) return;
    fs.mkdirSync(path.dirname(FILE), { recursive: true });
    const tmp = `${FILE}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify({ acks: [...acks.values()] }, null, 2), 'utf8');
    fs.renameSync(tmp, FILE);
  }

  /** The ack covering this issue right now, or null. */
  function match(issue) {
    const a = acks.get(issue.key ?? issueKey(issue));
    if (!a) return null;
    if (RANK[issue.severity] > RANK[a.severity]) return null; // got worse → show again
    if (a.details && issue.details?.some((d) => !a.details.includes(wild(d)))) return null; // something new in the group
    return a;
  }

  function add(issue, { note = null, by = 'webapp' } = {}) {
    const key = issue.key ?? issueKey(issue);
    const a = {
      key, severity: issue.severity, text: issue.text, resource: issue.resource, host: issue.host ?? null,
      source: issue.source, details: issue.details ? issue.details.map(wild) : undefined,
      note, by, at: new Date().toISOString(),
    };
    acks.set(key, a);
    save();
    return a;
  }

  function remove(key) {
    const had = acks.delete(key);
    if (had) save();
    return had;
  }

  return { match, add, remove, get: (key) => acks.get(key) ?? null, list: () => [...acks.values()], FILE };
}

module.exports = { createAcks, issueKey, subject };
