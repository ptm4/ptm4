// Client side of the action pipeline: confirm risky actions, start jobs, and keep the
// job tray pointed at what *this* browser started. Errors that stop a job from even
// starting (428, 400, network) land in the tray too — nothing fails silently.
import { api, ApiError } from './api';
import { live } from './live.svelte';
import type { ActionRef, Job, Resource } from './types';

interface StartError { id: string; title: string; text: string; at: number }

class Actions {
  pending = $state<{ action: ActionRef; resource: Resource } | null>(null);
  trayOpen = $state(false);
  mine = $state<string[]>([]);
  errors = $state<StartError[]>([]);

  run(action: ActionRef, resource: Resource) {
    if (action.risky) {
      this.pending = { action, resource };
      return;
    }
    void this.#start(action, resource, false);
  }

  confirm() {
    const p = this.pending;
    this.pending = null;
    if (p) void this.#start(p.action, p.resource, true);
  }

  cancel() {
    this.pending = null;
  }

  dismissError(id: string) {
    this.errors = this.errors.filter((e) => e.id !== id);
  }

  // A generic confirm question for pages whose buttons are not resource actions
  // (e.g. deleting a torrent). ConfirmDialog renders it.
  question = $state<{ title: string; body: string; label: string; run: () => void } | null>(null);
  ask(q: { title: string; body: string; label: string; run: () => void }) {
    this.question = q;
  }

  // Put a job started elsewhere (Downloads, …) into the tray. `open: false` for jobs whose
  // effect is visible where you clicked (acks) — the tray still has them.
  track(job: Job, { open = true } = {}) {
    live.upsertJob(job);
    this.mine = [job.id, ...this.mine].slice(0, 20);
    if (open) this.trayOpen = true;
  }

  // Acknowledge / un-acknowledge an issue (backend/lib/acks.js). The row moves between
  // "Needs attention" and "Acknowledged" as soon as the job's rebuild lands over SSE.
  async ack(key: string, label: string, on: boolean): Promise<boolean> {
    try {
      const { job } = on ? await api.acks.add(key) : await api.acks.remove(key);
      this.track(job, { open: false });
      return true;
    } catch (e) {
      this.fail(`${on ? 'Acknowledge' : 'Un-acknowledge'} ${label}`, e);
      return false;
    }
  }

  fail(title: string, e: unknown) {
    const text = e instanceof ApiError ? e.message : `could not reach Pertal: ${(e as Error).message}`;
    this.errors = [{ id: crypto.randomUUID(), title, text, at: Date.now() }, ...this.errors].slice(0, 5);
    this.trayOpen = true;
  }

  async #start(action: ActionRef, resource: Resource, confirm: boolean) {
    this.trayOpen = true;
    try {
      const { job } = await api.action(action.kind, resource.id, { confirm });
      live.upsertJob(job);
      this.mine = [job.id, ...this.mine].slice(0, 20);
    } catch (e) {
      const text = e instanceof ApiError ? e.message : `could not reach Pertal: ${(e as Error).message}`;
      this.errors = [
        { id: crypto.randomUUID(), title: `${action.label} ${resource.name}`, text, at: Date.now() },
        ...this.errors,
      ].slice(0, 5);
    }
  }
}

export const actions = new Actions();
