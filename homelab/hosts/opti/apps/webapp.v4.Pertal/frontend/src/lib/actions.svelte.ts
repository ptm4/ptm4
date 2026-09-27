// Client side of the action pipeline: confirm risky actions, start jobs, and keep the
// job tray pointed at what *this* browser started. Errors that stop a job from even
// starting (428, 400, network) land in the tray too — nothing fails silently.
import { api, ApiError } from './api';
import { live } from './live.svelte';
import type { ActionRef, Resource } from './types';

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
