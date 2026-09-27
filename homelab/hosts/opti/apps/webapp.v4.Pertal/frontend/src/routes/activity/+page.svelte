<script lang="ts">
  // One feed: every action (with its steps), every container state change, every data
  // source that failed or recovered. History from the API, new entries live over SSE.
  import { onMount } from 'svelte';
  import JobSteps from '$lib/components/JobSteps.svelte';
  import { live } from '$lib/live.svelte';
  import { api } from '$lib/api';
  import { ago, clock } from '$lib/format';
  import type { ActivityEntry } from '$lib/types';

  type Filter = 'all' | 'actions' | 'changes' | 'problems';
  let filter = $state<Filter>('all');
  let base = $state<ActivityEntry[]>([]);
  let err = $state<string | null>(null);
  let loaded = $state(false);
  let expanded = $state<Record<string, boolean>>({});

  async function load() {
    try {
      base = (await api.activity(300)).items;
      err = null;
    } catch (e) {
      err = (e as Error).message;
    } finally {
      loaded = true;
    }
  }
  onMount(load);

  // Merge: history + live activity entries + live jobs (which update step by step).
  const items = $derived.by(() => {
    const byId = new Map<string, ActivityEntry>();
    for (const e of base) byId.set(e.id, e);
    for (const e of live.activity) byId.set(e.id, e);
    for (const j of live.jobs) byId.set(j.id, { id: j.id, at: j.started_at, type: 'job', severity: j.status === 'failed' ? 'crit' : 'ok', host: j.host, resource_id: j.resource, job: j });
    return [...byId.values()].sort((a, b) => b.at.localeCompare(a.at));
  });
  const shown = $derived(items.filter((e) =>
    filter === 'all' ? true
      : filter === 'actions' ? e.type === 'job'
      : filter === 'changes' ? e.type !== 'job'
      : e.severity !== 'ok' || e.job?.status === 'failed',
  ));
</script>

<svelte:head><title>Activity · Pertal</title></svelte:head>

<div class="head">
  <h1>Activity</h1>
  <div class="seg" role="group" aria-label="Filter">
    {#each ['all', 'actions', 'changes', 'problems'] as f}
      <button aria-pressed={filter === f} onclick={() => (filter = f as Filter)}>{f}</button>
    {/each}
  </div>
</div>

{#if err}<p class="banner">Could not load history ({err}); showing live entries only.</p>{/if}

<div class="panel">
  <div class="rows">
    {#each shown as e (e.id)}
      <div class="row item">
        {#if e.job}
          <span class="badge {e.job.status === 'failed' ? 'crit' : e.job.status === 'running' ? 'accent' : ''}">{e.job.status}</span>
          <div class="main">
            <button class="linkish" onclick={() => (expanded[e.id] = !expanded[e.id])}>{e.job.title}</button>
            <span class="faint">· {e.job.actor}{#if e.job.resource} · <a href="/r/{e.job.resource}">open</a>{/if}</span>
            {#if e.job.error}<div class="errline">{e.job.error}</div>{/if}
            {#if expanded[e.id]}<div class="steps"><JobSteps job={e.job} /></div>{/if}
          </div>
        {:else}
          <span class="kind faint">{e.type}</span>
          <div class="main">
            <span class="dot {e.severity}"></span>
            {#if e.resource_id}<a href="/r/{e.resource_id}">{e.text}</a>{:else}<span class="muted">{e.text}</span>{/if}
          </div>
        {/if}
        <span class="faint when" title={e.at}>{clock(e.at)} · {ago(e.at, live.now)}</span>
      </div>
    {:else}
      <div class="empty">{loaded ? 'Nothing here yet.' : 'Loading…'}</div>
    {/each}
  </div>
</div>

<style>
  .head { display: flex; align-items: center; justify-content: space-between; gap: var(--s3); flex-wrap: wrap; margin-bottom: var(--s3); }
  .seg button { text-transform: capitalize; }
  .item { grid-template-columns: 70px minmax(0, 1fr) auto; align-items: start; font-size: var(--fs-sm); }
  .main { min-width: 0; display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
  .main .dot { margin-right: 2px; }
  .kind { font-size: var(--fs-xs); text-transform: uppercase; letter-spacing: .05em; padding-top: 2px; }
  .linkish { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; text-align: left; }
  .errline { flex-basis: 100%; color: var(--crit); font-size: var(--fs-xs); }
  .steps { flex-basis: 100%; margin-top: 6px; }
  .when { font-size: var(--fs-xs); white-space: nowrap; }
  .banner { padding: 8px 12px; border: 1px solid var(--warn); border-radius: var(--r); background: var(--warn-dim); color: var(--warn); font-size: var(--fs-sm); }
  @media (max-width: 720px) {
    .item { grid-template-columns: minmax(0, 1fr); }
    .kind { display: none; }
  }
</style>
