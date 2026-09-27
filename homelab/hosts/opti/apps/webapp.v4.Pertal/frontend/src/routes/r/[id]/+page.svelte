<script lang="ts">
  // The resource page — one template for every host and container: header, command bar,
  // then tabs. Live fields come from the store; history (jobs, audit, activity) is fetched
  // and refetched when a job for this resource finishes.
  import { page } from '$app/state';
  import { Server, Container, Bot, Smartphone, ChevronRight } from '@lucide/svelte';
  import StatusDot from '$lib/components/StatusDot.svelte';
  import Age from '$lib/components/Age.svelte';
  import CommandBar from '$lib/components/CommandBar.svelte';
  import JobSteps from '$lib/components/JobSteps.svelte';
  import { live } from '$lib/live.svelte';
  import { api } from '$lib/api';
  import { pct, uptime, rate, bytes, tone, ago, clock } from '$lib/format';
  import type { ActivityEntry, Job } from '$lib/types';

  const id = $derived(decodeURIComponent(page.params.id ?? ''));
  const r = $derived(live.byId(id));
  const children = $derived(r?.type === 'host' ? live.resources.filter((x) => x.type === 'container' && x.host === r.id) : []);
  let tab = $state<'overview' | 'activity'>('overview');

  let history = $state<{ jobs: Job[]; audit: Job[]; activity: ActivityEntry[] } | null>(null);
  let histErr = $state<string | null>(null);
  async function loadHistory(target: string) {
    try {
      const d = await api.resource(target);
      history = { jobs: d.jobs, audit: d.audit, activity: d.activity };
      histErr = null;
    } catch (e) {
      histErr = (e as Error).message;
    }
  }
  $effect(() => { history = null; void loadHistory(id); });

  // When a job on this resource finishes, pull fresh history.
  const finishedMine = $derived(live.jobs.filter((j) => j.resource === id && j.status !== 'running').map((j) => j.id).join());
  $effect(() => { if (finishedMine) void loadHistory(id); });

  const liveJobs = $derived(live.jobs.filter((j) => j.resource === id));
  const feed = $derived.by(() => {
    if (!history) return [];
    const seen = new Set(liveJobs.map((j) => j.id));
    const jobs = [...liveJobs, ...history.jobs.filter((j) => !seen.has(j.id)), ...history.audit.filter((j) => !seen.has(j.id))]
      .filter((j, i, a) => a.findIndex((x) => x.id === j.id) === i)
      .map((j) => ({ at: j.started_at, job: j, entry: null as ActivityEntry | null }));
    const acts = history.activity.map((a) => ({ at: a.at, job: null as Job | null, entry: a }));
    return [...jobs, ...acts].sort((a, b) => b.at.localeCompare(a.at));
  });
  let expanded = $state<Record<string, boolean>>({});
</script>

<svelte:head><title>{r?.name ?? id} · Pertal</title></svelte:head>

