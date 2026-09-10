// Live jobs — the client half of the stepped-execution work.
//
// The backend emits a full job snapshot on every step transition (see backend/lib/jobs.js).
// This store keeps the ones worth showing, newest first, and the drawer renders them.
//
// Snapshots are whole, not deltas, so the merge rule is simply "last one wins per id".
// That means a dropped event costs nothing — the next transition carries the complete
// state again, and a reconnect re-seeds from /api/jobs. There is deliberately no
// reconciliation logic here, because the alternative (accumulating patches) is how a
// progress display drifts out of sync with the thing it is describing, which for this
// feature would be worse than showing nothing.
import { browser } from '$app/environment';

export interface JobStep {
  key: string;
  label: string;
  detail: string | null;
  status: 'pending' | 'running' | 'ok' | 'failed' | 'skipped';
  started_at: string | null;
  finished_at: string | null;
  ms: number | null;
  output: string | null;
}

export interface Job {
  id: string;
  kind: string;
  title: string;
  host: string | null;
  target: string | null;
  actor: string;
  danger: boolean;
  status: 'running' | 'ok' | 'failed';
  started_at: string;
  finished_at: string | null;
  error: string | null;
  steps: JobStep[];
}

// How long a finished job stays in the drawer before it stops asking for attention.
// Long enough to read the outcome, short enough that the drawer is not a graveyard —
// the permanent copy is the audit page, so nothing is lost when this expires.
const KEEP_FINISHED_MS = 90_000;

let jobs = $state<Job[]>([]);
let dismissed = $state<Set<string>>(new Set());
let expanded = $state<string | null>(null);
let sweeper: ReturnType<typeof setInterval> | null = null;

function visible(list: Job[]): Job[] {
  const now = Date.now();
  return list.filter((j) => {
    if (dismissed.has(j.id)) return false;
    if (j.status === 'running') return true;
    const end = Date.parse(j.finished_at || j.started_at);
    // A failure stays until it is dismissed. Something went wrong; it should not
    // quietly disappear because you looked away.
    if (j.status === 'failed') return true;
    return Number.isFinite(end) && now - end < KEEP_FINISHED_MS;
  });
}

export const jobStore = {
  get all() { return jobs; },
  get shown() { return visible(jobs); },
  get running() { return jobs.filter((j) => j.status === 'running'); },
  get expanded() { return expanded; },

  /** Merge one snapshot. Whole-object replace by id; see the note at the top. */
  push(job: Job) {
    const i = jobs.findIndex((j) => j.id === job.id);
    if (i === -1) {
      jobs = [job, ...jobs].slice(0, 50);
      // A brand-new job opens itself: you pressed a button, you want to see the plan.
      if (job.status === 'running') expanded = job.id;
    } else {
      const next = jobs.slice();
      next[i] = job;
      jobs = next;
    }
  },

  seed(list: Job[]) {
    for (const j of [...list].reverse()) this.push(j);
  },

  toggle(id: string) { expanded = expanded === id ? null : id; },
  dismiss(id: string) {
    dismissed = new Set([...dismissed, id]);
    if (expanded === id) expanded = null;
  },

  /** Re-render on a timer so time-based expiry actually takes effect. */
  start() {
    if (!browser || sweeper) return;
    sweeper = setInterval(() => { jobs = jobs.slice(); }, 5_000);
  },
  stop() {
    if (sweeper) { clearInterval(sweeper); sweeper = null; }
  },
};