{#if !r}
  <p class="empty">{live.loaded ? `No resource "${id}".` : 'Loading…'}</p>
{:else}
  <nav class="crumbs faint" aria-label="Breadcrumb">
    <a href="/resources">Resources</a><ChevronRight size={12} />
    {#if r.type === 'container'}<a href="/r/{r.host}">{r.host}</a><ChevronRight size={12} />{/if}
    <span>{r.name}</span>
  </nav>

  <header class="rhead">
    <span class="ico">
      {#if r.type === 'host'}{#if r.id === 'android'}<Smartphone size={22} />{:else}<Server size={22} />{/if}
      {:else if r.kind === 'bot'}<Bot size={22} />{:else}<Container size={22} />{/if}
    </span>
    <div class="title">
      <h1>{r.name}</h1>
      <div class="sub faint">{r.type === 'host' ? 'Host' : `${r.kind === 'bot' ? 'Bot' : r.kind === 'infra' ? 'Infrastructure' : 'App'} on ${r.host}`} · {r.state_text}</div>
    </div>
    <span class="badge {r.status === 'crit' ? 'crit' : r.status === 'warn' ? 'warn' : ''}"><StatusDot status={r.status} />{r.status === 'ok' ? 'healthy' : r.status}</span>
  </header>

  <CommandBar resource={r} />

  <div class="tabs" role="tablist">
    <button role="tab" aria-selected={tab === 'overview'} onclick={() => (tab = 'overview')}>Overview</button>
    <button role="tab" aria-selected={tab === 'activity'} onclick={() => (tab = 'activity')}>Activity</button>
    <button role="tab" disabled title="Coming in the v4 build">Logs</button>
    <button role="tab" disabled title="Coming in the v4 build">Metrics</button>
  </div>

  {#if tab === 'overview'}
    {#if r.reasons.length}
      <section class="panel reasons">
        {#each r.reasons as why}
          <div class="row reason"><span class="badge {why.severity}">{why.severity === 'crit' ? 'critical' : why.severity}</span><span>{why.text}</span><span class="faint src">{why.source}</span></div>
        {/each}
      </section>
    {/if}

    <section class="essentials">
      {#each r.facts as f (f.label)}
        <div class="fact"><span class="faint">{f.label}</span><span class:warn={f.tone === 'warn'}>{f.value ?? '—'}</span></div>
      {/each}
      <div class="fact"><span class="faint">Data</span><span><Age at={r.updated_at} staleAfterMs={60_000} /></span></div>
    </section>

    {#if r.metrics}
      <section class="tiles">
        <div class="tile"><span class="faint">CPU</span><strong class="num">{pct(r.metrics.cpu_pct)}</strong><div class="meter {tone(r.metrics.cpu_pct)}"><span style="width:{r.metrics.cpu_pct ?? 0}%"></span></div><span class="faint">load {r.metrics.load1 ?? '—'} · {r.metrics.cores ?? '?'} cores</span></div>
        <div class="tile"><span class="faint">Memory</span><strong class="num">{pct(r.metrics.mem_pct)}</strong><div class="meter {tone(r.metrics.mem_pct)}"><span style="width:{r.metrics.mem_pct ?? 0}%"></span></div><span class="faint">of {bytes(r.metrics.mem_total_bytes)}</span></div>
        <div class="tile"><span class="faint">Temperature</span><strong class="num">{r.metrics.temp_c != null ? `${Math.round(r.metrics.temp_c)} °C` : '—'}</strong><span class="faint">up {uptime(r.metrics.uptime_s)}</span></div>
        <div class="tile"><span class="faint">Network</span><strong class="num">↓ {rate(r.metrics.rx_bps)}</strong><span class="faint">↑ {rate(r.metrics.tx_bps)}</span></div>
      </section>
    {/if}

    {#if children.length}
      <section class="panel">
        <div class="panel-head"><h2>Containers</h2><span class="faint">{r.counts?.running}/{r.counts?.containers} running</span></div>
        <div class="rows">
          {#each children as c (c.id)}
            <a class="row child" href="/r/{c.id}">
              <StatusDot status={c.status} /><span>{c.name}</span>
              <span class="faint kind">{c.kind}</span>
              <span class="st" class:warn={c.status === 'warn'} class:crit={c.status === 'crit'}>{c.status_text}</span>
            </a>
          {/each}
        </div>
      </section>
    {/if}
  {:else}
    <section class="panel">
      {#if histErr}<p class="empty">Could not load history: {histErr}</p>{/if}
      <div class="rows">
        {#each feed as f (f.job?.id ?? f.entry?.id)}
          {#if f.job}
            <div class="row feed">
              <span class="badge {f.job.status === 'failed' ? 'crit' : f.job.status === 'running' ? 'accent' : ''}">{f.job.status}</span>
              <div class="feed-main">
                <button class="linkish" onclick={() => (expanded[f.job!.id] = !expanded[f.job!.id])}>{f.job.title}</button>
                <span class="faint">by {f.job.actor}</span>
                {#if f.job.error}<div class="errline">{f.job.error}</div>{/if}
                {#if expanded[f.job.id]}<div class="steps"><JobSteps job={f.job} /></div>{/if}
              </div>
              <span class="faint when" title={f.at}>{clock(f.at)}</span>
            </div>
          {:else if f.entry}
            <div class="row feed">
              <span class="dot {f.entry.severity}"></span>
              <div class="feed-main muted">{f.entry.text}</div>
              <span class="faint when" title={f.at}>{ago(f.at, live.now)}</span>
            </div>
          {/if}
        {:else}
          <div class="empty">{history ? 'No recorded activity for this resource yet.' : 'Loading…'}</div>
        {/each}
      </div>
    </section>
  {/if}
{/if}

<style>
  .crumbs { display: flex; align-items: center; gap: 4px; font-size: var(--fs-sm); margin-bottom: var(--s2); }
  .rhead { display: flex; align-items: center; gap: var(--s3); margin-bottom: var(--s2); }
  .ico { display: flex; width: 38px; height: 38px; align-items: center; justify-content: center; border-radius: var(--r); background: var(--surface-2); color: var(--ink-2); }
  .title { flex: 1; min-width: 0; }
  .sub { font-size: var(--fs-sm); }
  .tabs { display: flex; gap: var(--s4); margin: var(--s2) 0 var(--s4); border-bottom: 1px solid var(--border); }
  .tabs button { border: 0; background: none; padding: 8px 0; color: var(--ink-2); cursor: pointer; border-bottom: 2px solid transparent; }
  .tabs button[aria-selected='true'] { color: var(--ink); border-bottom-color: var(--accent); }
  .tabs button:disabled { color: var(--ink-3); cursor: default; opacity: .6; }
  .reasons { margin-bottom: var(--s3); }
  .reason { grid-template-columns: auto minmax(0, 1fr) auto; font-size: var(--fs-sm); }
  .src { font: var(--fs-xs) var(--mono); }
  .essentials { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 6px var(--s5); margin-bottom: var(--s4); }
  .fact { display: grid; grid-template-columns: 90px minmax(0, 1fr); gap: 8px; font-size: var(--fs-sm); padding: 3px 0; border-bottom: 1px dashed var(--border); overflow-wrap: anywhere; }
  .warn { color: var(--warn); }
  .crit { color: var(--crit); }
  .tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: var(--s3); margin-bottom: var(--s4); }
  .tile { display: flex; flex-direction: column; gap: 4px; padding: var(--s3); background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); font-size: var(--fs-sm); }
  .tile strong { font-size: var(--fs-xl); font-weight: 600; }
  .child { grid-template-columns: 12px minmax(120px, 1fr) 60px minmax(0, 2fr); font-size: var(--fs-sm); }
  .kind { font-size: var(--fs-xs); }
  .st { color: var(--ink-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .feed { grid-template-columns: auto minmax(0, 1fr) auto; align-items: start; font-size: var(--fs-sm); }
  .feed-main { min-width: 0; }
  .linkish { border: 0; background: none; padding: 0; color: var(--accent); cursor: pointer; text-align: left; }
  .errline { color: var(--crit); font-size: var(--fs-xs); margin-top: 2px; }
  .steps { margin-top: 8px; }
  .when { font-size: var(--fs-xs); white-space: nowrap; }
  @media (max-width: 720px) {
    .child { grid-template-columns: 12px minmax(0, 1fr) auto; }
    .child .kind { display: none; }
  }
</style>
